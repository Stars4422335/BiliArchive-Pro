# BiliArchive-Pro 变更记录

本文件记录正式发布版本的用户可见变更。版本号遵循语义化版本格式。

## [Unreleased]

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

[Unreleased]: https://github.com/Stars4422335/BiliArchive-Pro/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.2.0
[1.1.3]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.1.3
