"""FastAPI application factory for the BiliArchive-Pro WebUI."""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from app import __version__

from .service import (
    ConfigValidationError,
    RevisionConflict,
    WebService,
    is_loopback_host,
)


def create_app(
    project_root: os.PathLike[str] | str | None = None,
    *,
    host: str = "127.0.0.1",
    token: str | None = None,
    config_path: os.PathLike[str] | str | None = None,
    db_path: os.PathLike[str] | str | None = None,
    static_dir: os.PathLike[str] | str | None = None,
) -> FastAPI:
    """Create the API and optionally serve the built frontend.

    A token is mandatory before binding to a non-loopback address. When a
    token is configured, only ``/api/health`` remains unauthenticated.
    """
    token = token.strip() if isinstance(token, str) else token
    token = token or None
    if not is_loopback_host(host) and not token:
        raise ValueError("非 loopback 地址必须配置 WebUI token")
    root = Path(project_root or os.getcwd()).resolve()
    resolved_config = Path(config_path or root / "config.yaml").resolve()
    resolved_static = Path(static_dir or root / "webui" / "dist").resolve()
    service = WebService(
        project_root=root,
        config_path=resolved_config,
        db_path=Path(db_path) if db_path else None,
        version=__version__,
    )
    app = FastAPI(title="BiliArchive-Pro WebUI API")
    app.state.web_service = service

    def request_is_authenticated(request: Request) -> bool:
        if token is None:
            return True
        scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
        return (
            scheme.lower() == "bearer"
            and bool(supplied)
            and hmac.compare_digest(supplied, token)
        )

    @app.middleware("http")
    async def api_authentication(request: Request, call_next):
        if token is not None and request.url.path.startswith("/api/") and request.url.path != "/api/health":
            if not request_is_authenticated(request):
                return JSONResponse(
                    {"detail": "需要 Bearer token"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, str | bool]:
        return {
            "status": "ok",
            "auth_required": token is not None,
            "authenticated": request_is_authenticated(request),
        }

    @app.get("/api/dashboard")
    async def dashboard() -> dict:
        try:
            return service.dashboard()
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="数据库不可读") from exc

    @app.get("/api/assets")
    async def assets(
        query: str | None = Query(default=None),
        q: str | None = Query(default=None),
        status: str | int | None = Query(default=None),
        type: str | None = Query(default=None),
        page: int = Query(default=1),
        page_size: int = Query(default=20),
    ) -> dict:
        try:
            return service.assets(
                query=query or q,
                status=status,
                asset_type=type,
                page=page,
                page_size=page_size,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="数据库不可读") from exc

    @app.get("/api/assets/{asset_id}/poster")
    async def poster(asset_id: str) -> FileResponse:
        path = service.poster_path(asset_id)
        if path is None:
            raise HTTPException(status_code=404, detail="poster 不存在")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/config")
    async def get_config() -> dict:
        try:
            return service.config_response()
        except (ConfigValidationError, OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.put("/api/config")
    async def put_config(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
        if "config" in body:
            if set(body) != {"revision", "config"} or not isinstance(body["config"], dict):
                raise HTTPException(status_code=422, detail="请求体必须包含 revision 和 config")
            revision = body.get("revision")
            incoming = body["config"]
        else:
            revision = body.pop("revision", None)
            incoming = body
        if not isinstance(revision, str) or not revision:
            raise HTTPException(status_code=422, detail="缺少有效 revision")
        try:
            result = service.write_config(incoming, revision)
            return JSONResponse(result)
        except RevisionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail="配置已被其他进程修改",
                headers={"X-Config-Revision": exc.revision},
            ) from exc
        except ConfigValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    if resolved_static.is_dir():
        @app.get("/{path:path}")
        async def static_or_spa(path: str) -> FileResponse:
            candidate = (resolved_static / path).resolve()
            if candidate.is_relative_to(resolved_static) and candidate.is_file():
                return FileResponse(candidate)
            index = resolved_static / "index.html"
            if index.is_file():
                return FileResponse(index)
            raise HTTPException(status_code=404, detail="资源不存在")

    return app


__all__ = ["create_app"]
