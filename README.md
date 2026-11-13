# 📺 BiliArchive-Pro

> **带本地 WebUI 的 Bilibili 个人数字资产备份、同步与媒体库整理工具**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Release: v1.9.8](https://img.shields.io/badge/release-v1.9.8-green.svg)](https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.9.8)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

**简体中文** | [English](README.en.md)

**BiliArchive-Pro** 旨在为 B 站深度用户提供一套稳定、安全且符合影视库管理规范（如 Plex、Jellyfin、Emby）的本地自动化备份方案。它不仅是一个支持最高 4K/HDR 画质的下载器，更是一个智能的**个人数字图书馆管理员**。

无论是防备 UP 主删稿、视频失效，还是希望将 B 站的优质视频、专栏图文永久纳入自己的私人 NAS 影视库，BiliArchive-Pro 都能为你提供“开箱即用”且“一劳永逸”的守护。

---

## ✨ 核心特性

- 🚀 **全能媒体抓取**：不仅仅是视频！支持最高画质视频下载（含多 P 分集），同时**独家支持专栏图文**抓取（自动转为 Markdown 并将图片本地化保存）。
- 👥 **关注 UP 主全量同步**：`followings.mode` 一键全量同步账号已关注的全部 UP 主投稿，或用 `list` 模式按 UID 监控任意 UP 主；取关后本地已备份资产保留不动，失效投稿自动走墓碑/孤本保护。
- 🎬 **媒体库侧车输出 (Plex/Jellyfin/Emby)**：媒体与 `.nfo` 一一同名，整理标准封面；多 P 可按 `Season 01/S01E##` 组织，并将 UP 主写入演职员信息。
- 🛡️ **首创数字资产保护逻辑**：
  - **墓碑机制 (Tombstone)**：扫描到收藏夹中已被 B 站删除的失效视频时，在本地生成 NFO 占位符，记录遗失的元数据。
  - **孤本保护**：如果本地已下载好的视频后来被源端删除，本地资产会自动打标锁定（如添加 `[源端已删]` 前缀），绝不发生误覆盖或同步删除。
- ⚡ **周期巡检与防风控**：按配置周期全量巡检收藏夹，通过本地数据库跳过已归档资源并更新存活时间；翻页和下载后加入休眠，降低请求频率。
- 🖥️ **本地 WebUI 管理面板**：独立进程展示扫描状态、磁盘空间和真实资产封面，支持跨页搜索、筛选及白名单配置编辑；可下发运维指令（触发巡检 / 重下单个资产 / 提示重启）并查看执行回执。
- 💬 **弹幕智能渲染**：把当前媒体的 B 站 XML 弹幕转换为 `.ass`，分别调度滚动、顶部和底部轨道，过载时丢弃冲突项以避免文字重叠。可选基于同一份弹幕生成词云 SVG。
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

### 方式二：NAS Docker 离线包 (推荐极空间 / 飞牛等 NAS 使用)

从 [Releases](https://github.com/Stars4422335/BiliArchive-Pro/releases) 下载对应架构的 `BiliArchive-Pro-docker-<架构>.tar.gz`（amd64 对应 x86 NAS，arm64 对应 ARM NAS）与同名 `.sha256`，本地校验通过后解压。

**飞牛 fnOS**：全程图形界面——Docker → 本地镜像 → 从 NAS 文件添加（选 tar）→ Compose → 上传包内 `docker-compose.yml`。

**极空间 ZOS（实测流程，全程不需要 SSH）**：

1. 把镜像文件 `biliarchive-pro-<版本>-<架构>.tar` 上传到极空间个人空间（如 `我的文件/BiliArchive-Pro/`）。
2. 极空间客户端 → Docker → 镜像 → 导入本地镜像，选择该 tar（远程链路导入大镜像可能超时，在 NAS 所在局域网内操作最快）。
3. Compose → 创建项目，粘贴包内 `docker-compose.yml`，把其中的相对路径挂载改为个人空间绝对路径，例如：
   - `我的文件/BiliArchive-Pro/config` → `/app/data`
   - `我的文件/BiliArchive-Pro/Download` → `/app/downloads`
4. 面板容器启动后，在 Docker 应用列表点「打开」进入 WebUI；**首启密码在核心容器日志里**（自动生成，登录后强制修改）。

**账号登录（v1.9.2 起）**：打开 WebUI 的「账号」页，点击「生成登录二维码」，用 B 站手机 App 扫一扫即可完成登录——凭据自动写入 NAS 数据目录，核心引擎下一轮自动接管；页面同时常显当前登录状态（账号昵称 + UID）。命令行方式（`python login.py --qr`）仍然可用。

**WebUI 访问安全**：默认 `BILIARCHIVE_WEB_BIND=127.0.0.1`，仅限 NAS 本机访问；局域网访问把它改为 `0.0.0.0` 并**必须**同时设置 `BILIARCHIVE_WEB_TOKEN`（作为找回凭据的后门），否则面板容器拒绝启动。日常登录使用管理密码：首次启动自动生成初始密码并打印在日志中，登录后会强制改为 8-12 位含数字、大小写与符号的复杂密码。

### 方式三：Docker / Docker Compose 源码部署 (推荐服务器使用)

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

**3. 启动核心容器**
```bash
docker compose up -d biliarchive
```
启动后，容器会自动接管所有后台下载任务。你可以通过 `docker compose logs -f biliarchive` 查看实时运行日志。

**4. 启动 WebUI**

WebUI 是 compose 中的默认服务，随 `docker compose up -d` 一起启动。默认 `BILIARCHIVE_WEB_BIND=127.0.0.1`：端口只发布到宿主机本机，**免 token** 直接访问 `http://127.0.0.1:8000`。

若要从其他电脑访问，把 `.env` 中 `BILIARCHIVE_WEB_BIND` 改为 `0.0.0.0`，并设置 token（否则面板容器会拒绝启动）：

```bash
echo "BILIARCHIVE_WEB_BIND=0.0.0.0" >> .env
echo "BILIARCHIVE_WEB_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
docker compose up -d biliarchive-web
```

打开 `http://<主机IP>:8000` 并用管理密码登录（首启密码见日志）。安全规则只看实际暴露范围（`--public-bind`）：暴露到非 loopback 必须配 `BILIARCHIVE_WEB_TOKEN` 作为后门；优先使用 SSH 隧道或带 TLS 的反向代理，不要直接把未加密端口暴露到公网。

> **持久化说明**：Docker 会将 `data/`（数据库、凭证、运行状态和 `config.local.yaml`）、`downloads/`（视频与专栏库）、`bin/`（组件工具）映射到宿主机；`config.yaml` 只读挂载。WebUI 设置页保存后：标「即时生效」的字段通过命令通道热重载立即生效，标「需重启」的字段在核心进程重启后生效。

---

## ⚙️ 配置指南 (`config.yaml`)

项目根目录下的 `config.yaml` 是整个系统的默认配置模板。首次运行前，建议根据个人需求进行微调：

> **v1.9.x 起**：下表全部字段都可以在 **WebUI「设置」页**直接修改并保存（写入 `config.local.yaml`），无需手改本文件。每个字段旁标注了生效方式：【即时】保存后通过配置热重载立即生效；【重启】需重启核心进程。

```yaml
system:
  download_enabled: false            # 【即时】下载总开关（默认 false=暂停全部下载来源）。
                                     # 掉登录时下载门禁也会自动拦截，双重保证只入库最高清晰度
  download_path: "./downloads"       # 【重启】媒体库保存位置
  plex_mode: true                    # 【重启】多P使用 Season 01/S01E；false 时平铺为 P01/P02
  scan_interval_seconds: 21600       # 【即时】每轮扫描后的休眠秒数（默认 6 小时）
  max_downloads_per_run: 0           # 【即时】单轮最大下载数；0=无限制（测试时可设 5）
  download_timeout_seconds: 7200     # 【即时】单个 yt-dlp 任务超时；0 表示不限制
  sync_watch_later: false            # 【即时】自动备份"稍后再看"列表
  sync_watch_history: false          # 【即时】同步观看历史（仅元数据入库，不下载视频本体）
  max_history_days: 90               # 【即时】观看历史回溯窗口（天）；0=不限
  verify_integrity: "off"            # 【重启】完整性巡检档位：off / light（大小+文件头） / full（ffmpeg 解码）
  db_wal: false                      # 【重启】SQLite WAL：WebUI 读取不阻塞核心写入；启用失败自动退回
  check_update_on_start: false       # 【即时】启动时执行组件检查
  quality_audit_enabled: false       # 【即时】清晰度审计开关：巡检时对比本地与源端清晰度，
                                     # 低清清单在 WebUI「操作」页确认后清除并自动重下高清
  plex_mode: true                    # 多P使用 Season 01/S01E；false 时平铺为 P01/P02
  check_update_on_start: false       # 是否在启动时执行组件检查策略
  max_downloads_per_run: 0           # 0代表无限制。若只想测试，可改为 5
  download_timeout_seconds: 7200     # 单个 yt-dlp 任务超时；0 表示不限制
  sync_watch_later: false            # 是否自动备份“稍后再看”列表
  sync_watch_history: false          # 同步观看历史（仅记元数据，不下载视频本体）
  max_history_days: 90               # 观看历史回溯窗口（天）；0 表示不限，历史量大时慎用
  verify_integrity: "off"            # 完整性巡检档位：off / light / full（见下文说明）
  db_wal: false                      # SQLite WAL：WebUI 读取不再阻塞核心写入。
                                    # 需要库同目录可写；启用失败时自动退回默认模式

network:
  sync_retry_attempts: 3            # 【即时】同步列表读取最大尝试次数（1-10）
  sync_retry_backoff_seconds: 2     # 【即时】失败后指数退避的初始秒数（0-60）
  request_timeout_seconds: 30       # 【即时】直接 HTTP 同步请求超时（1-300）
  github_proxy_url: "https://mirror.ghproxy.com/" # 【重启】GitHub 代理前缀，加速组件更新下载

components:                        # 【重启】组件策略与自定义路径（设置页「组件路径」分组）
  yt-dlp:
    strategy: "auto"                # auto=校验后更新；notify=仅提醒；off=关闭
    path: "./bin/yt-dlp"            # 自定义可执行路径；留空用内置
  ffmpeg:
    strategy: "notify"
    path: "./bin/ffmpeg"
archive_protection:                 # 【即时】源端失效记录的本地标记前缀
  mark_deleted_prefix: "[源端已删]"  # 孤本保护：源端删除时给目录改名加此前缀
  tombstone_prefix: "[失效墓碑]"    # 墓碑：源端已失效且本地无存档时创建占位目录

wordcloud:
  enabled: false                    # 弹幕词云：下载完成后基于同目录 .danmaku.xml 生成 .wordcloud.svg
  max_terms: 60                     # 词云最多展示的词数

summary:
  enabled: false                    # 内容摘要：从字幕抽取式生成，写入 NFO <outline>（Plex 情节摘要）
  mode: "local"                     # local = 本地抽取式；llm 尚未实现（会外发字幕文本）
  max_chars: 220                    # 摘要最大字数

sync_collections:
  # mid 是合集所属 UP 主的 UID，id 是合集或系列 ID
  # - id: 67890
  #   mid: 12345
  #   name: "某个UP主的精华合集"

followings:
  # 关注 UP 主投稿同步。取关 UP 主后，本地已备份的资产默认保留不动。
  # mode:
  #   off  = 关闭（默认）
  #   all  = 全量同步登录账号的全部关注 UP 主
  #          ⚠️ 首轮拉取量大，强烈建议配合 max_downloads_per_run 小流量试跑
  #   list = 只同步下方 list 中显式列出的 UID（无需关注关系，可用于监控任意 UP 主）
  mode: "off"
  # 关注源的专栏（图文）投稿。off=不抓（默认） article=只抓专栏 all=视频+专栏都抓
  # 视频投稿始终随 mode 同步；此开关只控制额外的专栏请求。
  article_types: "off"
  list:
    # - mid: 946974
    #   name: "某UP主"        # name 可省略，省略时自动向 B 站查询
    # - mid: 12345678

favorites:
  # 留空此项将【自动拉取并备份您账号下的所有收藏夹】！
  # 如果只想备份特定收藏夹，请取消下方注释并填入：
  # - id: 12345678
  #   name: "指定收藏夹名称"
```

### 📋 设置页字段速查（v1.9.6 全字段）

WebUI「设置」页按分组展示以下字段；徽标含义：【即时】保存后热重载立即生效、【重启】核心进程重启后生效。

| 分组 | 字段 | 含义 | 生效 |
|---|---|---|---|
| 运行设置 | 磁盘保护阈值 (GB) | 剩余空间低于该值时暂停下载，防爆盘 | 需重启 |
| 运行设置 | 扫描间隔（秒） | 每轮全量巡检后的休眠时长（60~2678400） | 即时 |
| 运行设置 | 单轮下载上限 | 一轮巡检最多下载多少个；0=不限制 | 即时 |
| 运行设置 | 单项下载超时（秒） | 单个 yt-dlp 任务超时；0=不限制 | 即时 |
| 运行设置 | 输出模式 | Plex 分季（Season 01/S01E01）或平铺（P01） | 需重启 |
| 运行设置 | 完整性巡检 | off/light（大小+文件头）/full（ffmpeg 解码），抓"存在但损坏" | 需重启 |
| 运行设置 | 历史保留天数 | 观看历史回溯窗口；0=永久 | 即时 |
| 运行设置 | **启用下载** | **下载总开关（默认关）**：关闭时跳过全部下载来源，概览页显示"下载已暂停" | 即时 |
| 运行设置 | 同步稍后再看 | 把"稍后再看"列表纳入周期备份 | 即时 |
| 运行设置 | 同步观看历史 | 只记观看历史元数据，不下载视频本体 | 即时 |
| 运行设置 | **清晰度审计** | 巡检时对比本地与源端清晰度，低清清单在操作页确认清除重下 | 即时 |
| 运行设置 | 数据库 WAL | SQLite WAL 并发模式（需库目录可写） | 需重启 |
| 运行设置 | 启动时检查组件 | 启动时校验 yt-dlp/FFmpeg | 即时 |
| 网络设置 | 请求超时（秒） | 单次 HTTP 请求超时（1-300） | 即时 |
| 网络设置 | 同步重试次数 | 列表读取失败重试次数（1-10），耗尽后该来源本轮标记失败 | 即时 |
| 网络设置 | 重试退避（秒） | 重试指数退避初始间隔（0-60） | 即时 |
| 网络设置 | GitHub 代理前缀 | 组件更新下载加速（留空直连） | 需重启 |
| 组件路径 | yt-dlp / FFmpeg 策略 | auto=自动校验更新 / notify=仅提醒 / off=关闭 | 需重启 |
| 组件路径 | yt-dlp / FFmpeg 路径 | 自定义可执行文件位置；留空用内置 `./bin/` | 需重启 |
| 归档保护 | 源端已删前缀 | 源端删除时本地目录改名加此前缀（孤本保护，不删文件） | 即时 |
| 归档保护 | 失效墓碑前缀 | 源端失效且本地无存档时创建占位目录的前缀 | 即时 |
| UP 主同步 | 投稿同步范围 | off=关闭 / list=仅列表中 UID（可监控任意 UP 主）/ all=全部关注（首轮量大） | 即时 |
| UP 主同步 | 专栏同步范围 | off / 仅列表 / 全部关注（视频始终随投稿范围同步） | 即时 |
| UP 主同步 | UP 主列表 | 每行「UP 主 UID + 名称」，名称留空自动向 B 站查询 | 即时 |
| 词云与摘要 | 弹幕词云 | 下载完成后基于同目录 .danmaku.xml 生成 .wordcloud.svg | 即时 |
| 词云与摘要 | 词云最大词条数 | 词云展示词数上限（1-1000） | 即时 |
| 词云与摘要 | 视频简介摘要 | off=关闭 / local=本地抽取式，写入 NFO `<outline>`（Plex 情节摘要） | 即时 |
| 词云与摘要 | 摘要最大字数 | 摘要长度上限（50-10000） | 即时 |
| 收藏夹 | 收藏夹列表 | 每行「收藏夹 ID + 名称」；**支持一键"自动获取我的收藏夹"**；留空=备份全部收藏夹 | 即时 |
| 合集 | 合集列表 | 每行「合集 ID + UP 主 UID + 名称」；支持按 UID 自动获取全部合集 | 即时 |

**「操作」页附加能力**：下载总开关快捷启停按钮、立即巡检（跳过休眠提前开扫）、重启核心（安全退出交运维层）、重下单个资产、**清晰度审计**（全库对比 → 确认清单 → 清除低清自动重下高清）、配置热重载（保存设置自动触发）。

**「账号」页能力**：扫码登录（生成二维码，B 站 App 扫码后凭据自动写入，无需宿主机 Python）、当前登录状态常显（账号昵称 + UID / 失效原因）。

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

> `config.local.yaml` 只用于本地覆盖，不应放入发布包。Docker Compose 将本地覆盖写入 `data/config.local.yaml`，镜像内路径为 `/app/data/config.local.yaml`。

### 🔖 功能开关与档位说明

**关注 UP 主同步（`followings.mode`）**

| 档位 | 行为 | 适用场景 |
|---|---|---|
| `off` | 关闭（默认） | 只用收藏夹/合集等其它来源 |
| `all` | 全量同步账号已关注的**全部** UP 主投稿 | 想"关注即备份"；⚠️ 关注数多时首轮拉取量大 |
| `list` | 只同步 `list` 中列出的 UID | 精准监控少数 UP 主；无需关注关系，可监控任意人 |

- `all` 模式首次启用时建议设置 `max_downloads_per_run: 5` 试跑一轮，观察风控与磁盘消耗后再放开。
- `list` 模式条目支持 `[{mid: 946974, name: "某UP主"}]` 或纯 UID `[946974]`；省略名称时自动向 B 站补全。
- **取关语义**：取关（或从 list 移除）后，该 UP 主不再被扫描，但本地已备份的资产**永久保留**，程序不存在任何删除逻辑。
- 关注源与收藏夹共享同一套资产保护：失效投稿自动建墓碑或触发孤本保护；已完整归档的跳过。
- `article_types` 额外控制**专栏（图文）投稿**：`off`（默认）/ `article`（只抓专栏）/ `all`（视频+专栏）。专栏归档复用同一套 Markdown + NFO 管线。

**观看历史同步（`system.sync_watch_history`）**

- 开启后只把观看过的视频**元数据**（bvid、标题、UP 主、观看时间）记入本地数据库，**不会下载任何视频本体**。
- 用途：留存"我什么时候看过什么"的私人观影档案；记录不参与媒体库整理与巡检。
- `max_history_days` 控制回溯窗口（默认 90 天，`0` 不限）。历史动辄上万条，首次全量拉取请理解风控风险；增量轮次只追新记录，负担很小。

**完整性巡检（`system.verify_integrity`）**

| 档位 | 校验内容 | 代价 | 适合 |
|---|---|---|---|
| `off` | 不校验（默认） | 无 | 下载后基本不管、库小 |
| `light` | 文件非空 + 媒体容器签名（MP4/MKV/FLV/AVI 等） | 极低（纯字节读取） | 日常巡检推荐 |
| `full` | light 基础上追加 `ffmpeg` 前 5 秒解码探测 | 较高（CPU/时间） | 怀疑有坏文件、或重要库定期体检 |

- 每轮扫描最多抽样校验 20 个资产：从未校验的优先，之后最久未校验优先；大库会摊薄到多轮完成。
- 结果写入数据库 `integrity_status`（0 未校验 / 1 通过 / 2 损坏），WebUI 资产页可见。
- **只标记，不删除**：损坏文件（含孤本）会被保留并标记为"完整性异常"，是否重新下载由你根据源端是否还在自行决定。
- `full` 档位依赖 FFmpeg：找不到时该项校验报错标记，不会中断扫描。

**弹幕词云（`wordcloud.enabled`）**

- 开启后，视频下载完成时基于同目录的 `.danmaku.xml` 生成 `.wordcloud.svg`，文件名沿用 ASS 侧车习惯。
- **纯本地计算，不外发任何数据**，也不引入任何新依赖（SVG 由标准库生成）。
- 中文按**字符二元组**切分而非词典分词——弹幕是极短高频口语，二元组能自然捕获「前排」「泪目」这类模式，且完全确定、无外部词典依赖。
- 过滤「哈哈哈」「awsl」等应答噪声与虚词，但**保留「前排」「打卡」等高频且有语义的词**。
- **只生成不阻断**：XML 损坏、词数不足、渲染异常都只打印提示，不影响视频下载与 NFO 写入的成功判定。
- 关闭时（默认）零开销，不产生任何额外文件。

**数据库性能（`system.db_wal`）**

- 2 万资产实测：WebUI 资产列表 **9.46ms → 0.11ms**，计数 **8.12ms → 0.68ms**。索引在启动时自动创建，旧库无需手工迁移。
- `db_wal: true` 开启 SQLite WAL：写入不再被 WebUI 的并发读阻塞（实测 5.5 秒 → 15 毫秒）。
- **默认关闭**：WAL 需要在数据库同目录创建 `-wal` / `-shm` 文件，只读挂载或部分网络盘会失败。启用失败时程序静默退回默认日志模式并打印提示，功能不受影响。
- 已验证 WAL 模式下 WebUI 的只读连接（`mode=ro`）完全兼容，包括写事务进行中的读取。

**内容摘要（`summary.enabled`）**

- 开启后从**字幕文本**抽取式生成摘要，写入 NFO 的 `<outline>` 字段——这是 Plex 的情节摘要字段，会显示在媒体库详情页。
- **纯本地计算，字幕文本不会外发到任何服务器**，也不引入外部依赖。
- 优先读中文字幕（`.zh-Hans.srt/.vtt/.ass`），无字幕时退回视频简介；只读当前媒体自己的字幕，不碰同目录其他资产。
- 少于两句话时不做摘要，「一键三连」「欢迎收看」等套话会被过滤；多P视频只生成一份摘要。
- `mode: "llm"` 预留了外部 API 接入位，但**当前未实现**——外发字幕文本与本项目的资产保护取向冲突。填入该值会明确报错并跳过，不会静默当作本地处理。
- 摘要失败（内容过短、字幕缺失、内部异常）只打印提示，不影响视频下载与 NFO 写入。


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

### 3. 启动 WebUI

首次从源码使用 WebUI 需要 Node.js 20+ 构建前端；之后由 FastAPI 同源提供静态页面和 API：

```bash
cd webui
npm ci
npm run build
cd ..
python web.py
```

默认只监听 `127.0.0.1:8000`。若显式监听非 loopback 地址，必须通过环境变量提供 Token（找回凭据的后门）：

```bash
export BILIARCHIVE_WEB_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python web.py --host 0.0.0.0 --port 8000
```

**登录方式（v1.9.1 起）**：WebUI 以管理密码登录。首次启动自动生成 12 位初始密码并打印在日志 / `data/webui_auth.json` 中，登录后强制修改为 8-12 位、同时包含数字、大小写字母与符号的复杂密码；环境令牌仍可直接登录作为后门。会话只在当前浏览器会话中保存。

WebAPI 使用 SQLite `mode=ro` 浏览资产，不创建或迁移数据库（v1.9.1 起核心引擎首次启动会自动为存量库补 `source` 列并回填来源，不改动任何现有数据）。设置页可修改全部运行参数并区分「即时生效 / 需重启」：即时项保存后自动热重载到核心引擎，重启项会在下次核心重启后生效；数据库路径、Cookie 路径等私密字段仍不通过 WebUI 暴露。

**核心引擎未运行时**，概览页会显示醒目的提示条并给出启动命令，而不是含糊的「等待扫描」——因为 `runtime.json` 在引擎停止后仍会留在磁盘上，仅凭它无法判断核心是否在跑。

### 4. 从 WebUI 下发运维指令（v1.6.0 起）

WebUI 新增「操作」视图，可直接向核心引擎下发指令，无需 SSH：

| 指令 | 行为 | 说明 |
|---|---|---|
| `trigger_scan` | 立即巡检 | 跳过剩余休眠时间，提前开始下一轮巡检；进行中的下载不被中断 |
| `redownload_asset` | 重下单个资产 | 按 BV / av 编号重新抓取；本地已有文件不会被删除，按原目录规则写入并计入本轮下载量 |
| `restart` | 提示重启核心 | 核心在当前轮次结束后**安全退出并关闭数据库**，由 systemd / Docker / supervisor 重新拉起 |
| `reload_config` | 配置热重载 | 设置页保存后自动下发：来源列表、扫描参数等即时生效，无需重启（v1.9.1 起） |

工作方式与 `runtime.json` 一致，属于本地文件命令通道，不引入 WebSocket：

- WebUI 只把指令原子写入数据目录下的 `commands.json`，不直接连接守护进程。
- 守护进程每 5 秒轮询一次，休眠期也保持可唤醒，因此"立即巡检"无需等完整休眠结束。
- 每条指令都会被认领（claim）并回执，历史最多保留 50 条，可在「执行审计」中查看。

**安全边界（设计如此，不提供开关）：**

- **不开放删除本地资产**。任何删除类指令都会被拒绝，手工编辑 `commands.json` 注入也会被核心拒绝。
- 资产编号只接受规范的 `BV` / `av` 编号，不接受任意字符串或文件路径，因此无法用于路径穿越。
- 删除资产、强制覆盖等破坏性操作仍需在终端手工执行。
- `restart` 不会自杀式重启：若由 Docker Compose 托管，核心退出后容器可能直接停止，请确认编排策略。

### 5. 测试与限制下载数量
如果你只是想测试一下环境是否跑通，可以使用 `--limit` 参数限制本次运行最大下载数（到达指定数量后程序会自动安全退出）：
```bash
python main.py --cli --limit 3
```

### 6. 使用 PyInstaller 打包（可选，免 Python 环境分发）

核心引擎可以打包为目录分发的可执行文件，适合分发给不想装 Python 环境的用户。**v1.6.x 起推送版本标签会自动产出多平台产物**（Windows x64 / macOS Intel 与 Apple Silicon / Linux x64），无需手工打包：

```bash
# 打出新版本并推送标签，CI 会自动构建各平台产物
git tag -a v1.8.1 -m "v1.8.1" && git push origin v1.8.1
```

若需在本机打包：

核心引擎可以打包为免 Python 环境的单目录可执行文件，适合分发给不想装 Python 环境的用户：

```bash
# 在已安装依赖的虚拟环境中执行
pip install -r requirements.txt
pip install pyinstaller
venv\Scripts\python.exe -m PyInstaller build.spec --noconfirm

# 产物位于 dist\BiliArchive-Pro\，冒烟验证：
dist\BiliArchive-Pro\BiliArchive-Pro.exe --version
```

- 产物为**单目录模式**：整个 `dist\BiliArchive-Pro\` 目录缺一不可，分发时整体打包（zip）交付。
- 运行时程序会把工作目录切换到 exe 所在位置，`config.yaml`、`data/`、`downloads/`、`bin/`（ffmpeg/yt-dlp）都放在 exe 旁边即可，与源码运行的目录布局一致。
- **不含** `login.py` 与 WebUI：登录需要终端二维码交互，WebUI 需要前端构建产物，二者仍以源码方式运行。
- FFmpeg 不内嵌：把 `ffmpeg.exe` 放到 exe 同目录的 `bin/` 下，或保证其在系统 PATH 中。

### 7. 开发测试
如果你要参与开发或验证改动，可以安装开发依赖并运行测试：
```bash
pip install -r requirements-dev.txt
python -m pytest tests
python -m compileall main.py login.py web.py app
cd webui && npm ci && npm run lint && npm test && npm run build
```

前端测试用 Vitest + Testing Library（`webui/src/test/`），覆盖 API 参数拼接、分页筛选与运维指令的二次确认流程。

---

## 🧾 最新改进（v1.9.8）

完整版本说明见 [CHANGELOG.md](CHANGELOG.md)，历史版本明细见 [GitHub Releases](https://github.com/Stars4422335/BiliArchive-Pro/releases)。

**下载登录门禁 + 清晰度审计 + 下载总开关**

- 下载前强制校验登录状态（fail-closed）：游客身份只会拿到 480p/360p，门禁直接拒绝下载，杜绝低清入库。
- 「操作」页新增清晰度审计：对比本地已下载与源端可用清晰度（对比法，源本身就低的视频不误判），确认后一键清除低清资产并自动重下高清。
- 下载总开关默认关闭：升级后请在设置页/操作页打开「启用下载」；配合账号页扫码登录，构成「登录 → 开关 → 高清下载」的完整链路。
- 修复：设置保存报「不允许配置字段: effects」的问题（v1.9.4 引入的前端回传字段泄漏）。
- 清晰度审计单次覆盖全部已归档视频（此前只采样最近 300 个，导致清单不一致且越跑越多）。

## ❓ 常见问题

**启动后立刻退出，提示"登录凭据已失效"**
Cookie 有有效期（通常几个月）。重新扫码登录即可：

```bash
python login.py
```

程序会区分"凭据确实失效"和"网络临时抖动"：前者立即退出并提示，后者仍会继续（公开视频不依赖登录）。

**WebUI 概览页显示"核心引擎未运行"**
这是真实状态，不是页面 bug。`runtime.json` 在引擎停止后仍留在磁盘上，所以程序改为显式判断引擎是否真的在跑。启动核心引擎即可：

```bash
python main.py --cli
```

**下载失败，提示找不到 ffmpeg**
合并音视频需要 FFmpeg。Linux 用 `sudo apt install ffmpeg`，Windows / macOS 从 [ffmpeg.org](https://ffmpeg.org/download.html) 下载后放进项目的 `bin/` 目录。程序不会自动下载它。

**提示"某个来源同步失败"**
单个来源失败不影响其他来源继续扫描。常见原因是收藏夹 ID 已失效或该收藏夹已删除。用 `config.yaml` 核对 `favorites` / `sync_collections` 里的 ID。

**为什么有些视频只有 480P？掉登录后下载的视频怎么办？**
B 站对未登录访客限制清晰度（通常 480P 及以下）。v1.9.4 起内置**下载登录门禁**：掉登录时直接拒绝下载，不会再有"游客低清"入库。历史遗留的低清视频用「操作」页的**清晰度审计**处理：它会对比本地实际清晰度与源端当前可用最高清晰度，只有源端确实更高才列入清除清单，确认后自动删除并重下高清（源本身就只有低清的视频不会被误删）。

**审计每次跑出来的清单不一样？**
v1.9.6 起审计**一次覆盖全部已归档视频**（完成页显示"本次探测数 / 库内总数"）。耗时与库大小成正比（1418 个约 15-30 分钟，受 B 站接口风控节奏影响），期间保持页面打开。探测失败（网络抖动）的条目当轮跳过、下轮补上。

**下载总开关为什么默认是关的？**
`download_enabled` 默认 false 是安全设计：避免部署/升级后立即产生下载。正常使用流程是「账号页扫码登录 → 设置页打开启用下载」，之后引擎按周期自动巡检下载，掉登录时门禁兜底。

**下载的视频没有封面 / NFO**
关键 NFO 或标准封面写入失败时，程序**不会**记录完成状态，下一轮会自动重试。若反复失败，检查媒体目录是否可写、以及磁盘是否已满（`system.min_disk_gb`）。

**WebUI 登录密码 / 令牌**
日常登录用管理密码：首启自动生成（看核心容器日志），登录后强制改密。`BILIARCHIVE_WEB_TOKEN` 是找回凭据的后门；非 loopback 监听时必须配置它，默认 `127.0.0.1` 无需令牌。

**如何只归档视频、不抓专栏**
`followings.mode` 控制关注源的视频投稿；专栏由 `followings.article_types` 单独控制，设为 `off`（默认）即可。

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
- [x] **WebUI 管理面板**：概览、资产（含来源筛选）、全部设置项与运维指令；密码认证 + 令牌后门；数据库只读。
- [x] **WebUI 可操作化**：「操作」视图可触发即时巡检、重下单个资产、提示重启核心；本地文件命令通道 + 执行回执审计，删除本地资产始终不开放。
- [x] **智能路径管理**：跨平台安全的路径名非法字符过滤与防爆长路径自动截断机制。
- [x] **全量同步关注UP主**：`followings.mode` 支持 `all`（全部关注）/ `list`（指定 UID），失效投稿自动进入墓碑与孤本保护；取关后本地资产保留。`article_types` 可额外同步专栏图文。
- [x] **观看历史元数据**：`sync_watch_history` 把看过的视频记录为本地观影档案（仅元数据，不下载本体），支持 `max_history_days` 窗口。
- [x] **完整性巡检**：`verify_integrity` 三档（off/light/full）抽样校验已归档媒体，抓"存在但损坏"的静默失败，只标记不删除。
- [x] **跨平台打包**：推送版本标签由 CI 自动产出 Windows / macOS / Linux 三平台免 Python 环境分发包（PyInstaller 构建 + 冒烟验证 + 完整性检查 + SHA256）。

### 🟢 扩展功能 (已实现)
- [x] **弹幕词云**：`wordcloud.enabled` 基于同一份 `.danmaku.xml` 生成 `.wordcloud.svg` 侧车，零新依赖、纯本地计算，失败不影响下载。
- [x] **内容摘要**：`summary.enabled` 从字幕抽取式生成摘要写入 NFO `<outline>`，纯本地计算、字幕不外发；`mode: llm` 预留但明确拒绝（涉及隐私）。
- [x] **性能治理**：面向真实查询的索引 + WebUI 排序去表达式化；`db_wal` 可选开启 WAL。2 万资产实测 WebUI 列表 9.5ms→0.11ms、计数 8.1ms→0.7ms。

---

## 🤝 参与贡献

欢迎任何形式的贡献。开始之前请先阅读 **[CONTRIBUTING.md](CONTRIBUTING.md)**，里面写清了本地验证命令、测试要求，以及一条不可逾越的架构边界：**不得引入任何自动删除本地资产的路径**。

- 提交 Bug 与功能建议：使用 [Issue 模板](.github/ISSUE_TEMPLATE)
- 提交代码改动：PR 会自动套用[贡献清单](.github/pull_request_template.md)
- **安全问题请勿提交公开 Issue**，改用[私有漏洞报告](https://github.com/Stars4422335/BiliArchive-Pro/security/advisories/new)，详见 [SECURITY.md](SECURITY.md)

英文文档见 [README.en.md](README.en.md)。

## 📄 许可证

本项目采用 [GNU General Public License v3.0](LICENSE) 授权。分发修改版时必须继续使用 GPLv3 并提供对应源代码。

> **免责声明**：本项目仅供个人学习、技术研究及私有数字资产备份使用。请严格遵守 Bilibili 用户协议，尊重 UP 主版权，**严禁将抓取的内容用于任何商业用途或进行二次非法传播**。因使用不当造成的任何法律责任由使用者自行承担。
