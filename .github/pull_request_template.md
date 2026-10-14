## 这个 PR 做了什么

<!-- 一两句话说明改动动机与效果。关联 Issue 请写 Closes #123 -->

## 改动类型

- [ ] 缺陷修复（不改变既有归档行为）
- [ ] 新增功能（不改变既有归档行为）
- [ ] 行为变更（会影响既有归档或删除逻辑，请重点说明）
- [ ] 文档 / 社区基建
- [ ] 构建与依赖
- [ ] 重构（无功能变化）

## 影响面确认

- [ ] **不新增任何删除本地资产的路径**（本项目的硬性边界，删除操作只能由用户在终端手工执行）
- [ ] 不引入新的外部网络请求，或已在描述中说明请求目标与用途
- [ ] 不把凭据、数据库内容、`config.local.yaml`、`data/` 或下载内容写入仓库
- [ ] 数据库结构有变更时，提供了向后兼容的迁移（启动时自动补列，而非要求用户手工处理）

## 验证记录

<!-- 请贴出实际执行的命令与结果。未执行请勾选下面的"未验证"并说明原因 -->

- [ ] `python -m pytest tests -q` —— 结果：
- [ ] `python -m compileall -q main.py login.py web.py app`
- [ ] `cd webui && npm run lint && npm run build`
- [ ] 涉及 Dockerfile 或依赖变更：`docker build -t biliarchive-pro:local .`
- [ ] 本次为纯文档改动，未运行上述验证

## 架构约束自查

对照 [DEVELOPER_GUIDE.md](../DEVELOPER_GUIDE.md) 确认：

- [ ] 数据库始终以 `mode=ro` 只读方式被 WebUI 访问
- [ ] WebUI 只写入 `app/webui/service.py` 中声明的公开白名单
- [ ] 新增的外部输入都做了长度、类型与取值校验
- [ ] 写入用户目录的路径都经过 `path_manager` 的路径预算与规范化处理
- [ ] 未引入 WebSocket 或新的进程间通信方式（运维指令走 `commands.json` 文件通道）

## 截图 / 日志

<!-- 前端改动请附截图；后端问题请附脱敏后的日志片段 -->