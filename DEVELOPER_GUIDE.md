# BiliArchive-Pro 开发维护指南

## 配置边界

- `config.yaml` 是受 Git 管理的默认模板，不应写入个人收藏夹、绝对路径或测试开关。
- 本机配置写入 `config.local.yaml`。程序启动时会递归合并该文件，列表和标量以本地值为准。
- `config.local.yaml`、`.env`、`data/`、`downloads/`、`logs/` 和 `bin/` 不得提交或加入发布包。
- 根目录的 `本地任务计划与执行表.md` 仅用于本地执行记录，禁止使用 `git add -f` 强制提交。
- 组件策略只允许 `auto`、`notify`、`off`；自动更新的可执行文件必须先通过官方 SHA256 校验，下载流程不得自行安装组件。
- `sync_collections` 的每个条目必须同时提供合集 `id` 和所属 UP 主 UID `mid`。
- WebUI 只能写入 `app/webui/service.py` 中声明的公开白名单；不得暴露或修改下载路径、数据库路径、Cookie 路径和代理地址。
- WebUI 命令端点只能下发 `app/core/commands.py` 中 `SUPPORTED_COMMANDS` 列出的指令；新增指令必须同时更新前端「操作」视图与 CHANGELOG。**任何删除类能力都不得加入该白名单。**
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
13. **命令通道**：WebUI 不直连守护进程，只把指令原子追加到 `commands.json`（与 `runtime.json` 同级）；守护进程认领（先标记 `running` 再执行，保证不重复）后逐条回执，审计历史上限 50 条。
14. **休眠可中断**：守护循环休眠按 5 秒分片轮询，使 `trigger_scan` 能及时唤醒；轮次开始前额外消费一次命令，让 `redownload_asset` 当轮命中。
15. **命令安全边界**：删除本地资产**永不开放**。删除类指令名硬编码拒绝（含手工编辑 `commands.json` 注入的情况）；`asset_id` 只接受 `BV`/`av` 正则白名单，命令载荷不得携带路径；`note` 与回执截断单行 200 字符防日志注入。
16. **重下豁免一次性消费**：`request_redownload()` 同时登记 BV 与 av 拼写，`_should_skip_archived_video()` 命中时当轮豁免跳过判定并立即从白名单移除，下一轮恢复正常跳过。

## 媒体库布局

- 单 P：媒体、NFO、普通字幕和弹幕侧车使用同一前缀，目录内额外生成 `poster.jpg`。
- 多 P 且 `plex_mode=true`：根目录保存 `tvshow.nfo`、`poster.jpg`，媒体写入 `Season 01/S01E## - 标题 [BV-P#]`。
- 多 P 且 `plex_mode=false`：媒体平铺为 `P## - 标题 [BV-P#]`，每个分 P 使用独立 movie NFO。
- 现有归档不自动迁移；布局变化只应用于新下载或用户明确触发的重新下载。

## 目录职责

- `app/core/`：下载、解析、元数据、路径、数据库、命令通道和敏感文件写入工具。
- `app/scheduler/`：收藏夹扫描和组件环境检查。
- `app/webui/`：只读资产服务、配置白名单、命令下发端点与 FastAPI 应用工厂。数据库始终只读，写操作仅限配置本地覆盖与命令通道文件。
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

### 自动化发版（v1.6.x 起）

推送 `vX.Y.Z` 标签会触发 `.github/workflows/release.yml`，无需手工执行上述步骤：

1. `source` 作业用 `git archive` 从标签生成源码 ZIP，并**逐条目审计**：去掉归档前缀后，顶层的 `config.local.yaml`、`data/`、`downloads/`、`bin/`、`venv/`、`logs/`、`__pycache__/`、`.mimosa/`、本地任务记录，以及任何 `*.db` / `*.db-wal` / `*.pyc` 都会让作业失败。
2. `build` 作业在三个**原生 runner** 上并行构建。PyInstaller 不能交叉编译，所以 Windows / macOS / Linux 各占一个 runner，而不是矩阵里可替换的维度。
3. 每个平台依次执行：归档工具就绪（按平台选 choco / brew / apt）→ PyInstaller 构建 → **`--version` 冒烟并与 `app/__init__.py` 比对版本号 + 运行时依赖导入检查** → 产物规模检查 → 打包 → SHA256（用 Python 的 `hashlib`）→ 上传。
4. 全部上传到**草稿 Release**，由 `publish` 作业在三个平台都成功后统一转为正式发布。任一平台失败则不会产生正式 Release。

手工触发：对已有标签执行 `workflow_dispatch` 并填入 tag。

> 冒烟验证是刻意加的：隐藏导入漏依赖或平台差异只会在真正运行时暴露，没有这一步就会把打不开的包发给用户。

### 跨平台脚本踩过的坑

v1.7.0 首次发布连续失败三轮，全部是 `release.yml` 自身的缺陷。改动这个工作流前请先读完这一节。

**1. 不要用子串搜索审计归档内容**

把整个条目清单拼成一段文本再 `case` 匹配子串，会误伤合法路径：`webui/src/data/normalize.js` 里含 `/data/`，却与根目录的 `data/` 毫无关系。**必须逐条目比对**，且要先剥掉 `BiliArchive-Pro-vX.Y.Z/` 前缀——只有前缀之后的位置才有意义。

**2. 不要在 dist/ 里找纯 Python 包目录**

`build.spec` 用 `noarchive=False`，所有纯 Python 模块都压进了可执行文件内部的 PYZ 归档，磁盘上**不存在** `yt_dlp/`、`bilibili_api/` 这类目录。按文件查找的完整性检查永远不可能通过，它此前只是恰好没被触发。

要验证依赖是否齐备，正确做法是**导入**：让产物跑 `--version`（`main.py` 的 import 链已覆盖 `bilibili_api` 与 `app.*`），再对构建环境做一次 `importlib.import_module`。产物完整性则看文件数与编译型依赖（`*.pyd` / `*.so` / `*.dll` / `*.dylib`）是否随包落盘。

**3. GitHub runner 没有 sudo，也各用各的包管理器**

`windows-latest` 根本没有 `sudo`，无条件 `sudo apt-get` 会直接 127 退出。包管理器必须按矩阵变量分支：`choco` / `brew` / `apt`。GitHub runner 上这三个都免密，可以一律去掉 `sudo`。

**4. 不要假设命令行工具在所有平台都存在**

`shasum` 只有 macOS 有，Windows 的 Git Bash 里没有；`sha256sum` 也不是每个 runner 都装了。校验值统一用 Python 的 `hashlib`——三个平台的 runner 都装了 Python。

**5. `set -o pipefail` 下不要用 `| head` / `| grep -q`**

读端提前退出会让写端收到 SIGPIPE，`pipefail` 会把整条管道判为失败，而且失败点离真正的原因很远。需要判断内容时，先把结果捕获进变量，再用 `case` 匹配。

**6. `tar` 的选项与文件名之间必须有空格**

`tar -C dist -czf "${NAME}.tar.gz" DIR` 里 `-czf` 与文件名相邻，会被解析成单个选项串，报 `Cannot open: No such file or directory`。写成 `tar -czf "dist/${NAME}.tar.gz" -C dist DIR`。

**7. 改工作流前先在本地复现**

这三条修复之前都是靠 CI 一轮轮试错发现的，代价是每次都要重跑整个三平台矩阵（数分钟）加上强制移动 tag。正确做法是**先在本地用模拟产物跑一遍脚本逻辑**（tar 语法、归档清单、校验文件格式、完整性检查），全部通过再提交。工作流里的 shell 片段应该能在本地 `bash` 直接执行验证。

**8. tag 可以移动，但要谨慎**

发布失败且未产出任何产物时，强制更新 tag 是合理的（内容修正后重发）。但一旦有用户或下游消费了该 tag，移动它就是破坏性的——移动前先确认 Release 从未成功发布过。
