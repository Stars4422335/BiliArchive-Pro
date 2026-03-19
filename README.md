# 📺 BiliArchive-Pro

> **专业的 Bilibili 个人数字资产全量备份系统**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

**BiliArchive-Pro** 旨在为 B 站深度用户提供一套稳定、安全且符合影视库管理规范（如 Plex、Jellyfin、Emby）的本地自动化备份方案。它不仅是一个支持最高 4K/HDR 画质的下载器，更是一个智能的**个人数字图书馆管理员**。

无论是防备 UP 主删稿、视频失效，还是希望将 B 站的优质视频、专栏图文永久纳入自己的私人 NAS 影视库，BiliArchive-Pro 都能为你提供“开箱即用”且“一劳永逸”的守护。

---

## ✨ 核心特性

- 🚀 **全能媒体抓取**：不仅仅是视频！支持最高画质视频下载（含多 P 分集），同时**独家支持专栏图文**抓取（自动转为 Markdown 并将图片本地化保存）。
- 🎬 **完美适配影视库 (Plex/Jellyfin)**：自动刮削并生成符合标准规范的 `.nfo` 元数据、下载高清封面图，并将 UP 主映射为演职员信息。
- 🛡️ **首创数字资产保护逻辑**：
  - **墓碑机制 (Tombstone)**：扫描到收藏夹中已被 B 站删除的失效视频时，在本地生成 NFO 占位符，记录遗失的元数据。
  - **孤本保护**：如果本地已下载好的视频后来被源端删除，本地资产会自动打标锁定（如添加 `[源端已删]` 前缀），绝不发生误覆盖或同步删除。
- ⚡ **智能增量与防风控**：采用“连续重复熔断”的增量扫描策略，仅下载新增内容，大幅减少 API 请求；内置随机休眠机制，有效防止账号被风控。
- 💬 **弹幕智能渲染**：自动下载 B 站原生 XML 弹幕，并利用内置渲染引擎实时转换为各大播放器通用的 `.ass` 高级字幕格式。
- 🔄 **组件全自动更新**：启动时自动检测并从 GitHub 拉取更新 `yt-dlp` 及 `ffmpeg` 环境，自带网络加速镜像配置。

---

## 🛠️ 安装与部署

BiliArchive-Pro 支持在 Windows、macOS、Linux (含 WSL) 以及各类 NAS 平台上运行。你可以选择**本地原生运行**或使用 **Docker 容器化部署**。

### 方式一：本地 Python 原生运行 (推荐开发/测试使用)

**1. 环境准备**
确保系统已安装 **Python 3.10+** 以及 [**FFmpeg**](https://ffmpeg.org/download.html) (用于音视频合并，Windows/Mac 用户可直接将 `ffmpeg.exe` 放入本项目的 `bin/` 目录下，Linux 用户可 `sudo apt install ffmpeg`)。

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

> **持久化说明**：Docker 会将 `data/` (数据库与凭证)、`downloads/` (视频与专栏库)、`bin/` (组件工具) 以及 `config.yaml` 完美映射到宿主机的项目目录下，随时可以迁移备份。

---

## ⚙️ 配置指南 (`config.yaml`)

项目根目录下的 `config.yaml` 是整个系统的核心控制台。首次运行前，建议根据个人需求进行微调：

```yaml
system:
  download_path: "./downloads"       # 媒体库保存位置
  plex_mode: true                    # 开启后，多P视频会独立建文件夹，完美适配 Plex/Jellyfin
  max_downloads_per_run: 0           # 0代表无限制。若只想测试，可改为 5

network:
  github_proxy_url: "https://mirror.ghproxy.com/" # 解决国内服务器下载 yt-dlp 失败的问题

favorites:
  # 留空此项将【自动拉取并备份您账号下的所有收藏夹】！
  # 如果只想备份特定收藏夹，请取消下方注释并填入：
  # - id: 12345678
  #   name: "指定收藏夹名称"
```

---

## 🚀 使用指南

### 1. 账号授权登录
无论是哪种部署方式，首次使用都必须获取 B 站授权：
```bash
python login.py
```
- 支持**二维码登录**（推荐，最稳定安全）和**手机号短信登录**。
- 登录凭证加密存储于 `./data/cookie.json`，不会上传或泄露。

### 2. 启动守护进程
获取凭证后，即可启动后台扫描与下载引擎：
```bash
python main.py --cli
```
系统会自动拉取所有的收藏夹并开始高并发下载，本轮任务结束后会进入休眠状态（默认 1 小时后再次扫描），适合搭配 `tmux`、`screen` 或 `systemd` 长期挂机。

### 3. 测试与限制下载数量
如果你只是想测试一下环境是否跑通，可以使用 `--limit` 参数限制本次运行最大下载数（到达指定数量后程序会自动安全退出）：
```bash
python main.py --cli --limit 3
```

---

## 📋 功能清单与开发状态 (TODO)

本项目正在持续迭代中。以下是当前的开发进度：

### 🟢 核心功能 (已实现)
- [x] **全自动引擎**：无头守护进程，自动拉取账号下所有收藏夹，并支持配置文件指定拉取。
- [x] **双重登录机制**：终端二维码扫码登录 + 手机号短信验证码登录。
- [x] **最高画质下载**：基于 `yt-dlp` 的 4K/HDR 视频与高质量音频自动抓取及合并。
- [x] **Plex/Jellyfin 生态适配**：自动生成标准 `movie.nfo` 元数据、下载高清封面图、提取 UP 主信息。
- [x] **专栏图文支持**：自动识别收藏夹中的专栏文章，抓取正文转为 `Markdown`，并将网络图片本地化下载保存。
- [x] **弹幕渲染器**：内置 `DanmakuConverter`，自动将 B 站 XML 弹幕渲染为各大播放器原生支持的高级 `.ass` 字幕。
- [x] **资产保护机制**：独立实现的“墓碑机制（Tombstone）”与“孤本保护”，防止源端失效导致本地资产连带损失。
- [x] **增量扫描策略**：自动记忆已下载资产，支持“连续重复熔断”机制（遇到连续10个已下载视频即停止翻页），彻底告别每次全量扫描的低效与风控风险。
- [x] **组件自动更新**：内建热更新模块，每次启动前自动对比 GitHub 检查并升级 `yt-dlp` 与 `ffmpeg`。
- [x] **Docker 容器化**：提供包含完整环境的轻量级镜像与 `docker-compose.yml` 一键部署方案，完美解决依赖问题。
- [x] **智能路径管理**：跨平台安全的路径名非法字符过滤与防爆长路径自动截断机制。

### 🟡 扩展功能 (规划中/开发中)
- [ ] **跨平台打包**：使用 PyInstaller 打包生成 Windows/Mac/Linux 独立可执行文件（免配 Python 环境）。
- [ ] **WebUI 管理面板**：提供现代化的可视化网页端，用于查看下载进度、管理数据库资产、修改配置。
- [ ] **播放列表同步**：支持同步“稍后再看”列表及历史观看记录。
- [ ] **AI 内容摘要**：接入大模型，在下载完成后自动分析视频/专栏内容，并在 NFO 中追加 AI 内容摘要。
- [ ] **弹幕词云图**：基于下载的弹幕文件，自动生成并保存弹幕词云图作为媒体库的海报/背景图。

---

## 🤝 参与贡献

欢迎任何形式的贡献！如果你有更好的想法，或者发现了 Bug，欢迎提交 Pull Request 或开 Issue 讨论。

## 📄 许可证

本项目采用 [MIT License](LICENSE) 授权。

> **免责声明**：本项目仅供个人学习、技术研究及私有数字资产备份使用。请严格遵守 Bilibili 用户协议，尊重 UP 主版权，**严禁将抓取的内容用于任何商业用途或进行二次非法传播**。因使用不当造成的任何法律责任由使用者自行承担。
