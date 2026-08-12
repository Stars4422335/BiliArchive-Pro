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
        help="监听地址，默认 127.0.0.1",
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
        token=token,
        config_path=args.config,
    )
    uvicorn.run(app, host=args.host, port=args.port, access_log=True)


if __name__ == "__main__":
    main()
