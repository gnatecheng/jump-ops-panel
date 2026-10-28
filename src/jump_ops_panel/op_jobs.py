from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from .exec_command import build_remote_command, exec_timeout_for_target, format_exec_label
from .jms_runner import RunResult, run_manual_remote, run_operation
from .models import AppConfig, OperationConfig, ProfileConfig

JobKind = Literal["operation", "exec"]
JobStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class OpJob:
    id: str
    profile_id: str
    kind: JobKind
    status: JobStatus = "pending"
    label: str = ""
    target: str = ""
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

    def start_exec(
        self,
        profile: ProfileConfig,
        config: AppConfig,
        *,
        target: str,
        args_line: str,
        data_dir,
        manual_exec_cache,
    ) -> OpJob:
        job_id = uuid.uuid4().hex[:12]
        label = format_exec_label(target=target, args_line=args_line)
        job = OpJob(
            id=job_id,
            profile_id=profile.id,
            kind="exec",
            label=label,
            target=target.strip(),
        )
        self._jobs[job_id] = job
        self._tasks[job_id] = asyncio.create_task(
            self._run_exec(
                job,
                profile,
                config,
                target=target,
                args_line=args_line,
                data_dir=data_dir,
                manual_exec_cache=manual_exec_cache,
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
            )
            job.status = "done"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = datetime.now(tz=UTC)

    async def _run_exec(
        self,
        job: OpJob,
        profile: ProfileConfig,
        config: AppConfig,
        *,
        target: str,
        args_line: str,
        data_dir,
        manual_exec_cache,
    ) -> None:
        job.status = "running"
        try:
            timeout_seconds = exec_timeout_for_target(config, target)
            remote_command = build_remote_command(
                config,
                profile,
                target=target,
                args_line=args_line,
                timeout_seconds=timeout_seconds,
            )
            job.result = await run_manual_remote(
                profile,
                config,
                remote_command,
                data_dir=data_dir,
                timeout_seconds=timeout_seconds,
                label=job.label,
                target=target,
                cache=manual_exec_cache,
            )
            job.status = "done"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = datetime.now(tz=UTC)
