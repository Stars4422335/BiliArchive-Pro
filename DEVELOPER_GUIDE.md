# BiliArchive-Pro 开发维护指南

## 配置边界

- `config.yaml` 是受 Git 管理的默认模板，不应写入个人收藏夹、绝对路径或测试开关。
- 本机配置写入 `config.local.yaml`。程序启动时会递归合并该文件，列表和标量以本地值为准。
- `config.local.yaml`、`.env`、`data/`、`downloads/`、`logs/` 和 `bin/` 不得提交或加入发布包。
- 根目录的 `本地任务计划与执行表.md` 仅用于本地执行记录，禁止使用 `git add -f` 强制提交。
- 组件策略只允许 `auto`、`notify`、`off`；自动更新的可执行文件必须先通过官方 SHA256 校验，下载流程不得自行安装组件。

## 核心逻辑

1. **资产保护**：本地已有视频但源端失效时，目录会增加 `[源端已删]` 标记，不执行同步删除。
2. **墓碑机制**：收藏夹仍返回失效条目且本地无存档时，创建只包含元数据的墓碑目录。
3. **媒体库元数据**：视频与专栏归档后生成 `.nfo` 文件，供 Plex、Jellyfin 或 Emby 识别。
4. **周期巡检**：扫描全部目标收藏夹，利用数据库跳过已归档资源并更新 `last_check`。

## 目录职责

- `app/core/`：下载、解析、元数据、路径、数据库和敏感文件写入工具。
- `app/scheduler/`：收藏夹扫描和组件环境检查。
- `tests/`：不访问真实 Bilibili 账号的单元与边界测试。
- `.github/workflows/ci.yml`：Windows/Linux 测试、编译检查和 Docker 构建验证。

## 本地验证

Windows PowerShell：

```powershell
.\venv\Scripts\python.exe -m pytest tests -q
.\venv\Scripts\python.exe -m compileall -q main.py login.py app
```

Linux、macOS 或 WSL：

```bash
python -m pytest tests -q
python -m compileall -q main.py login.py app
```

涉及 Dockerfile 或依赖变更时，还必须执行：

```bash
docker build -t biliarchive-pro:local .
```

Dockerfile 默认使用 Debian 官方 HTTPS 源。网络环境需要镜像时，只能传入可信 HTTPS 根地址：

```bash
docker build --build-arg DEBIAN_MIRROR=https://mirrors.aliyun.com -t biliarchive-pro:local .
```

## 发布流程

1. 将 `app/__init__.py`、Dockerfile 镜像标签、README 徽章与最新改进、`CHANGELOG.md` 更新为同一版本号。
2. 确认测试、编译检查和 Docker 构建全部通过。
3. 使用 `git status --short` 确认没有凭据、数据库、本地配置或任务记录进入变更。
4. 提交并标记版本后，只用 Git 受跟踪内容生成 ZIP：

```bash
git archive --format=zip --prefix=BiliArchive-Pro-vX.Y.Z/ --output BiliArchive-Pro-vX.Y.Z.zip vX.Y.Z
```

5. 审计 ZIP 文件列表，确认不包含 `config.local.yaml`、`data/`、`downloads/`、`bin/`、`venv/` 或本地任务记录。
6. 计算 SHA256，使用 `CHANGELOG.md` 中对应版本内容作为 Release 说明，并上传 ZIP 与校验文件。
