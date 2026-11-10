# BiliArchive-Pro NAS Docker 离线安装指南

本包面向无法直接从镜像仓库拉取镜像的 NAS 环境（极空间、飞牛等），包含：

| 文件 | 说明 |
|---|---|
| `biliarchive-pro-*.tar` | Docker 镜像（已含核心引擎 + WebUI + FFmpeg 环境） |
| `docker-compose.yml` | 离线专用编排文件（无 build 段，WebUI 为默认服务） |
| `config.yaml` | 公共配置模板（挂载进容器，只读） |
| `.env.example` | WebUI 访问配置模板（绑定地址 / 端口 / token） |
| `install.sh` | 可选快捷脚本（需 SSH；图形界面安装请忽略它） |
| `SHA256SUMS` | 完整性校验 |

## 安装前须知：持久化目录

BiliArchive-Pro 把所有需要长期保留的数据都放在两个挂载目录里，**删除容器、升级镜像都不会丢**：

| 容器内路径 | 内容 | 建议的 NAS 宿主路径（示例） |
|---|---|---|
| `/app/data` | 数据库、登录凭证（cookie.json）、运行状态、本地覆盖配置 | 飞牛：`/vol1/1000/docker/biliarchive/data`；极空间：个人空间 `Docker/biliarchive/data` |
| `/app/downloads` | 媒体库输出（视频 / 专栏 / NFO / 封面） | 飞牛：`/vol1/1000/docker/biliarchive/downloads`；极空间：`Docker/biliarchive/downloads` |

`config.yaml` 在容器内是只读挂载；个人化配置写 `data/config.local.yaml`（程序会自动递归合并，列表和标量以本地覆盖为准），改完重启容器生效。

**登录方式（当前版本）**：需要先在一台装有 Python 的电脑上执行 `python login.py` 扫码，生成 `data/cookie.json` 后放到 NAS 的 `data` 挂载目录中，再重启容器。WebUI 内扫码登录在后续版本提供。

---

## 一、飞牛 fnOS（纯图形界面，无需 SSH）

1. **上传文件**：把解压后的整个文件夹上传到 NAS（如 `/vol1/1000/docker/biliarchive/`）。
2. **导入镜像**：打开 Docker 应用 → **本地镜像** → **添加镜像** → **从 NAS 文件添加** → 选中 `biliarchive-pro-*.tar` → 等待导入完成。
3. **创建 Compose 项目**：Docker → **Compose** → 新增项目 → 上传（或粘贴）包内的 `docker-compose.yml`。
4. **调整挂载路径**：确认 yml 中相对路径 `./data`、`./downloads` 指向你上传的目录（Compose 相对路径即 yml 所在目录；若把包解压到了别处，把相对路径改为绝对路径，如 `/vol1/1000/docker/biliarchive/data`）。
5. **配置 WebUI 访问**：默认只允许在 NAS 本机浏览器访问（免 token）。若要从自己的电脑访问，编辑 `.env`（复制 `.env.example`）：把 `BILIARCHIVE_WEB_BIND` 改为 `0.0.0.0`，并**必须**设置 `BILIARCHIVE_WEB_TOKEN`（否则 WebUI 容器会拒绝启动），然后重启项目。
6. **启动**：确定后等待两个容器（biliarchive 核心 + biliarchive-web 面板）运行。
7. **访问面板**：浏览器打开 `http://<NAS的IP>:8000`。

## 二、极空间 ZOS

> 前提：极空间 GUI 暂无"从文件导入镜像"入口，需 **2024 年 10 月及之后的固件**（才有 SSH 功能）。

1. **开启 SSH**：设置 → 系统设置 → 打开 SSH（用完可以关掉）。
2. **上传文件**：把整个文件夹上传到个人空间，建议路径 `个人空间/Docker/biliarchive/`。
3. **SSH 登录**：SSH 工具连接 NAS 后执行 `sudo -i`，进入上传目录：
   ```bash
   cd /你的个人空间路径/Docker/biliarchive
   ```
4. **导入镜像**：
   ```bash
   docker load -i biliarchive-pro-*.tar
   ```
   完成后 Docker 管理器的本地镜像列表会出现 `biliarchive-pro`。
5. **配置访问**（可选）：`cp .env.example .env`，按需修改（同上：`0.0.0.0` 必须配 token）。
6. **创建 Compose**：Docker 管理器 → **Compose** 标签页 → 新建 → 粘贴包内 `docker-compose.yml` 内容（支持相对路径与 `.env`）→ 确定。
7. **访问面板**：浏览器打开 `http://<极空间的IP>:8000`。

**极空间已知坑**：GUI 里映射宿主目录时显示的路径可能带 `/tmp` 前缀，属于显示问题，实际指向你的个人空间目录；Compose 方式不受影响。

## 三、其他支持 Docker 的 NAS（群晖 / 绿联 / 威联通等通用路径）

任何能执行 `docker load` 的环境都适用：

```bash
docker load -i biliarchive-pro-*.tar
cp .env.example .env   # 按需修改
docker compose --env-file .env up -d
```

## 四、验证与日常运维

```bash
# 查看核心引擎日志（下载/巡检活动）
docker compose logs -f biliarchive

# 查看 WebUI 日志
docker compose logs -f biliarchive-web

# 重启（应用 config.local.yaml 修改后）
docker compose restart

# 停止（不删除任何数据）
docker compose down
```

面板能力：扫描状态概览、资产浏览与筛选、配置编辑、运维指令（立即巡检 / 重下单个资产 / 重启核心），执行记录可在「执行审计」查看。**删除本地资产不开放**——这是产品安全边界。

## 五、常见问题

- **WebUI 容器反复重启**：十有八九是 `BILIARCHIVE_WEB_BIND` 改成了 `0.0.0.0` 但没设 `BILIARCHIVE_WEB_TOKEN`。看 `docker compose logs biliarchive-web`，按报错补 token。
- **核心容器一直重启**：多半是没有登录凭证。按上文"登录方式"放入 `cookie.json` 后 `docker compose restart`。
- **磁盘占用持续增长**：媒体库在 `downloads` 目录，属正常；确认挂载路径没指错地方。
- **升级新版本**：下载新离线包 → `docker load` 新 tar → 若镜像 tag 变化，修改 compose 中 `image:` 行 → `docker compose up -d`。数据在挂载目录里，不会丢失。
