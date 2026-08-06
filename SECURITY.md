# 安全策略

## 支持范围

安全修复优先应用于最新的 `1.1.x` 版本。旧版本用户应先升级到最新 Release 再复现问题。

## 报告安全问题

请优先通过 GitHub 的私有漏洞报告或 Security Advisory 草稿报告安全问题。不要在公开 Issue 中粘贴 Cookie、数据库、日志中的认证信息或可直接复现账号访问的材料。

报告应包含受影响版本、运行平台、最小复现步骤、预期影响和已完成的脱敏处理。

## 凭据处理

- `data/cookie.json` 和运行时生成的 Netscape Cookie 都是明文凭据，不属于加密存储。
- 程序采用原子写入并在支持的平台上尽力限制文件权限；宿主目录 ACL 仍由用户负责。
- 每个下载任务使用独立的 Netscape Cookie 临时文件，Cookie 标记为 Secure，并在任务结束后按所有权清理。
- 携带 Cookie 的视频下载只允许使用 HTTPS URL。
- 不得把 `data/`、`config.local.yaml`、`.env` 或本地任务记录加入 Git、Docker 镜像、ZIP、EXE 或 App 包。
- 若凭据曾进入公开仓库、共享镜像或发布包，应立即重新登录并删除受影响产物。

## 组件更新

- 下载流程不会隐式安装远程可执行文件。
- `yt-dlp` 只有在启动组件检查且策略为 `auto` 时才会自动更新。
- 代理仅用于下载组件本体；SHA256 校验文件从 GitHub 官方地址直连获取。缺少校验值或摘要不匹配时拒绝替换现有文件。

## Docker 构建边界

Dockerfile 只复制明确列出的运行文件，`.dockerignore` 额外排除本地状态。修改 Dockerfile 时不得恢复 `COPY . .`。
