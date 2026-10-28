from __future__ import annotations

from pydantic import BaseModel, Field


class JumpServerConfig(BaseModel):
    base_url: str
    username: str
    password_env: str = ""
    password: str = Field(default="", repr=False)


class RunAsConfig(BaseModel):
    method: str = "none"
    user: str = ""


class TargetConfig(BaseModel):
    asset_ref: str
    account_ref: str = ""
    run_as: RunAsConfig = Field(default_factory=RunAsConfig)


class InitScript(BaseModel):
    local: str
    remote_name: str


class InitConfig(BaseModel):
    scripts: list[InitScript] = Field(default_factory=list)


class OperationInput(BaseModel):
    name: str
    label: str = ""
    required: bool = False


class OperationConfig(BaseModel):
    id: str
    label: str
    script: str | None = None
    command: str | None = None
    timeout_seconds: float = 60.0
    inputs: list[OperationInput] = Field(default_factory=list)


class DashboardPanel(BaseModel):
    id: str
    label: str
    script: str | None = None
    command: str | None = None


class DashboardConfig(BaseModel):
    refresh_interval_seconds: int = 60
    panels: list[DashboardPanel] = Field(default_factory=list)


class ProfileConfig(BaseModel):
    id: str
    label: str
    jumpserver: JumpServerConfig
    target: TargetConfig
    init: InitConfig = Field(default_factory=InitConfig)
    operations: list[OperationConfig] = Field(default_factory=list)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)


class DefaultsConfig(BaseModel):
    script_remote_dir: str = "/opt/jop/scripts"
    protocol: str = "ssh"
    connect_method: str = "web_cli"


class AppConfig(BaseModel):
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    profiles: list[ProfileConfig] = Field(default_factory=list)

    def get_profile(self, profile_id: str) -> ProfileConfig:
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        raise KeyError(profile_id)
