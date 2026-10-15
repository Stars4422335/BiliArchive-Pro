# 参与 BiliArchive-Pro 开发

感谢你愿意参与。本项目由个人维护，回复可能不快，但每个 Issue 和 PR 都会看。

## 项目定位

BiliArchive-Pro 是 B 站个人数字资产备份工具。它的核心价值不是"能下载视频"，而是**保证已归档的本地资产不会丢失**——无论 B 站源端如何变化。

这决定了很多设计取舍，也是下面"不能碰"清单的由来。

## 快速开始

```bash
git clone https://github.com/Stars4422335/BiliArchive-Pro.git
cd BiliArchive-Pro

python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt

# 前端
cd webui && npm ci && npm run build && cd ..
```

本地个人配置写入 `config.local.yaml`，**不要**修改受 Git 管理的 `config.yaml` 去存私人收藏夹 ID 或绝对路径。

## 提交前必须通过

```bash
python -m pytest tests -q
python -m compileall -q main.py login.py web.py app
cd webui && npm run lint && npm run build
```

涉及 `Dockerfile` 或依赖变更时额外执行：

```bash
docker build -t biliarchive-pro:local .
```

CI 会在 Windows / Linux × Python 3.10 / 3.12 上跑后端测试，另跑 Node 22 前端 lint+build 和 Docker 构建。本地全绿再提交，能省掉一轮往返。

## 硬性边界：以下改动不会被接受

这些不是风格偏好，而是这个项目存在的前提。改动触碰了它们，PR 会被直接关闭：

1. **任何自动删除本地资产的路径**

   源端视频失效时，程序只做两件事：建墓碑占位，或给本地目录加 `[源端已删]` 前缀。**绝不删除文件**。

   删除本地资产只能由你在终端手工执行。WebUI 也不提供删除指令——它连表达"删除某个文件"的能力都不存在。

2. **绕过校验的快捷路径**

   外部输入（BV 号、配置项、WebUI 参数）都要做类型、长度和取值校验。不要为了"代码简洁"用 `eval`、`shell=True` 或字符串拼接 SQL。

3. **让 WebUI 具备写数据库的能力**

   WebAPI 通过 SQLite `mode=ro` 只读访问资产表，从不创建、迁移或写入数据库。它能写的东西只有两个：本地覆盖配置，和 `commands.json` 命令通道。

4. **把凭据或本地状态纳入版本控制**

   `data/`、`downloads/`、`bin/`、`venv/`、`config.local.yaml`、`.env`、本地任务记录，都不能进 Git、Docker 镜像或发布包。

5. **隐式安装远程可执行文件**

   `yt-dlp` 只在显式开启启动检查且策略为 `auto` 时更新，且必须先通过 GitHub 官方 SHA256 校验。FFmpeg 只探测不下载。

## 架构约定

完整说明见 [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)，几条最常踩的：

- **分层**：`app/core/`（解析、下载、元数据、路径、数据库、命令通道）→ `app/scheduler/`（扫描与组件检查）→ `app/webui/`（只读服务与 API）。依赖只从上往下。
- **数据库迁移**：在启动事务中补列，不要求用户手工操作；查询不依赖列顺序。
- **完成状态**：视频、专栏或墓碑的关键 NFO、以及视频标准封面写入失败时，**不得**写入数据库完成状态，下一轮会继续处理。
- **运维指令**：走 `commands.json` 文件通道（原子写入 + 幂等认领 + 审计回执），不引入 WebSocket 或其他 IPC。新增指令要同步更新前端「操作」视图、CHANGELOG 和测试。
- **休眠语义**：守护循环休眠按分片轮询，保证指令能及时唤醒。

## 测试要求

新增功能必须带测试。当前 197 例，核心路径和失败路径（超时、缺集、失效视频、损坏文件）都有覆盖。

写测试时优先覆盖**失败路径**，而不只是 happy path。一个只测成功场景的测试几乎没有价值。

```bash
python -m pytest tests/test_xxx.py -q          # 单文件
python -m pytest tests -q -k "关键字"           # 按名字筛选
```

测试不得访问真实 B 站账号或网络。用 fixture 替换 `BiliParser`、`Downloader`、`DatabaseManager`。

## 提交与发版

提交信息用祈使句，说明动机而非罗列文件：

```
fix: 损坏的 NFO 不应写入完成状态

关键 NFO 写入失败时仍记录成功，导致该资产永久不再重试。
改为写入失败时保留未完成状态，下轮扫描继续处理。
```

发版流程见 [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) 的「发布流程」。版本号需要同步的位置：`app/__init__.py`、`webui/package.json`、Dockerfile 镜像标签与 `BILIARCHIVE_VERSION`、README 徽章、CHANGELOG。`tests/test_release_safety.py` 会校验这些一致性。

## 报告安全问题

**不要提交公开 Issue。** 请使用 [私有漏洞报告](https://github.com/Stars4422335/BiliArchive-Pro/security/advisories/new)，详见 [SECURITY.md](SECURITY.md)。

## 改 CI 工作流前

`.github/workflows/release.yml` 负责三平台打包发布，它踩过的坑集中在 [DEVELOPER_GUIDE.md 的「跨平台脚本踩过的坑」](DEVELOPER_GUIDE.md)。其中几条会直接导致发布失败：

- **不要在 `dist/` 里找纯 Python 包目录**——`noarchive=False` 把它们全压进了可执行文件内的 PYZ，磁盘上不存在
- **不要无条件 `sudo`**——`windows-latest` 没有 `sudo`，包管理器要按平台分支
- **不要假设 `shasum` / `sha256sum` 到处都有**——校验值统一用 Python 的 `hashlib`
- **改之前先在本地用模拟产物跑一遍脚本逻辑**，不要靠 CI 一轮轮试错

## 许可

贡献的代码以 GPLv3 发布。提交 PR 即表示你同意以此许可授权。