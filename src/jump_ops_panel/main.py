from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .config_loader import list_profile_summaries, load_config, project_root
from .dashboard_store import DashboardStore
from .jms_runner import RunResult
from .models import AppConfig
from .op_jobs import OpJobStore
from .manual_exec_cache import ManualExecCache
from .schedule_store import ScheduleStore
from .script_catalog import ScriptCatalog
from .script_upload import upload_script_file

LOGGER = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _jop_clock_seed() -> str:
    from datetime import datetime

    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


TEMPLATES.env.globals["jop_clock_seed"] = _jop_clock_seed


@dataclass
class AppState:
    config_path: Path
    data_dir: Path
    root: Path
    config: AppConfig
    dashboard: DashboardStore = field(default_factory=DashboardStore)
    op_jobs: OpJobStore = field(default_factory=OpJobStore)
    script_catalog: ScriptCatalog | None = None
    schedule_store: ScheduleStore | None = None
    manual_exec_cache: ManualExecCache = field(default_factory=ManualExecCache)
    last_results: dict[str, RunResult] = field(default_factory=dict)


def _config_path() -> Path:
    raw = os.getenv("JOP_CONFIG", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    candidate = project_root() / "config" / "profiles.yaml"
    if candidate.is_file():
        return candidate
    return project_root() / "config" / "profiles.example.yaml"


def _data_dir() -> Path:
    raw = os.getenv("JOP_DATA_DIR", "").strip()
    path = Path(raw).expanduser() if raw else project_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _active_profile(state: AppState, profile_id: str | None):
    if not state.config.profiles:
        raise HTTPException(status_code=503, detail="No profiles configured.")
    if profile_id:
        try:
            return state.config.get_profile(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Profile not found.") from exc
    return state.config.profiles[0]


def _scripts_context(state: AppState, profile_id: str) -> dict:
    assert state.script_catalog is not None
    return {"scripts": state.script_catalog.list_scripts(profile_id)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_path = _config_path()
    data_dir = _data_dir()
    config = load_config(config_path)
    scheduler = AsyncIOScheduler()
    jop = AppState(
        config_path=config_path,
        data_dir=data_dir,
        root=project_root(),
        config=config,
        script_catalog=ScriptCatalog(data_dir),
    )
    app.state.jop = jop
    jop.schedule_store = ScheduleStore(
        scheduler,
        data_dir=data_dir,
        state_getter=lambda: app.state.jop,
    )
    jop.schedule_store.load_from_disk()
    await jop.schedule_store.bootstrap_jobs()
    scheduler.start()
    LOGGER.info("Jump Ops Panel started; config=%s", config_path)
    yield
    scheduler.shutdown(wait=False)
    if jop.schedule_store:
        await jop.schedule_store.close_all_sessions()
    await jop.manual_exec_cache.close_all()


app = FastAPI(title="Jump Ops Panel", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, profile: str | None = None) -> HTMLResponse:
    state: AppState = request.app.state.jop
    state.config = load_config(state.config_path)
    active = _active_profile(state, profile)
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "profiles": list_profile_summaries(state.config),
            "active_id": active.id,
            "profile": active,
            "last_result": state.last_results.get(active.id),
            **_scripts_context(state, active.id),
        },
    )


@app.post("/profiles/{profile_id}/scripts/upload", response_class=HTMLResponse)
async def upload_script(
    request: Request,
    profile_id: str,
    file: UploadFile = File(...),
) -> HTMLResponse:
    state: AppState = request.app.state.jop
    state.config = load_config(state.config_path)
    profile = _active_profile(state, profile_id)
    assert state.script_catalog is not None
    body = await file.read()
    filename = file.filename or "script.sh"
    try:
        entry = await upload_script_file(
            profile,
            state.config,
            data_dir=state.data_dir,
            filename=filename,
            body=body,
            catalog=state.script_catalog,
        )
    except ValueError as exc:
        return TEMPLATES.TemplateResponse(
            request,
            "partials/upload_feedback.html",
            {
                "ok": False,
                "message": str(exc),
            },
        )
    except Exception as exc:
        LOGGER.exception("Upload failed")
        return TEMPLATES.TemplateResponse(
            request,
            "partials/upload_feedback.html",
            {
                "ok": False,
                "message": f"上传失败：{exc}",
            },
        )
    response = TEMPLATES.TemplateResponse(
        request,
        "partials/upload_feedback.html",
        {
            "ok": True,
            "message": f"上传成功：{entry.name}",
            "oob": True,
            **_scripts_context(state, profile_id),
            "selected": entry.name,
        },
    )
    if request.headers.get("HX-Request"):
        response.headers["HX-Trigger"] = "jop-upload-reset"
    return response


@app.post("/profiles/{profile_id}/exec", response_class=HTMLResponse)
async def exec_command(
    request: Request,
    profile_id: str,
    target: str = Form(...),
    args_line: str = Form(""),
) -> HTMLResponse:
    state: AppState = request.app.state.jop
    state.config = load_config(state.config_path)
    profile = _active_profile(state, profile_id)
    job = state.op_jobs.start_exec(
        profile,
        state.config,
        target=target,
        args_line=args_line,
        data_dir=state.data_dir,
        manual_exec_cache=state.manual_exec_cache,
    )
    return TEMPLATES.TemplateResponse(
        request,
        "partials/op_job_poll.html",
        {"job": job, "profile_id": profile_id, "result_element_id": "exec-result"},
    )


@app.get("/profiles/{profile_id}/ops/jobs/{job_id}", response_class=HTMLResponse)
async def op_job_status(
    request: Request,
    profile_id: str,
    job_id: str,
    result_element_id: str = "run-result",
) -> HTMLResponse:
    state: AppState = request.app.state.jop
    job = state.op_jobs.get(job_id)
    if job is None or job.profile_id != profile_id:
        element_id = request.query_params.get("result_element_id", result_element_id)
        return TEMPLATES.TemplateResponse(
            request,
            "partials/exec_result.html",
            {
                "last_result": None,
                "result_element_id": element_id,
                "job_lost_message": "任务不存在或 Pod 已重启，请重新 Exec。",
            },
        )
    element_id = request.query_params.get("result_element_id", result_element_id)
    if job.status in ("pending", "running"):
        return TEMPLATES.TemplateResponse(
            request,
            "partials/op_job_poll.html",
            {"job": job, "profile_id": profile_id, "result_element_id": element_id},
        )
    if job.status == "failed" and job.result is None:
        finished = job.finished_at or job.created_at
        result = RunResult(
            profile_id=profile_id,
            label=job.label,
            command="",
            exit_status=None,
            stdout="",
            started_at=job.created_at,
            finished_at=finished,
            error=job.error or "执行失败",
        )
    else:
        result = job.result
        if result is None:
            raise HTTPException(status_code=500, detail="Job finished without result.")
    state.last_results[profile_id] = result
    return TEMPLATES.TemplateResponse(
        request,
        "partials/exec_result.html",
        {
            "last_result": result,
            "result_element_id": element_id,
            "job_lost_message": None,
        },
    )


@app.get("/profiles/{profile_id}/schedules", response_class=HTMLResponse)
async def list_schedules(request: Request, profile_id: str) -> HTMLResponse:
    state: AppState = request.app.state.jop
    assert state.schedule_store is not None
    entries = state.schedule_store.list_for_profile(profile_id)
    return TEMPLATES.TemplateResponse(
        request,
        "partials/schedule_panel_list.html",
        {"entries": entries, "profile_id": profile_id},
    )


@app.post("/profiles/{profile_id}/schedules", response_class=HTMLResponse)
async def add_schedule(
    request: Request,
    profile_id: str,
    target: str = Form(...),
    args_line: str = Form(""),
    interval_seconds: int = Form(...),
) -> HTMLResponse:
    state: AppState = request.app.state.jop
    state.config = load_config(state.config_path)
    profile = _active_profile(state, profile_id)
    assert state.schedule_store is not None
    try:
        await state.schedule_store.add(
            profile,
            state.config,
            target=target,
            args_line=args_line,
            interval_seconds=interval_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    entries = state.schedule_store.list_for_profile(profile_id)
    return TEMPLATES.TemplateResponse(
        request,
        "partials/schedule_panel_list.html",
        {"entries": entries, "profile_id": profile_id},
    )


@app.post("/profiles/{profile_id}/schedules/{schedule_id}/toggle", response_class=HTMLResponse)
async def toggle_schedule(
    request: Request,
    profile_id: str,
    schedule_id: str,
) -> HTMLResponse:
    state: AppState = request.app.state.jop
    assert state.schedule_store is not None
    try:
        await state.schedule_store.toggle_pause(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found.") from exc
    entries = state.schedule_store.list_for_profile(profile_id)
    return TEMPLATES.TemplateResponse(
        request,
        "partials/schedule_panel_list.html",
        {"entries": entries, "profile_id": profile_id},
    )


@app.delete("/profiles/{profile_id}/schedules/{schedule_id}", response_class=HTMLResponse)
async def delete_schedule(
    request: Request,
    profile_id: str,
    schedule_id: str,
) -> HTMLResponse:
    state: AppState = request.app.state.jop
    assert state.schedule_store is not None
    await state.schedule_store.delete(schedule_id)
    entries = state.schedule_store.list_for_profile(profile_id)
    return TEMPLATES.TemplateResponse(
        request,
        "partials/schedule_panel_list.html",
        {"entries": entries, "profile_id": profile_id},
    )


@app.get("/profiles/{profile_id}/dashboard", response_class=HTMLResponse)
async def dashboard_view(request: Request, profile_id: str) -> HTMLResponse:
    state: AppState = request.app.state.jop
    state.config = load_config(state.config_path)
    profile = _active_profile(state, profile_id)
    dash = state.dashboard.get(profile_id)
    if dash is None:
        dash = state.dashboard.placeholder(profile_id)
        state.dashboard.schedule_refresh(
            profile,
            state.config,
            data_dir=state.data_dir,
        )
    return TEMPLATES.TemplateResponse(
        request,
        "partials/dashboard.html",
        {"state": dash, "profile_id": profile_id},
    )


@app.post("/profiles/{profile_id}/dashboard/refresh", response_class=HTMLResponse)
async def dashboard_refresh(request: Request, profile_id: str) -> HTMLResponse:
    state: AppState = request.app.state.jop
    state.config = load_config(state.config_path)
    profile = _active_profile(state, profile_id)
    state.dashboard.schedule_refresh(
        profile,
        state.config,
        data_dir=state.data_dir,
    )
    dash = state.dashboard.get(profile_id) or state.dashboard.placeholder(profile_id)
    return TEMPLATES.TemplateResponse(
        request,
        "partials/dashboard.html",
        {"state": dash, "profile_id": profile_id},
    )


def run() -> None:
    import uvicorn

    host = os.getenv("JOP_HOST", "127.0.0.1")
    port = int(os.getenv("JOP_PORT", "8765"))
    uvicorn.run(
        "jump_ops_panel.main:app",
        host=host,
        port=port,
        reload=os.getenv("JOP_RELOAD", "") == "1",
    )


if __name__ == "__main__":
    run()
