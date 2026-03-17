# 📺 BiliArchive-Pro

> **专业的 Bilibili 个人数字资产全量备份系统**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

BiliArchive-Pro 旨在为 B 站深度用户提供一套稳定、安全且符合影视库管理规范（Plex/Jellyfin）的本地备份方案。它不仅是下载器，更是你的个人数字图书馆。

---

## ✨ 核心特性

- 🚀 **全能抓取**：支持 4K/HDR 最高画质视频下载，自动处理分 P 视频及图文专栏。
- 📦 **Plex 模式**：自动生成符合 Plex/Jellyfin 标准的 NFO 元数据、封面图及演职员信息。
- 🛡️ **资产保护逻辑**：
  - **墓碑机制 (Tombstone)**：视频被删？本地保留元数据占位，并支持视频“复活”后自动补全。
  - **孤本保护**：源端删除已下好的视频？本地资产自动打标锁定，绝不误删/覆盖。
- 🔄 **组件独立更新**：支持 `yt-dlp` 和 `ffmpeg` 独立在线更新，并为国内用户内置了 **GitHub 加速下载** 通道。
- 🐳 **多端部署**：支持 WSL/Linux、Windows/Mac 原生运行，并提供 Docker 一键挂载部署方案。

---

## 🛠️ 快速开始

### 1. 环境准备
确保你的环境中已安装 Python 3.10+。
```bash
git clone 该项目
cd BiliArchive-Pro
pip install -r requirements.txt

### 2. 账号登录
本项目采用扫码登录方式，安全快捷，凭证加密存储于本地。
```bash
python login.py
```
*请使用 Bilibili 手机 App 扫描控制台出现的二维码并确认。*

### 3. 启动备份
```bash
python main.py --cli
```

---

## 📂 项目结构

```text
├── app/               # 核心引擎代码
├── bin/               # 外部二进制工具 (yt-dlp, ffmpeg)
├── data/              # 登录凭证与数据库 (不上传)
├── downloads/         # 你的个人视频库 (不上传)
├── config.yaml        # 所有的偏好设置都在这里
└── main.py            # 程序总入口
```

---

## ⚙️ 配置文件说明 (`config.yaml`)

你可以根据需求修改 `config.yaml`：
- `download_path`: 修改为你硬盘或 NAS 的路径。
- `github_proxy_url`: 填入加速前缀（如 `https://mirror.ghproxy.com/`）以加快组件更新速度。
- `min_disk_gb`: 磁盘剩余空间预警值，防止写满。

---

## ✅ 功能清单 (TODO)

### 已实现功能

- [x] **核心架构** - 模块化设计 (app/core/, app/scheduler/)
- [x] **多方式登录** - 二维码登录 + 短信验证码登录
- [x] **Cookie管理** - JSON格式存储 + Netscape格式转换(yt-dlp兼容)
- [x] **最高画质下载** - 4K/HDR视频下载(yt-dlp)
- [x] **自动获取收藏夹** - 自动拉取用户的所有收藏夹列表
- [x] **多P视频检测** - 自动检测并标记分P视频
- [x] **Plex兼容** - 自动生成NFO元数据、封面图
- [x] **墓碑机制(Tombstone)** - 源端删除视频保留元数据占位
- [x] **孤本保护** - 本地已下载但被源端删除的视频自动锁定
- [x] **风控保护** - 随机休眠机制防封号
- [x] **数据库管理** - SQLite记录资产状态(Active/Tombstoned/Protected)
- [x] **路径安全** - 防爆路径截断、非法字符过滤
- [x] **配置管理** - YAML配置文件支持

### 待开发功能

- [ ] **WebUI界面** - 桌面GUI托盘模式(开发中)
- [ ] **专栏图文下载** - 专栏文章转Markdown及图片本地化
- [ ] **组件自动更新** - yt-dlp/ffmpeg自动检测更新
- [ ] **Docker部署** - 一键Docker容器化部署
- [ ] **弹幕渲染** - 弹幕下载并渲染为ASS字幕
- [ ] **AI摘要** - 视频内容AI自动摘要
- [ ] **跨平台打包** - Windows/Mac/Linux可执行文件
- [ ] **播放列表同步** - 支持稍后再看/历史记录同步
- [ ] **增量备份** - 仅下载新增内容的高效模式

---

## 🤝 参与贡献

如果你有更好的想法（例如 AI 视频摘要、弹幕渲染转换等），欢迎提交 Pull Request 或开 Issue 讨论。

## 📄 许可证

本项目采用 [MIT License](LICENSE) 授权。

---

**免责声明：** 本项目仅供个人学习及数字资产备份使用。请遵守 Bilibili 用户协议，尊重 UP 主版权，严禁用于商业用途或非法传播。

---


