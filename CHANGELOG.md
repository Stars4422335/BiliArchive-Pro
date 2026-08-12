# BiliArchive-Pro 变更记录

本文件记录正式发布版本的用户可见变更。版本号遵循语义化版本格式。

## [Unreleased]

## [1.3.0] - 2026-08-12

### WebUI 管理面板

- 新增 React/Vite 管理面板，包含扫描概览、资产表和设置页，支持真实 `poster.jpg`、服务端搜索、状态/类型筛选、分页和移动端布局。
- 核心守护进程原子发布 `runtime.json`；WebAPI 独立读取运行状态，WebUI 与扫描/下载生命周期解耦。
- 资产 API 使用 SQLite `mode=ro` 和短连接查询，不创建、迁移或修改数据库；本阶段不提供远程删除资产或直接控制下载。
- 设置 API 仅接受公开白名单字段，使用 revision 检测并发修改，原子更新本地覆盖文件且保留其中已有的私有字段。

### 安全与部署

- 新增 `web.py` FastAPI/Uvicorn 启动入口，默认监听 `127.0.0.1`；监听非 loopback 地址时必须设置 `BILIARCHIVE_WEB_TOKEN`。
- Token 仅通过 Authorization Bearer 头发送并保存在浏览器 `sessionStorage`；封面也通过鉴权 fetch 加载，不把 Token 写入 URL。
- Dockerfile 增加 Node 构建阶段，仅把前端 `dist` 复制到最终 Python 镜像；Compose 通过可选 `webui` profile 启动独立 Web 服务。
- Docker 中公共配置只读挂载，本地覆盖写入共享的 `/app/data/config.local.yaml`；WebUI 保存后需重启核心服务生效。

### 媒体库输出

- `plex_mode` 现在真实控制多 P 布局：开启时生成 `Season 01/S01E##`、`tvshow.nfo` 和分集 NFO，关闭时使用不会互相覆盖的平铺 `P##` 文件。
- 多 P 改为逐页下载，每页强制 `--no-playlist`；只有全部分 P 与关键 NFO 成功后才记录完成。
- NFO 与媒体文件使用同一前缀，并从 yt-dlp 缩略图整理 `poster.jpg` 与分集 `-thumb.jpg`。
- 同时请求普通字幕和自动字幕，只转换当前任务生成的 `.danmaku.xml`，不再扫描同目录的其他 XML。
- 弹幕 ASS 增加滚动、反向、顶部和底部定位、文本转义及轨道容量控制；非法时间或单个转换异常不会中断已完成的媒体下载。
- Active 记录会按 `p_count` 和稳定分 P 标识复核非空媒体文件，缺集时自动续跑；NFO 或标准封面写入失败不再写入数据库完成状态。
- 收藏夹、资产目录和媒体文件名增加危险组件规范化及完整路径预算；根路径过长时会明确拒绝，避免截断唯一标识后发生碰撞。

### 升级说明

- 新布局只影响新下载或重新下载的资产，不会自动移动现有媒体目录。

## [1.2.0] - 2026-08-11

### 可靠性

- 同步列表请求增加可配置的有限重试、指数退避和 HTTP 超时。
- 真实空列表与读取失败使用不同语义，避免将超时、鉴权或响应结构错误当作扫描完成。
- 单个收藏夹、稍后再看或合集读取失败时，后续来源继续扫描，并明确标记本轮不完整。
- `yt-dlp` 下载增加可配置超时；超时后终止 yt-dlp/FFmpeg 进程树、返回失败并清理临时 Cookie。
- 显式启用 `.part` 续传，保留非空部分文件供下轮恢复，并清理同一任务的空残留。
- 缺少 `bvid` 的失效视频使用 `av{aid/id}` 稳定键，并通过 AV/BV 转换关联既有存档，避免空主键、共享 `unknown` 目录和孤本保护失效。
- SQLite 启动时自动补齐旧表字段、修复历史空键，并使用事务写入和显式列查询。
- 守护循环在正常退出、提前返回、异常或取消时统一关闭数据库连接。

### 合集同步

- 合集配置新增所属 UP 主 UID `mid`，Series 与 Season API 使用同一真实 UID。
- 缺少或无效的 `id` / `mid` 会明确标记当前合集配置失败，不再发送硬编码 `mid=0/1` 请求。

### 升级说明

- `system.download_timeout_seconds` 默认 `7200` 秒，设置为 `0` 可关闭单任务超时。
- 已配置 `sync_collections` 的用户需要为每个条目补充 `mid`；该值来自合集 URL 中 `space.bilibili.com/<mid>` 的数字部分。
- 旧数据库会在首次启动时原地迁移；迁移保留现有有效记录和媒体文件，不执行同步删除。

## [1.1.3] - 2026-08-06

### 安全

- 项目许可证声明统一为 GNU General Public License v3.0。
- 登录凭据改为原子写入，并尽力限制本地文件权限。
- 每次下载使用独立的临时 Cookie 文件，只清理由当前任务创建的文件，并拒绝通过 HTTP 发送凭据。
- `yt-dlp` 自动更新仅在显式启用时执行，下载后必须通过 GitHub 官方 SHA256 校验。

### 可靠性

- 新增 `config.local.yaml` 递归覆盖机制，使本机测试配置与公共模板分离。
- 改进 `yt-dlp` 和 FFmpeg 路径发现，兼容 Windows 可执行文件后缀。
- 组件下载或校验失败时保留现有文件，避免以不完整文件替换可用版本。
- 增强下载临时文件的并发隔离和异常清理。

### 发布工程

- Docker 构建改为运行文件白名单复制，并排除凭据、数据库、下载内容、本地环境和任务记录。
- Docker 镜像元数据和应用运行时版本统一为 `1.1.3`。
- 新增 Windows/Linux CI，覆盖 Python 3.10 与 3.12 的测试、编译检查及 Docker 构建。
- 正式 Release 提供受跟踪源码生成的 ZIP 及对应 SHA256 校验文件。

### 升级说明

- `config.yaml` 的现有部署方式保持兼容；个人测试值建议迁移到被忽略的 `config.local.yaml`。
- Docker Compose 的数据、下载目录、组件目录和配置文件挂载方式不变。
- 如果 `data/cookie.json` 曾被上传、打包或共享，应重新登录，使旧凭据失效。
- 本版本不提供 EXE 或 App；跨平台独立可执行文件仍属于后续阶段。

[Unreleased]: https://github.com/Stars4422335/BiliArchive-Pro/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.3.0
[1.2.0]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.2.0
[1.1.3]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.1.3
