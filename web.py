import argparse
import os
from pathlib import Path

import uvicorn

from app.webui import create_app

PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(description="启动 BiliArchive-Pro WebUI")
    parser.add_argument(
        "--host",
        default=os.environ.get("BILIARCHIVE_WEB_HOST", "127.0.0.1"),
        help="监听地址，默认 127.0.0.1；容器内通常需 0.0.0.0 供端口映射",
    )
    parser.add_argument(
        "--public-bind",
        default=os.environ.get("BILIARCHIVE_WEB_PUBLIC_BIND"),
        help=(
            "服务实际暴露给谁的地址；未提供时回落到 --host。"
            "非 loopback 暴露必须配置 BILIARCHIVE_WEB_TOKEN"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("BILIARCHIVE_WEB_PORT", "8000")),
        help="监听端口，默认 8000",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("BILIARCHIVE_CONFIG_PATH", str(PROJECT_ROOT / "config.yaml")),
        help="公共配置文件路径",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("端口必须在 1 到 65535 之间")

    token = os.environ.get("BILIARCHIVE_WEB_TOKEN")
    app = create_app(
        project_root=PROJECT_ROOT,
        host=args.host,
        public_bind=args.public_bind,
        token=token,
        config_path=args.config,
    )
    uvicorn.run(app, host=args.host, port=args.port, access_log=True)


if __name__ == "__main__":
    main()
