from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from .jms_runner import RunResult, deploy_init_scripts, run_operation
from .models import AppConfig, OperationConfig, ProfileConfig

JobKind = Literal["operation", "init"]
JobStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class OpJob:
    id: str
    profile_id: str
    kind: JobKind
    status: JobStatus = "pending"
    label: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    finished_at: datetime | None = None
    result: RunResult | None = None
    error: str = ""


class OpJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, OpJob] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def get(self, job_id: str) -> OpJob | None:
        return self._jobs.get(job_id)

    def start_operation(
        self,
        profile: ProfileConfig,
        config: AppConfig,
        operation: OperationConfig,
        *,
        data_dir,
    ) -> OpJob:
        job_id = uuid.uuid4().hex[:12]
        job = OpJob(
            id=job_id,
            profile_id=profile.id,
            kind="operation",
            label=operation.label,
        )
        self._jobs[job_id] = job
        self._tasks[job_id] = asyncio.create_task(
            self._run_operation(job, profile, config, operation, data_dir=data_dir)
        )
        return job

    def start_init(
        self,
        profile: ProfileConfig,
        config: AppConfig,
        *,
        data_dir,
        project_root,
    ) -> OpJob:
        job_id = uuid.uuid4().hex[:12]
        job = OpJob(
            id=job_id,
            profile_id=profile.id,
            kind="init",
            label="初始化脚本",
        )
        self._jobs[job_id] = job
        self._tasks[job_id] = asyncio.create_task(
            self._run_init(
                job,
                profile,
                config,
                data_dir=data_dir,
                project_root=project_root,
            )
        )
        return job

    async def _run_operation(
        self,
        job: OpJob,
        profile: ProfileConfig,
        config: AppConfig,
        operation: OperationConfig,
        *,
        data_dir,
    ) -> None:
        job.status = "running"
        try:
            job.result = await run_operation(
                profile,
                config,
                operation,
                data_dir=data_dir,
                user_priority=True,
            )
            job.status = "done"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = datetime.now(tz=UTC)

    async def _run_init(
        self,
        job: OpJob,
        profile: ProfileConfig,
        config: AppConfig,
        *,
        data_dir,
        project_root,
    ) -> None:
        job.status = "running"
        try:
            job.result = await deploy_init_scripts(
                profile,
                config,
                data_dir=data_dir,
                project_root=project_root,
                user_priority=True,
            )
            job.status = "done"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = datetime.now(tz=UTC)
