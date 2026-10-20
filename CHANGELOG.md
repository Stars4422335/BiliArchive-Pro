# BiliArchive-Pro 变更记录

本文件记录正式发布版本的用户可见变更。版本号遵循语义化版本格式。

## [Unreleased]

### 测试平台化修正

- 修正路径穿越测试的跨平台假设：原用例断言反斜杠写法在所有平台都构成越界，这在 Linux 上不成立（反斜杠是合法文件名字符，路径仍在基目录内）。通用用例改用两个平台都是分隔符的正斜杠写法，反斜杠用例拆为仅 Windows 执行的独立测试。**生产代码的路径穿越防护本身在两边都是正确的**，错的是测试的预期。

### 前端测试与交互修复

- 新增前端测试基础设施（Vitest + React Testing Library + jsdom），CI 增加 `npm test` 步骤。此前 CI 只跑 ESLint 与 build，**两者都不验证运行时行为**，交互回归无法被捕获。
- **修复「重新下载资产」确认流程完全失效**：父组件用对象记录待确认项，卡片却用字符串比较，导致 `confirming` 恒为 false——用户输入编号点「重新下载」不会有任何反应；同时确认框里的资产编号取自布尔值，恒为 `undefined`。现在待确认项直接携带资产编号，确认框显示正确的编号并把它随指令下发。
- 新增 33 例前端测试：API 客户端的参数拼接与错误处理、资产列表的分页/筛选/详情抽屉、运维指令的二次确认（含「未确认前绝不下发指令」与「非法编号按钮禁用」）。

### 可用性修复（实际部署验收发现）

首次部署验收时逐项跑通「运行 → 部署 → 使用」全流程，发现并修复三个影响日常使用的问题：

- **登录凭据失效时不再空转**：原先 `check_cookie` 在凭据失效后仍返回凭据对象，守护进程会带着死 cookie 跑完整个 6 小时休眠周期，每个来源各重试 3 次。现在区分「鉴权失败」与「临时故障」：前者（B 站 -101 账号未登录、-111 csrf 校验失败、LoginError、SESSDATA 失效语义）立即明确退出并提示重新登录；后者（网络抖动、超时、5xx、以及 -400 请求错误 / -509 请求过于频繁这类非鉴权错误码）保持原有宽松行为，公开视频仍可下载。
- **WebUI 能区分「核心没跑」与「核心空闲」**：runtime.json 在引擎停止后仍留在磁盘上，原前端只能把两者都显示成「等待扫描」，用户无从判断。现在 API 显式返回 `core_running`，概览页在核心未运行时显示醒目提示并给出启动命令。判据同时考虑 `status` 与 `stopped_at` 标记——被 `kill -9` 强杀留下的陈旧文件也不会被误读成「仍在运行」。
- **退出时不再刷出看不懂的 traceback**：`bilibili_api` 的 atexit 清理把分支写反了（`if loop.is_closed(): loop.run_until_complete(...)`），导致每次正常退出（Ctrl+C / --limit 完成）都抛 `Event loop is closed` 并附带 coroutine 警告。现在关闭 loop 后置空当前事件循环，让它的 `except RuntimeError` 分支安静返回，不改动第三方库。

## [1.7.1] - 2026-10-16

### 安全修复：专栏图片域名白名单可被绕过

- **修复 SSRF 白名单绕过**：原先用裸 `endswith` 匹配域名，任何以受信串结尾的域名都会通过——`https://evil-hdslb.com/x.jpg` 与 `https://notbilibili.com/x.jpg` 会被放行。攻击者只需注册此类域名，就能让程序向任意主机发起请求，该防护自 v1.4.0 引入起形同虚设。
- 改为**按标签边界匹配**：域名本身，或以 `.受信域` 开头的真子域才放行。同时只接受 `https`，避免明文传输与本地探测，并补充 `bilivideo.com`（B 站官方 CDN）。
- **补齐路径穿越与 SSRF 的自动化回归测试**：`tests/test_security_paths.py` 38 例。这两道防线是 v1.4.0 安全加固引入的（对应路径穿越 ×4、SSRF ×2），但当时只做过一次性手工验证，从未沉淀为测试——SSRF 白名单的缺陷因此潜伏至今而未被发现。

## [1.7.0] - 2026-10-14

### 发版流水线修复（首次发布实测）

`release.yml` 在 v1.7.0 首次真实运行时连续三轮失败，全部是工作流自身的缺陷，现已修复并沉淀到 `DEVELOPER_GUIDE.md`：

- **归档审计改为逐条目匹配**：原先把整个条目清单拼成文本做子串搜索，误将合法的 `webui/src/data/normalize.js` 判为含 `/data/` 而失败。
- **产物完整性检查纠正原理**：原先在 `dist/` 里查找 `yt_dlp` / `bilibili_api` 等目录，但 `noarchive=False` 已把它们全部压入可执行文件内的 PYZ，该检查永远不可能通过。改为验证产物存在、文件数合理、编译型依赖随包，并用**导入**而非文件查找来确认运行时依赖。
- **包管理器按平台分支**：`windows-latest` 没有 `sudo`，原先无条件 `sudo apt-get` 直接 127 退出。改为按矩阵变量选 choco / brew / apt，并统一去掉 `sudo`。
- **校验值改用 Python `hashlib`**：`shasum` 只有 macOS 有，Windows Git Bash 不存在。
- **修正 `tar` 选项语法**：`-czf` 与文件名之间缺空格会被解析成单个选项串。

修复前均已在本地用模拟产物复现验证，而非继续依赖 CI 试错。

## [1.7.0] - 2026-10-14

### 内容摘要（README TODO #4，本地实现）

- 新增 `summary` 配置块（默认 `enabled: false`）：开启后从**字幕文本**抽取式生成摘要，写入 NFO 的 `<outline>` 字段（Plex 的情节摘要字段，媒体库会显示在简介页）。
- **纯本地计算，字幕文本绝不外发**：使用 TF-IDF 句子相似度图 + 秩迭代的抽取式摘要，不引入任何网络调用或新依赖。
- 与弹幕词云同理放弃 LLM 依赖：外发字幕文本与本项目"资产保护 / 最小暴露"的核心取向冲突。`summary.mode` 预留了 `llm` 值，但当前**明确报错而非静默降级**——避免用户以为内容已发送而实际没有。
- 少于两句话时不做摘要（强行截取只是原文片段，不如让简介保持原样）；「一键三连」「欢迎收看」等订阅套话会被过滤。
- 优先读取当前媒体的**中文字幕**（`.zh-Hans.srt/.vtt/.ass`），无字幕时退回视频简介。
- 字幕读取严格限定当前任务的文件名前缀，不读取同目录其他资产的字幕——与弹幕转换的隔离策略一致。
- 多P视频**只为第一集生成摘要**：各集字幕是分集内容，逐集生成会得到近乎重复的 outline。
- **失败静默跳过**：摘要器异常、字幕缺失、内容过短都只打印提示，不影响视频下载与 NFO 写入的成功判定。

### 关注源图文（专栏）投稿同步

- 新增 `followings.article_types` 配置（默认 `off`）：`article` 只抓专栏，`all` 视频与专栏都抓。视频投稿始终随 `mode` 同步，此开关只控制额外的专栏请求——只想要视频的用户不会被打扰。
- `BiliParser.get_user_articles()` 拉取 UP 主专栏投稿列表（`x/space/article`），cv 号统一归一为正整数，无效条目跳过；正文仍由 `MetadataGenerator` 按 `read/cv{ cv }` 自行抓取。
- `FavScanner.scan_following_articles()` 沿用关注源既有语义：取关后本地资产保留不动，已归档专栏跳过并更新存活标记，不完整记录续跑。
- 专栏归档复用收藏夹管线的同一套逻辑（Markdown + NFO + 封面），**关键 NFO 写入失败时不写数据库完成状态**，下一轮重试。
- 新增测试 14 例，覆盖 cv 号归一、无效条目跳过、API 错误传播、已归档跳过、NFO 失败不写完成状态、全局下载上限、配置闸门默认值。

### 性能治理（万级资产实测优化）

基于 2 万资产的实测基准（`.mimosa/bench_perf.py`），而非猜测：

- **WebUI 资产列表 9.46ms → 0.11ms（87x）**：排序键从 `ORDER BY COALESCE(last_check, '') DESC` 改为 `ORDER BY last_check DESC`。二者语义一致（SQLite 中 DESC 排序本就把 NULL 放最后，有测试锁定），但 COALESCE 是表达式，索引无法用于排序；改后走覆盖索引不再需要临时 B-tree。
- **WebUI 计数 8.12ms → 0.68ms（12x）**：新增 `idx_assets_type` 覆盖索引。
- **合计 27.99ms → 14.03ms（2.0x）**。
- 新增索引在启动时自动创建，**位置在列迁移与旧行修复之后**——`last_verify` 是 v1.5.0 才补的列，提前建索引会在旧库上直接失败。
- **主动删除实测有害的索引**：早期为 `candidates_for_verify` 建的 `idx_assets_verify` 在三种 `last_verify` 分布下全部更慢（0% 填充 6.4→13.9ms、50% 5.7→18.1ms、100% 11.3→108.4ms）。原因是它的排序键 `ORDER BY last_verify IS NOT NULL` 同样是表达式，用不上索引，反而要为每个匹配行回表再排序。启动时检测到该索引会主动 `DROP`。
- 新增 `system.db_wal`（默认 `false`）：WAL 模式下写入不再被并发读阻塞（实测 5.5s → 15ms）。**默认关闭**是因为 WAL 需要在库同目录创建 `-wal`/`-shm`，只读挂载或部分网络盘会失败；启用失败时静默退回默认日志模式，不影响功能。已验证 WAL 下 WebUI 的 `mode=ro` 连接完全兼容。

### 弹幕词云（README TODO #5）

- 新增 `system` 无关的独立配置块 `wordcloud`：`enabled`（默认 `false`）+ `max_terms`（默认 60）。
- 开启后，视频下载完成时基于同目录 `.danmaku.xml` 生成 `.wordcloud.svg` 侧车，文件名沿用 ASS 侧车习惯（`X.danmaku.xml` → `X.danmaku.wordcloud.svg`）。
- **零新依赖**：不引入 wordcloud / jieba / matplotlib，SVG 由标准库拼装，规避位图字体在 Windows / macOS / Linux 上的渲染差异。
- **中文按字符二元组切分**而非词典分词：弹幕是极短高频口语，jieba 需要词典与模型文件，对这类噪声文本收益有限；二元组能自然捕获「前排」「泪目」「gg」等模式，且完全确定、无外部资源。
- 弹幕统计复用 `DanmakuConverter.parse_comment`（由私有 `_parse_comment` 提升为公开 API），保证词云与 ASS 转换看到完全同一批弹幕。
- 过滤应答类噪声（「哈哈哈」「awsl」「2333」）与虚词，同时**保留「前排」「打卡」等高频但有语义的词**——它们恰是词云最有价值的部分。
- **只生成不阻断**：词云是衍生品，XML 损坏、词数不足、渲染异常等任何失败都只打印提示，不影响视频下载与 NFO 写入的成功判定。
- SVG 内容来自用户可见弹幕文本，全部经 XML 转义，`<script>` 一类内容无法注入标签。
- 布局使用固定随机种子，同一份弹幕重复生成得到同样版式，便于回归比对。

### 跨平台自动发版

- 新增 `.github/workflows/release.yml`：推送 `vX.Y.Z` 标签即自动产出三平台免 Python 环境分发包与源码 ZIP，无需手工执行发版步骤。
- PyInstaller 不能交叉编译，因此 Windows / macOS(arm64) / Linux 各自在原生 runner 上并行构建，产物分别为 zip / tar.gz，并附 SHA256 校验文件。
- 每个平台构建后强制冒烟：执行 `--version` 并与 `app/__init__.py` 声明的版本号比对，不一致即失败——防止打出标着旧版本号的包。
- 产物完整性检查确认 `yt_dlp` / `bilibili_api` / `defusedxml` / `uvicorn` 均随包发出，单目录模式缺任一文件都会导致用户拿到坏包。
- 源码 ZIP 生成后审计条目，出现 `config.local.yaml`、`data/`、`downloads/`、`venv/` 或本地任务记录即失败。
- 三平台产物先上传为草稿，全部成功后才统一转为正式发布；任一平台失败都不会产生正式 Release。
- 随包附带 `config.yaml` / `LICENSE` / `README.md` 与中文安装说明，用户无需手工创建目录结构。

### 文档与社区基建

- 新增 `CONTRIBUTING.md`：说明本地验证命令、测试要求，以及五条不可逾越的架构边界（删除本地资产永不做、WebUI 不写数据库、不绕过输入校验、不隐式安装远程可执行文件、不提交凭据）。
- 新增 Issue 模板（表单式 YAML）：Bug 报告与功能建议各一套，含凭据脱敏提醒；关闭空白 Issue，安全类问题引导至私有漏洞报告。
- 新增 PR 模板：改动类型分类、影响面确认清单（删除路径 / 外部请求 / 凭据 / 数据库迁移）、验证记录、架构约束自查。
- 新增 `README.en.md` 英文版，与中文版章节一一对应；两份 README 顶部互相切换。
- `SECURITY.md` 支持版本范围更新至 `1.6.x`。

## [1.6.0] - 2026-10-13

### WebUI 可操作化

- WebUI 新增「操作」视图：可下发 `trigger_scan`（立即巡检）、`redownload_asset`（重下单个资产）、`restart`（提示重启核心）三条指令，并查看每条指令的执行回执。
- 新增本地命令通道 `commands.json`（数据目录，与 `runtime.json` 同级）：原子写入、幂等认领、有界审计历史（最多保留 50 条），复用既有解耦哲学，不引入 WebSocket，WebUI 始终不直接连接守护进程。
- 守护进程休眠改为可中断的分片轮询（默认 5 秒一片），"立即巡检"无需等待完整休眠周期即可唤醒；重下载请求在下一轮巡检命中该资产时生效。
- `restart` 不做自杀式重启：核心在当前轮次结束后安全退出并关闭数据库，由 systemd / Docker / supervisor 按自身策略重新拉起。
- 指令队列在每轮巡检开始前消费一次，保证重下载请求及时生效。

### 安全边界

- **删除本地资产不开放**：任何删除类指令都被 API 层与核心层双重拒绝，包括手工编辑 `commands.json` 注入的情况。
- 资产编号只接受规范的 `BV` / `av` 编号（正则白名单），拒绝任意字符串与文件路径，因此命令载荷无法用于路径穿越。
- 命令 `note` 与执行回执统一截断为单行 200 字符，避免注入多行内容污染审计日志。
- 配置了 Token 时，命令端点与其余管理 API 一样受 Bearer 鉴权保护。

### 测试

- 后端测试从 141 例增加到 197 例：新增 `tests/test_commands.py`（46 例）覆盖路径解析、队列语义、幂等认领、审计留痕、载荷校验与注入防护。
- `tests/test_webui_api.py` 新增 10 例覆盖命令端点：入队、状态查询、Token 鉴权、内存数据库不可用等。
- 休眠行为测试改为验证"总时长等于配置值且每片不超过轮询间隔"，贴合新的可中断休眠语义。

### 升级说明

- 新功能全部向后兼容，未配置任何开关：核心引擎启动后自动创建命令通道，无需修改 `config.yaml`。
- `commands.json` 与 `runtime.json` 一样位于数据库同级目录；若数据库使用 `:memory:`，命令通道自动不可用，WebUI「操作」视图会提示该限制。
- 使用 Docker Compose 部署时请注意：`restart` 指令会让核心容器退出，若未配置重启策略需要手动拉起。

## [1.5.0] - 2026-10-10

### 观看历史元数据同步

- 新增 `system.sync_watch_history` 开关（默认 `off`）：开启后把看过的视频**仅以元数据**（bvid、标题、UP 主、观看时间）记入本地 `watch_history` 表，不下载任何视频本体。
- 新增 `system.max_history_days`（默认 `90`）回溯窗口：历史按观看时间倒序翻页，触及窗口边界或已记录的最早条目即停止；首轮拉取窗口内的量，之后每轮只追增量。
- 无 `bvid` 的历史条目（直播、课程等）自动跳过。

### 完整性巡检

- 新增 `system.verify_integrity` 三档配置：`off`（默认，不校验）/ `light`（文件非空 + 媒体容器签名，纯字节读取）/ `full`（追加 `ffmpeg` 前 5 秒快速解码探测，需要 FFmpeg）。
- 每轮扫描抽样最多 20 个已完成资产：从未校验的优先，之后最久未校验优先；大库摊薄到多轮完成。
- 校验结论写入 `assets` 表新列 `integrity_status`（0 未校验 / 1 通过 / 2 损坏）与 `last_verify`，旧数据库打开时自动迁移，WebUI 资产页自动展示。
- **只标记，不删除**：损坏文件（含孤本）永久保留并标记"完整性异常"，是否重新下载由用户决定。

### 其他

- 播放列表同步与既有 `sync_collections` 合集同步收敛：两者使用同一 B 站 seasons/series API，不再提供重复入口。
- README 配置指南新增"功能开关与档位说明"与 PyInstaller 打包使用说明，面向新用户交付。

### 升级说明

- 三个新配置默认值均为关闭状态（`sync_watch_history: false`、`verify_integrity: "off"`），升级后行为不变，按需开启。
- 旧数据库首次启动时自动补列（`integrity_status`、`last_verify`），无需手工迁移。
- `verify_integrity: "full"` 依赖 FFmpeg；未安装时该项校验报错标记，不会中断扫描。

## [1.4.0] - 2026-10-10

### 关注 UP 主同步

- 新增 `followings.mode` 配置：`all` 全量同步登录账号的全部关注 UP 主投稿，`list` 按 UID 显式指定（无需关注关系，可用于监控任意 UP 主），默认 `off`。
- 关注源与收藏夹管线同构：失效投稿自动创建墓碑或触发孤本保护；已完整归档的记录跳过并更新存活时间；不完整记录自动续跑修复。
- 取关 UP 主后，本地已备份的资产默认保留不动，程序不实现任何远程或本地清除逻辑。
- 同步列表 API 统一走有限重试、指数退避与来源隔离；`list` 模式未配置名称时自动向 B 站补全 UP 主名称。

### 打包与分发

- 新增 PyInstaller 打包配置 `build.spec`：核心引擎可打包为单目录分发的免 Python 环境可执行文件（Windows 实测通过）。
- 修复打包运行时的路径错误：`main.py` 与 `login.py` 在 PyInstaller frozen 环境下改用可执行文件自身路径定位程序目录，源码模式行为不变。

### 安全加固

- 专栏图片下载新增 B 站 CDN 域名白名单，非白名单外链一律跳过，防止正文注入触发 SSRF。
- 新增 realpath + commonpath 路径包含检查（NFO 写入、专栏图片与 Markdown 落盘、封面复制），作为路径穿越的纵深防御。
- NFO 生成的 XML 美化改用 `defusedxml`，禁用实体展开。
- 数据库自动迁移列名增加合法性白名单校验；WebUI 只读数据库的 PRAGMA 参数强制整型化。

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

[Unreleased]: https://github.com/Stars4422335/BiliArchive-Pro/compare/v1.7.1...HEAD
[1.7.1]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.7.1
[1.7.0]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.7.0
[1.6.0]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.6.0
[1.5.0]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.5.0
[1.4.0]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.4.0
[1.3.0]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.3.0
[1.2.0]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.2.0
[1.1.3]: https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.1.3
