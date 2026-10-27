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
from .jms_runner import RunResult, deploy_init_scripts, run_operation
from .models import AppConfig
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
    result = await deploy_init_scripts(
        profile,
        state.config,
        data_dir=state.data_dir,
        project_root=state.root,
    )
    state.last_results[profile_id] = result
    return TEMPLATES.TemplateResponse(
        request,
        "partials/run_result.html",
        {"last_result": result},
    )


@app.post("/profiles/{profile_id}/ops/{op_id}", response_class=HTMLResponse)
async def run_op(request: Request, profile_id: str, op_id: str) -> HTMLResponse:
    state: AppState = request.app.state.jop
    state.config = load_config(state.config_path)
    profile = _active_profile(state, profile_id)
    operation = next((op for op in profile.operations if op.id == op_id), None)
    if operation is None:
        raise HTTPException(status_code=404, detail="Operation not found.")
    result = await run_operation(
        profile,
        state.config,
        operation,
        data_dir=state.data_dir,
    )
    state.last_results[profile_id] = result
    return TEMPLATES.TemplateResponse(
        request,
        "partials/run_result.html",
        {"last_result": result},
    )


@app.get("/profiles/{profile_id}/dashboard", response_class=HTMLResponse)
async def dashboard_view(request: Request, profile_id: str) -> HTMLResponse:
    state: AppState = request.app.state.jop
    dash = state.dashboard.get(profile_id)
    if dash is None:
        profile = _active_profile(state, profile_id)
        state.config = load_config(state.config_path)
        dash = await state.dashboard.refresh_profile(
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
    dash = await state.dashboard.refresh_profile(
        profile,
        state.config,
        data_dir=state.data_dir,
    )
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
