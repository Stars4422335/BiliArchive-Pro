# 📺 BiliArchive-Pro

> **专业的 Bilibili 个人数字资产全量备份系统**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Release: v1.3.0](https://img.shields.io/badge/release-v1.3.0-green.svg)](https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.3.0)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

**BiliArchive-Pro** 旨在为 B 站深度用户提供一套稳定、安全且符合影视库管理规范（如 Plex、Jellyfin、Emby）的本地自动化备份方案。它不仅是一个支持最高 4K/HDR 画质的下载器，更是一个智能的**个人数字图书馆管理员**。

无论是防备 UP 主删稿、视频失效，还是希望将 B 站的优质视频、专栏图文永久纳入自己的私人 NAS 影视库，BiliArchive-Pro 都能为你提供“开箱即用”且“一劳永逸”的守护。

---

## ✨ 核心特性

- 🚀 **全能媒体抓取**：不仅仅是视频！支持最高画质视频下载（含多 P 分集），同时**独家支持专栏图文**抓取（自动转为 Markdown 并将图片本地化保存）。
- 🎬 **媒体库侧车输出 (Plex/Jellyfin/Emby)**：媒体与 `.nfo` 一一同名，整理标准封面；多 P 可按 `Season 01/S01E##` 组织，并将 UP 主写入演职员信息。
- 🛡️ **首创数字资产保护逻辑**：
  - **墓碑机制 (Tombstone)**：扫描到收藏夹中已被 B 站删除的失效视频时，在本地生成 NFO 占位符，记录遗失的元数据。
  - **孤本保护**：如果本地已下载好的视频后来被源端删除，本地资产会自动打标锁定（如添加 `[源端已删]` 前缀），绝不发生误覆盖或同步删除。
- ⚡ **周期巡检与防风控**：按配置周期全量巡检收藏夹，通过本地数据库跳过已归档资源并更新存活时间；翻页和下载后加入休眠，降低请求频率。
- 💬 **弹幕智能渲染**：把当前媒体的 B 站 XML 弹幕转换为 `.ass`，分别调度滚动、顶部和底部轨道，过载时丢弃冲突项以避免文字重叠。
- 🔄 **可选组件检查**：可按 `auto` / `notify` / `off` 策略检查 `yt-dlp`；自动更新前必须通过 GitHub 官方 SHA256 校验，同时验证系统或配置路径中的 FFmpeg 是否可用。

---

## 🛠️ 安装与部署

BiliArchive-Pro 支持在 Windows、macOS、Linux (含 WSL) 以及各类 NAS 平台上运行。你可以选择**本地原生运行**或使用 **Docker 容器化部署**。

### 方式一：本地 Python 原生运行 (推荐开发/测试使用)

**1. 环境准备**
确保系统已安装 **Python 3.10+**。`yt-dlp` 会随 `requirements.txt` 安装；程序优先使用配置路径中的 `yt-dlp`（Windows 同时识别 `.exe`），再查找系统 PATH，仍找不到时只给出手动安装提示。音视频合并需要 [**FFmpeg**](https://ffmpeg.org/download.html)：Linux 用户可 `sudo apt install ffmpeg`，Windows/Mac 用户可将 `ffmpeg.exe` / `ffmpeg` 放入本项目的 `bin/` 目录。

```bash
# 1. 克隆代码
git clone https://github.com/Stars4422335/BiliArchive-Pro.git
cd BiliArchive-Pro

# 2. 创建并激活虚拟环境 (可选但推荐)
python -m venv venv
source venv/bin/activate  # Windows 用户使用 venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt
```

### 方式二：Docker / Docker Compose 部署 (推荐 NAS/服务器使用)

Docker 部署内置了 FFmpeg 等所有运行环境，且彻底隔离，是最稳定省心的长期挂机方式。

**1. 克隆项目并初始化配置**
```bash
git clone https://github.com/Stars4422335/BiliArchive-Pro.git
cd BiliArchive-Pro
```

**2. 在宿主机上完成扫码登录 (必须步骤)**
由于 Docker 内部不方便扫码，我们需要先在本地环境或宿主机上生成凭证：
```bash
# 安装轻量请求库用于登录
pip install httpx qrcode bilibili-api-python
python login.py
```
*请使用 Bilibili 手机 App 扫描控制台出现的二维码。登录成功后，会在 `data/` 目录下生成 `cookie.json`。*

**3. 一键启动容器**
```bash
docker-compose up -d
```
启动后，容器会自动接管所有后台下载任务。你可以通过 `docker-compose logs -f` 查看实时运行日志。

> **持久化说明**：Docker 会将 `data/` (数据库与凭证)、`downloads/` (视频与专栏库)、`bin/` (组件工具) 以及 `config.yaml` 映射到宿主机的项目目录下，便于迁移备份。

---

## ⚙️ 配置指南 (`config.yaml`)

项目根目录下的 `config.yaml` 是整个系统的默认配置模板。首次运行前，建议根据个人需求进行微调：

```yaml
system:
  download_path: "./downloads"       # 媒体库保存位置
  plex_mode: true                    # 多P使用 Season 01/S01E；false 时平铺为 P01/P02
  check_update_on_start: false       # 是否在启动时执行组件检查策略
  max_downloads_per_run: 0           # 0代表无限制。若只想测试，可改为 5
  download_timeout_seconds: 7200     # 单个 yt-dlp 任务超时；0 表示不限制

network:
  sync_retry_attempts: 3            # 同步列表读取最大尝试次数
  sync_retry_backoff_seconds: 2     # 失败后指数退避的初始秒数
  request_timeout_seconds: 30       # 直接 HTTP 同步请求超时
  github_proxy_url: "https://mirror.ghproxy.com/" # 解决国内服务器下载 yt-dlp 失败的问题

components:
  yt-dlp:
    strategy: "auto"                # 校验后更新；notify 仅提醒；off 关闭

sync_collections:
  # mid 是合集所属 UP 主的 UID，id 是合集或系列 ID
  # - id: 67890
  #   mid: 12345
  #   name: "某个UP主的精华合集"

favorites:
  # 留空此项将【自动拉取并备份您账号下的所有收藏夹】！
  # 如果只想备份特定收藏夹，请取消下方注释并填入：
  # - id: 12345678
  #   name: "指定收藏夹名称"
```

个人测试配置请写入根目录的 `config.local.yaml`。程序会在读取 `config.yaml` 后递归合并本地配置，其中列表和普通值以本地文件为准。该文件默认被 Git 和 Docker 构建忽略，适合保存本机收藏夹、开关和路径设置。

同步列表请求失败时会按 `sync_retry_attempts` 进行有限重试。重试耗尽后，当前收藏夹、稍后再看或合集会被标记为本轮失败，其他来源仍会继续扫描，下一轮再重试失败来源。

单个下载超过 `download_timeout_seconds` 后会终止 yt-dlp/FFmpeg 进程树、返回失败并清理临时 Cookie。非空 `.part` 文件会保留并在下一轮通过 `yt-dlp --continue` 续传，空残留会自动清理。

媒体库输出规则：

- 单 P 视频在两种模式下都保持原目录结构，媒体、字幕、弹幕 ASS 和 NFO 使用同一文件名前缀，并在视频目录生成 `poster.jpg`。
- `plex_mode: true` 时，多 P 视频写入 `Season 01/`，按 `S01E01`、`S01E02` 命名；根目录生成 `tvshow.nfo` 和 `poster.jpg`，每集生成同名 NFO 与 `-thumb.jpg`。
- `plex_mode: false` 时，多 P 视频平铺在视频目录，按 `P01`、`P02` 命名，每个分 P 仍有独立 NFO 和封面，避免覆盖。
- 每个分 P 使用独立 URL 下载。只有全部分 P 与关键 NFO 都成功后才写入数据库完成状态；中途失败会在下一轮利用现有文件和 `.part` 继续。
- 已有 Active 记录会按数据库 `p_count` 和稳定分 P 标识复核非空媒体文件；缺集时自动续跑，完整时才跳过。
- 收藏夹目录和媒体文件名会按完整路径预算截断；若 `download_path` 过长到无法保留唯一标识，程序会明确报错，避免名称碰撞。
- 本设置只影响新下载或重新下载的资产，不会自动移动已经归档的旧目录。

> `config.local.yaml` 只用于本地覆盖，不应放入发布包。Docker 部署应通过挂载 `config.yaml` 或其他部署侧配置管理方式提供运行配置。

---

## 🚀 使用指南

### 1. 账号授权登录
无论是哪种部署方式，首次使用都必须获取 B 站授权：
```bash
python login.py
```
- 支持**二维码登录**（推荐，最稳定安全）和**手机号短信登录**。
- 登录凭证以明文 JSON 保存在 `./data/cookie.json`，程序采用原子写入并尽力限制文件权限，但不会进行加密。
- `data/` 已被 Git 和 Docker 构建忽略。请勿分享该文件；若凭据曾进入镜像、压缩包或公共位置，应立即重新登录使旧凭据失效。

### 2. 启动守护进程
获取凭证后，即可启动后台扫描与下载引擎：
```bash
python main.py --cli
```
系统会自动拉取所有的收藏夹并开始下载，本轮任务结束后会进入休眠状态（默认 21600 秒后再次扫描，可通过 `config.yaml` 的 `system.scan_interval_seconds` 调整），适合搭配 `tmux`、`screen` 或 `systemd` 长期挂机。

### 3. 测试与限制下载数量
如果你只是想测试一下环境是否跑通，可以使用 `--limit` 参数限制本次运行最大下载数（到达指定数量后程序会自动安全退出）：
```bash
python main.py --cli --limit 3
```

### 4. 开发测试
如果你要参与开发或验证改动，可以安装开发依赖并运行测试：
```bash
pip install -r requirements-dev.txt
python -m pytest tests
python -m compileall main.py login.py app
```

---

## 🧾 最新改进（v1.3.0）

完整版本说明见 [CHANGELOG.md](CHANGELOG.md)。

- 多 P 视频按独立页面下载；Plex 模式生成 `Season 01/S01E##`、`tvshow.nfo`、分集 NFO 和标准封面，平铺模式使用稳定 `P##` 命名。
- Active 记录按 `p_count` 与稳定分 P 标识复核，缺集自动续跑；关键 NFO 或标准封面失败时不写入数据库完成状态。
- 同时请求普通字幕和自动字幕，弹幕转换支持滚动、反向、顶部、底部及轨道防重叠，并隔离异常文件。
- 收藏夹、资产目录和媒体文件名增加危险组件规范化和完整路径预算，避免 Windows 保留名、路径逃逸及唯一标识碰撞。

### v1.2.0 改进

- 同步列表读取增加有限重试、指数退避、HTTP 超时和来源隔离，不再把读取失败误判为空列表。
- `yt-dlp` 下载增加可配置超时；超时后终止下载进程树、清理临时 Cookie，并保留可续传的非空 `.part` 文件。
- 失效视频缺少 `bvid` 时使用 `av{aid/id}` 稳定键，避免多个条目共用空数据库主键和 `unknown` 目录。
- SQLite 启动时自动补齐旧表字段、修复历史空键，并在退出、异常或取消时关闭连接。
- 合集同步要求配置所属 UP 主的 `mid`，两个合集 API 不再使用无效的硬编码 UID。

### v1.1.3 改进

- 项目许可证声明统一为 GPLv3。
- 新增 `config.local.yaml` 本地覆盖机制，个人测试配置不再污染受跟踪模板。
- Docker 改为运行文件白名单复制，并通过 `.dockerignore` 排除凭据、数据库、下载内容、本地环境和任务记录。
- 登录凭据使用原子写入；每次下载使用独立的 Secure 临时 Cookie，结束后按所有权清理，并拒绝通过 HTTP 发送凭据。
- `yt-dlp` 不再在下载流程中隐式安装；显式自动更新必须验证 GitHub 官方 SHA256，校验失败时保留现有文件。
- 增加 Windows/Linux 的 GitHub Actions 测试、编译检查和 Docker 构建检查。
- 精简尚未使用的 GUI、浏览器和调度依赖，降低安装与镜像体积。

### v1.1.2 及此前改进

- 新增“稍后再看”和 UP 主合集/列表同步入口，可通过 `system.sync_watch_later` 和 `sync_collections` 配置启用。
- 启动时可通过 `system.check_update_on_start` 控制是否检查 `yt-dlp` / `ffmpeg` 组件。
- 扫描间隔可通过 `system.scan_interval_seconds` 配置，便于 NAS 或服务器长期运行。
- 下载前会按 `system.min_disk_gb` 检查剩余磁盘空间，防止磁盘被视频下载占满。
- 下载时依次查找配置路径和系统 PATH，不会隐式下载可执行文件；组件自动更新只在启用启动检查且策略为 `auto` 时执行。
- `ffmpeg` 不存在时会提示按系统安装或配置本地路径，不会自动下载。
- 补齐运行依赖，并新增 pytest 基础测试覆盖核心路径、数据库、NFO 和运行配置。

---

## 📋 功能清单与开发状态 (TODO)

本项目正在持续迭代中。以下是当前的开发进度：

### 🟢 核心功能 (已实现)
- [x] **全自动引擎**：无头守护进程，自动拉取账号下所有收藏夹，并支持配置文件指定拉取。
- [x] **双重登录机制**：终端二维码扫码登录 + 手机号短信验证码登录。
- [x] **最高画质下载**：基于 `yt-dlp` 的 4K/HDR 视频与高质量音频自动抓取及合并。
- [x] **Plex/Jellyfin 元数据**：生成与媒体文件同名的 NFO 和标准封面；多 P 支持 `Season 01/S01E##` 剧集布局。
- [x] **专栏图文支持**：自动识别收藏夹中的专栏文章，抓取正文转为 `Markdown`，并将网络图片本地化下载保存。
- [x] **弹幕渲染器**：将当前媒体的 B 站 XML 弹幕转换为 `.ass`，支持滚动/反向/顶部/底部布局和轨道防重叠。
- [x] **资产保护机制**：独立实现的“墓碑机制（Tombstone）”与“孤本保护”，防止源端失效导致本地资产连带损失。
- [x] **周期全量巡检**：自动记忆已归档资产，扫描时跳过重复下载并更新 `last_check`，默认每 6 小时重新巡检。
- [x] **组件环境检查**：按策略检查 `yt-dlp`，自动更新前验证官方 SHA256；FFmpeg 只检查系统 PATH 或配置路径，不自动下载更新。
- [x] **Docker 容器化**：提供包含 FFmpeg 与 Python 运行环境的镜像及 `docker-compose.yml` 部署方案。
- [x] **智能路径管理**：跨平台安全的路径名非法字符过滤与防爆长路径自动截断机制。

### 🟡 扩展功能 (规划中/开发中)
- [ ] **全量同步关注UP主**：新增配置字段，支持全量同步账号中已关注UP主的全部视频与图文。
- [ ] **跨平台打包**：使用 PyInstaller 打包生成 Windows/Mac/Linux 独立可执行文件（免配 Python 环境）。
- [ ] **WebUI 管理面板**：提供现代化的可视化网页端，用于查看下载进度、管理数据库资产、修改配置。
- [ ] **播放列表同步**：支持同步“稍后再看”列表及历史观看记录。
- [ ] **AI 内容摘要**：接入大模型，在下载完成后自动分析视频/专栏内容，并在 NFO 中追加 AI 内容摘要。
- [ ] **弹幕词云图**：基于下载的弹幕文件，自动生成并保存弹幕词云图作为媒体库的海报/背景图。

---

## 🤝 参与贡献

欢迎任何形式的贡献！如果你有更好的想法，或者发现了 Bug，欢迎提交 Pull Request 或开 Issue 讨论。

## 📄 许可证

本项目采用 [GNU General Public License v3.0](LICENSE) 授权。分发修改版时必须继续使用 GPLv3 并提供对应源代码。

> **免责声明**：本项目仅供个人学习、技术研究及私有数字资产备份使用。请严格遵守 Bilibili 用户协议，尊重 UP 主版权，**严禁将抓取的内容用于任何商业用途或进行二次非法传播**。因使用不当造成的任何法律责任由使用者自行承担。
