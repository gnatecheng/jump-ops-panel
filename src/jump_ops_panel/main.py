from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .config_loader import list_profile_summaries, load_config, project_root
from .dashboard_store import DashboardStore
from .jms_runner import RunResult
from .models import AppConfig
from .op_jobs import OpJobStore
from .scheduler import start_dashboard_scheduler

LOGGER = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@dataclass
class AppState:
    config_path: Path
    data_dir: Path
    root: Path
    config: AppConfig
    dashboard: DashboardStore = field(default_factory=DashboardStore)
    op_jobs: OpJobStore = field(default_factory=OpJobStore)
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_path = _config_path()
    data_dir = _data_dir()
    config = load_config(config_path)
    app.state.jop = AppState(
        config_path=config_path,
        data_dir=data_dir,
        root=project_root(),
        config=config,
    )
    scheduler = start_dashboard_scheduler(
        config_path=config_path,
        data_dir=data_dir,
        store=app.state.jop.dashboard,
    )
    LOGGER.info("Jump Ops Panel started; config=%s", config_path)
    yield
    scheduler.shutdown(wait=False)


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
        },
    )


@app.post("/profiles/{profile_id}/init", response_class=HTMLResponse)
async def init_scripts(request: Request, profile_id: str) -> HTMLResponse:
    state: AppState = request.app.state.jop
    state.config = load_config(state.config_path)
    profile = _active_profile(state, profile_id)
    state.dashboard.cancel_for_user(profile_id)
    job = state.op_jobs.start_init(
        profile,
        state.config,
        data_dir=state.data_dir,
        project_root=state.root,
    )
    return TEMPLATES.TemplateResponse(
        request,
        "partials/op_job_poll.html",
        {"job": job, "profile_id": profile_id},
    )


@app.post("/profiles/{profile_id}/ops/{op_id}", response_class=HTMLResponse)
async def run_op(request: Request, profile_id: str, op_id: str) -> HTMLResponse:
    state: AppState = request.app.state.jop
    state.config = load_config(state.config_path)
    profile = _active_profile(state, profile_id)
    operation = next((op for op in profile.operations if op.id == op_id), None)
    if operation is None:
        raise HTTPException(status_code=404, detail="Operation not found.")
    state.dashboard.cancel_for_user(profile_id)
    job = state.op_jobs.start_operation(
        profile,
        state.config,
        operation,
        data_dir=state.data_dir,
    )
    return TEMPLATES.TemplateResponse(
        request,
        "partials/op_job_poll.html",
        {"job": job, "profile_id": profile_id},
    )


@app.get("/profiles/{profile_id}/ops/jobs/{job_id}", response_class=HTMLResponse)
async def op_job_status(
    request: Request,
    profile_id: str,
    job_id: str,
) -> HTMLResponse:
    state: AppState = request.app.state.jop
    job = state.op_jobs.get(job_id)
    if job is None or job.profile_id != profile_id:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status in ("pending", "running"):
        return TEMPLATES.TemplateResponse(
            request,
            "partials/op_job_poll.html",
            {"job": job, "profile_id": profile_id},
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
        "partials/run_result_wrap.html",
        {"last_result": result},
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
