# BiliArchive-Pro 开发维护指南

## 配置边界

- `config.yaml` 是受 Git 管理的默认模板，不应写入个人收藏夹、绝对路径或测试开关。
- 本机配置写入 `config.local.yaml`。程序启动时会递归合并该文件，列表和标量以本地值为准。
- `config.local.yaml`、`.env`、`data/`、`downloads/`、`logs/` 和 `bin/` 不得提交或加入发布包。
- 根目录的 `本地任务计划与执行表.md` 仅用于本地执行记录，禁止使用 `git add -f` 强制提交。
- 组件策略只允许 `auto`、`notify`、`off`；自动更新的可执行文件必须先通过官方 SHA256 校验，下载流程不得自行安装组件。
- `sync_collections` 的每个条目必须同时提供合集 `id` 和所属 UP 主 UID `mid`。
- WebUI 只能写入 `app/webui/service.py` 中声明的公开白名单；不得暴露或修改下载路径、数据库路径、Cookie 路径和代理地址。
- WebUI 设置写入本地覆盖后不会热重载正在运行的扫描器，必须明确提示重启核心进程生效。

## 核心逻辑

1. **资产保护**：本地已有视频但源端失效时，目录会增加 `[源端已删]` 标记，不执行同步删除。
2. **墓碑机制**：收藏夹仍返回失效条目且本地无存档时，创建只包含元数据的墓碑目录。
3. **媒体库元数据**：媒体与 `.nfo` 使用同一文件名前缀；Plex 多 P 生成 `tvshow.nfo`、分集 NFO 和标准封面。
4. **周期巡检**：扫描全部目标收藏夹；Active 视频按 `p_count` 和稳定分 P 标识验证非空媒体文件，完整时更新 `last_check`，缺集时进入续跑。
5. **下载恢复**：超时时终止 yt-dlp/FFmpeg 进程树，失败时不写入成功记录；保留非空 `.part` 供下轮续传，只清理空残留。
6. **数据库迁移**：启动时在事务中补齐旧表字段并修复历史空键，查询不得依赖列顺序。
7. **多P完成语义**：每个分 P 由独立 `?p=` URL 和 `--no-playlist` 下载；全部分 P 与关键 NFO 成功后才写数据库完成状态。
8. **弹幕隔离**：下载器只转换当前文件名前缀下的 `.danmaku.xml`；转换器按类型分区和分配轨道，容量不足时丢弃冲突项。
9. **完成状态**：视频、专栏或墓碑的关键 NFO 以及视频标准封面写入失败时不得写入数据库完成状态，下轮扫描会继续处理。
10. **路径预算**：收藏夹与资产目录使用稳定截断，媒体文件名根据完整输出路径动态收缩；预算不足以保留唯一标识时明确拒绝。
11. **WebUI 解耦**：核心进程只原子发布 `runtime.json`；WebAPI 使用 SQLite `mode=ro` 短连接读取资产，不创建、迁移或写入数据库。
12. **WebUI 安全**：默认只监听 loopback；非 loopback 必须启用 Bearer Token。配置更新需要 revision，并保留本地覆盖文件中的非公开字段。

## 媒体库布局

- 单 P：媒体、NFO、普通字幕和弹幕侧车使用同一前缀，目录内额外生成 `poster.jpg`。
- 多 P 且 `plex_mode=true`：根目录保存 `tvshow.nfo`、`poster.jpg`，媒体写入 `Season 01/S01E## - 标题 [BV-P#]`。
- 多 P 且 `plex_mode=false`：媒体平铺为 `P## - 标题 [BV-P#]`，每个分 P 使用独立 movie NFO。
- 现有归档不自动迁移；布局变化只应用于新下载或用户明确触发的重新下载。

## 目录职责

- `app/core/`：下载、解析、元数据、路径、数据库和敏感文件写入工具。
- `app/scheduler/`：收藏夹扫描和组件环境检查。
- `app/webui/`：只读资产服务、配置白名单与 FastAPI 应用工厂。
- `webui/`：React/Vite 管理面板源码；`dist/` 和 `node_modules/` 只在本地生成，不提交。
- `web.py`：生产 WebUI 启动入口；默认地址为 `127.0.0.1:8000`。
- `tests/`：不访问真实 Bilibili 账号的单元与边界测试。
- `.github/workflows/ci.yml`：Windows/Linux 测试、编译检查和 Docker 构建验证。

## 本地验证

Windows PowerShell：

```powershell
.\venv\Scripts\python.exe -m pytest tests -q
.\venv\Scripts\python.exe -m compileall -q main.py login.py web.py app
Set-Location webui
npm.cmd ci
npm.cmd run lint
npm.cmd run build
```

Linux、macOS 或 WSL：

```bash
python -m pytest tests -q
python -m compileall -q main.py login.py web.py app
cd webui
npm ci
npm run lint
npm run build
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

1. 将 `app/__init__.py`、`webui/package.json`、Dockerfile 镜像标签、README 徽章与最新改进、`CHANGELOG.md` 更新为同一版本号。
2. 确认测试、编译检查和 Docker 构建全部通过。
3. 使用 `git status --short` 确认没有凭据、数据库、本地配置或任务记录进入变更。
4. 提交并标记版本后，只用 Git 受跟踪内容生成 ZIP：

```bash
git archive --format=zip --prefix=BiliArchive-Pro-vX.Y.Z/ --output BiliArchive-Pro-vX.Y.Z.zip vX.Y.Z
```

5. 审计 ZIP 文件列表，确认不包含 `config.local.yaml`、`data/`、`downloads/`、`bin/`、`venv/` 或本地任务记录。
6. 计算 SHA256，使用 `CHANGELOG.md` 中对应版本内容作为 Release 说明，并上传 ZIP 与校验文件。
