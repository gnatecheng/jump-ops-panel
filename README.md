# jump-ops-panel

内网 JumpServer 运维面板（htmx 快版）：多环境配置、远端脚本初始化、操作区执行、定时刷新展示。

- **Web**：无登录（仅内网使用）
- **JumpServer**：配置 `username` + `password_env`（或开发用 `password`）

## 依赖

先安装 fork 版 MCP 库，再安装本仓库：

```bash
pip install -e /path/to/mcp-jumpserver-gui-sucks
pip install -e /path/to/jump-ops-panel
```

## Docker 镜像

镜像**只打包本机 sibling 目录**里的 `mcp-jumpserver-gui-sucks` fork（不会从 PyPI 拉 upstream 包）：

```bash
cd ~/work/src/github.com/gnatecheng
./jump-ops-panel/deploy/build-image.sh dev-chengyt-$(date +%Y%m%d%H%M%S)
docker push "$(cat jump-ops-panel/deploy/.last-image)"
```

构建信息写入容器内 `/etc/jop-build-info`。

## 配置

```bash
cp config/profiles.example.yaml config/profiles.yaml
export JOP_PASSWORD_HICK='your-jumpserver-password'
# 可选：export JOP_CONFIG=/path/to/profiles.yaml
```

## 运行

```bash
jump-ops-panel
# 或 JOP_HOST=0.0.0.0 JOP_PORT=8765 jump-ops-panel
```

浏览器打开 `http://127.0.0.1:8765/`。

## 流程

1. **初始化：上传脚本** — 将 `assets/scripts/*.sh` 写入远端 `script_remote_dir`
2. **操作按钮** — 在目标机执行配置中的 command / script
3. **定时展示区** — 按 `dashboard.panels` 自动 htmx 刷新

## 环境变量

| 变量 | 说明 |
|------|------|
| `JOP_CONFIG` | 配置文件路径，默认 `config/profiles.yaml` 或 example |
| `JOP_DATA_DIR` | 状态目录（JumpServer auth-state），默认 `./data` |
| `JOP_HOST` / `JOP_PORT` | 监听地址 |
| `JOP_*_PASSWORD` | 各 profile 的 `password_env` |
