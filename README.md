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
git clone [https://github.com/你的用户名/BiliArchive-Pro.git](https://github.com/你的用户名/BiliArchive-Pro.git)
cd BiliArchive-Pro
pip install -r requirements.txt
