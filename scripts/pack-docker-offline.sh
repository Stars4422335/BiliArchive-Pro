#!/usr/bin/env bash
# 组装 BiliArchive-Pro NAS Docker 离线安装包。
#
# 用法（CI 的 assemble 阶段或本机）：
#   scripts/pack-docker-offline.sh <image-tar> <version-tag> <arch> <输出目录>
#   例: scripts/pack-docker-offline.sh biliarchive-pro-v1.9.0-amd64.tar v1.9.0 amd64 dist/offline
#
# 产物: <输出目录>/BiliArchive-Pro-docker-<arch>.tar.gz，内含
#   - 镜像 tar（保留 RepoTags，飞牛 GUI 导入 / 极空间 docker load 均可用）
#   - docker-compose.yml（离线专用：无 build 段、WebUI 为默认服务、相对路径挂载）
#   - .env.example / install.sh / NAS安装指南.md / SHA256SUMS
#
# 约束：绝不包含或触碰任何凭据与用户数据；脚本自身不联网。
set -euo pipefail

usage() {
    echo "用法: $0 <image-tar> <version-tag> <arch> <输出目录>" >&2
    exit 1
}

[[ $# -eq 4 ]] || usage

IMAGE_TAR=$1
VERSION_TAG=$2
ARCH=$3
OUT_DIR=$4

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
PKG_NAME="BiliArchive-Pro-docker-${ARCH}"

for required in "$IMAGE_TAR" "$REPO_ROOT/scripts/offline/docker-compose.yml" \
    "$REPO_ROOT/scripts/offline/NAS安装指南.md"; do
    [[ -f "$required" ]] || { echo "缺少必需文件: $required" >&2; exit 1; }
done

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$OUT_DIR" "$STAGE/$PKG_NAME"
PKG_DIR="$STAGE/$PKG_NAME"

# 1. 镜像 tar 原样放入（docker save 已保留 RepoTags）
cp "$IMAGE_TAR" "$PKG_DIR/"

# 2. 离线专用 compose 与文档；image 行按镜像 tar 内的实际 RepoTag 重写，
#    保证 docker load 后 compose 直接可用（CI 与本机构建的 tag 可能不同）
cp "$REPO_ROOT/scripts/offline/docker-compose.yml" "$STAGE/compose-template.yml"
# 直接从 tar 的 manifest.json 读取 RepoTags，无需真正 load 镜像
IMAGE_TAG=$(python - "$IMAGE_TAR" << 'PYEOF'
import json, sys, tarfile
with tarfile.open(sys.argv[1]) as tf:
    manifest = json.load(tf.extractfile("manifest.json"))
print(manifest[0]["RepoTags"][0])
PYEOF
)
sed "s|image: biliarchive-pro:local|image: ${IMAGE_TAG}|" \
    "$STAGE/compose-template.yml" > "$PKG_DIR/docker-compose.yml"
rm -f "$STAGE/compose-template.yml"
cp "$REPO_ROOT/scripts/offline/NAS安装指南.md" "$PKG_DIR/"
cp "$REPO_ROOT/config.yaml" "$PKG_DIR/config.yaml"

# 3. .env.example（引导用户配置 WebUI 绑定与 token）
cat > "$PKG_DIR/.env.example" << 'ENVEOF'
# BiliArchive-Pro WebUI 访问配置。复制本文件为 .env 后按需修改。
#
# WebUI 实际暴露给谁。默认只允许本机 (127.0.0.1) 访问，免 token。
# 如需局域网访问改为 0.0.0.0，此时【必须】设置下方 TOKEN。
BILIARCHIVE_WEB_BIND=127.0.0.1

# WebUI 端口（宿主机侧）
BILIARCHIVE_WEB_PORT=8000

# WebUI 访问令牌。绑定非 loopback 地址（如 0.0.0.0）时必填。
# 生成方式: python -c 'import secrets; print(secrets.token_urlsafe(32))'
BILIARCHIVE_WEB_TOKEN=

# 容器时区
TZ=Asia/Shanghai
ENVEOF

# 4. install.sh（可选快捷方式，供 SSH 用户；绝不触碰数据）
cat > "$PKG_DIR/install.sh" << 'INS_EOF'
#!/usr/bin/env bash
# BiliArchive-Pro 离线安装快捷脚本（可选）。
# 前提: NAS 已开启 SSH 且 docker/compose 可用（飞牛: sudo -i；极空间需 2024-10+ 固件）。
# 图形界面安装请看《NAS安装指南.md》，不依赖本脚本。
#
# 用法: bash install.sh
# 本脚本只做两件事: 导入镜像 + 提示启动命令；绝不删除或覆盖任何用户数据。
set -euo pipefail

cd "$(dirname "$0")"

IMAGE_TAR=$(find . -maxdepth 1 -name 'biliarchive-pro-*.tar' | head -n 1)
if [[ -z "$IMAGE_TAR" ]]; then
    echo "错误: 未找到镜像 tar 文件" >&2
    exit 1
fi

echo "[1/2] 导入镜像: $IMAGE_TAR"
docker load -i "$IMAGE_TAR"

echo "[2/2] 准备启动"
if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "已生成 .env，请按需修改 BILIARCHIVE_WEB_BIND / TOKEN 后再启动。"
fi
echo ""
echo "后续步骤（在本目录执行）:"
echo "  1. 编辑 .env 配置 WebUI 访问"
echo "  2. 检查 docker-compose.yml 中的相对路径挂载（./data ./downloads）"
echo "  3. 启动: docker compose --env-file .env up -d"
echo "  4. 查看日志: docker compose logs -f biliarchive"
echo ""
echo "卸载: docker compose --env-file .env down （不会删除 data/downloads 数据）"
INS_EOF
chmod +x "$PKG_DIR/install.sh"

# 5. SHA256SUMS（对包内所有文件计算，镜像 tar 最大故最后列出）
cd "$PKG_DIR"
find . -maxdepth 1 -type f ! -name 'SHA256SUMS' ! -name '*.tar' -print0 \
    | sort -z | xargs -0 sha256sum > SHA256SUMS
sha256sum "$(basename "$IMAGE_TAR")" >> SHA256SUMS
cd - > /dev/null

# 6. 打总包
tar -czf "$OUT_DIR/$PKG_NAME.tar.gz" -C "$STAGE" "$PKG_NAME"

echo "已生成: $OUT_DIR/$PKG_NAME.tar.gz"
sha256sum "$OUT_DIR/$PKG_NAME.tar.gz" > "$OUT_DIR/$PKG_NAME.tar.gz.sha256"
echo "校验文件: $OUT_DIR/$PKG_NAME.tar.gz.sha256"
