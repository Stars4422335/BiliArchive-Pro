"""FastAPI application factory for the BiliArchive-Pro WebUI."""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from app import __version__
from app.core.commands import CommandError

from .auth_store import AuthStore, PasswordPolicyError
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
    public_bind: str | None = None,
    token: str | None = None,
    config_path: os.PathLike[str] | str | None = None,
    db_path: os.PathLike[str] | str | None = None,
    static_dir: os.PathLike[str] | str | None = None,
) -> FastAPI:
    """Create the API and optionally serve the built frontend.

    ``host`` is the address uvicorn listens on; ``public_bind`` describes
    where the service is actually reachable from. A token is mandatory only
    when ``public_bind`` is a non-loopback address — this distinction is what
    lets the container listen on ``0.0.0.0`` (a technical requirement for
    Docker port mapping) while still publishing to the host loopback only.
    When a token is configured, only ``/api/health`` remains unauthenticated.
    """
    token = token.strip() if isinstance(token, str) else token
    token = token or None
    effective_bind = public_bind if public_bind is not None else host
    if not is_loopback_host(effective_bind) and not token:
        raise ValueError(
            "非 loopback 地址必须配置 WebUI token"
            "（--public-bind 描述实际暴露范围，--host 仅是监听地址）"
        )
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

    # Password credential store; when the data directory is read-only or the
    # file cannot be created we fall back to "env token only" semantics so
    # existing deployments keep booting.
    auth_store: AuthStore | None = None
    if token is not None:
        try:
            auth_store = AuthStore(root / "data" / "webui_auth.json")
        except (OSError, ValueError) as exc:
            print(f"[!] WebUI 密码存储不可用，退回环境令牌认证: {exc}")
            auth_store = None
    app.state.auth_store = auth_store

    def bearer_token(request: Request) -> str | None:
        scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not supplied:
            return None
        return supplied

    def request_is_authenticated(request: Request) -> bool:
        supplied = bearer_token(request)
        if not supplied:
            return token is None
        if token is not None and hmac.compare_digest(supplied, token):
            return True
        if auth_store is not None and auth_store.session_is_valid(supplied):
            return True
        return False

    @app.middleware("http")
    async def api_authentication(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.url.path not in {
            "/api/health",
            "/api/auth/login",
        }:
            if not request_is_authenticated(request):
                return JSONResponse(
                    {"detail": "需要登录凭据"},
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
            "force_change": bool(auth_store is not None and auth_store.force_change),
        }

    @app.post("/api/auth/login")
    async def auth_login(request: Request) -> JSONResponse:
        body_ok = True
        try:
            body = await request.json()
        except ValueError:
            body_ok = False
            body = {}
        if not body_ok or not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
        password = body.get("password")
        env_token = body.get("token")
        if not isinstance(password, str) or not password:
            if not isinstance(env_token, str) or not env_token:
                raise HTTPException(status_code=422, detail="缺少 password 或 token")
        if auth_store is None:
            # Degraded mode: only the environment token authenticates.
            if token is not None and isinstance(env_token, str) and hmac.compare_digest(env_token, token):
                return JSONResponse({"session": env_token, "force_change": False})
            raise HTTPException(status_code=401, detail="密码认证不可用，请使用环境令牌")
        matched = False
        if isinstance(password, str) and password:
            matched = auth_store.verify_bootstrap_or_password(password)
        elif isinstance(env_token, str) and token is not None and hmac.compare_digest(env_token, token):
            matched = True
        if not matched:
            raise HTTPException(status_code=401, detail="密码或令牌不正确")
        session = auth_store.issue_session()
        return JSONResponse({"session": session, "force_change": auth_store.force_change})

    @app.post("/api/auth/change-password")
    async def auth_change_password(request: Request) -> JSONResponse:
        if auth_store is None:
            raise HTTPException(status_code=503, detail="密码认证不可用")
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
        old_password = body.get("old_password")
        new_password = body.get("new_password")
        if not isinstance(old_password, str) or not isinstance(new_password, str):
            raise HTTPException(status_code=422, detail="缺少 old_password 或 new_password")
        try:
            session = auth_store.change_password(old_password, new_password)
        except PasswordPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse({"session": session, "force_change": auth_store.force_change})

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request) -> dict[str, bool]:
        supplied = bearer_token(request)
        if supplied and auth_store is not None:
            auth_store.revoke_session(supplied)
        return {"ok": True}

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
        source: str | None = Query(default=None),
        page: int = Query(default=1),
        page_size: int = Query(default=20),
        cursor: str | None = Query(default=None),
    ) -> dict:
        try:
            return service.assets(
                query=query or q,
                status=status,
                asset_type=type,
                source=source,
                page=page,
                page_size=page_size,
                cursor=cursor,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="数据库不可读") from exc

    @app.get("/api/assets/sources")
    async def asset_sources() -> dict:
        """来源（收藏夹/合集/稍后再看/UP 主）列表，供资产页筛选下拉。"""
        try:
            return {"sources": service.distinct_sources()}
        except Exception as exc:
            raise HTTPException(status_code=503, detail="数据库不可读") from exc

    @app.get("/api/discover/favorites")
    async def discover_favorites() -> dict:
        try:
            return await service.discover_favorites()
        except CommandError as exc:
            raise HTTPException(
                status_code=getattr(exc, "status", 503), detail=str(exc)
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"自动发现失败: {exc}") from exc

    @app.get("/api/discover/collections")
    async def discover_collections(mid: int | None = Query(default=None)) -> dict:
        try:
            return await service.discover_collections(mid)
        except CommandError as exc:
            raise HTTPException(
                status_code=getattr(exc, "status", 503), detail=str(exc)
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"自动发现失败: {exc}") from exc

    @app.post("/api/login/qrcode")
    async def login_qrcode_create() -> dict:
        """申请一个新的扫码登录二维码（data URL 形式的 PNG）。"""
        try:
            return await service.login_qrcode_create()
        except CommandError as exc:
            raise HTTPException(
                status_code=getattr(exc, "status", 503), detail=str(exc)
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"二维码申请失败: {exc}") from exc

    @app.get("/api/login/qrcode/{key}")
    async def login_qrcode_poll(key: str) -> dict:
        """查询一次扫码状态；登录完成时后端写入凭据。"""
        try:
            return await service.login_qrcode_poll(key)
        except CommandError as exc:
            raise HTTPException(
                status_code=getattr(exc, "status", 503), detail=str(exc)
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"状态查询失败: {exc}") from exc

    @app.get("/api/login/status")
    async def login_status() -> dict:
        try:
            return await service.login_status()
        except CommandError as exc:
            raise HTTPException(
                status_code=getattr(exc, "status", 503), detail=str(exc)
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"状态检测失败: {exc}") from exc

    @app.post("/api/quality/audit")
    async def quality_audit() -> dict:
        """清晰度审计：对比本地与源端可用清晰度，只产出证据清单。"""
        try:
            return await service.run_quality_audit()
        except CommandError as exc:
            raise HTTPException(
                status_code=getattr(exc, "status", 503), detail=str(exc)
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"审计失败: {exc}") from exc

    @app.get("/api/assets/{asset_id}/poster")
    async def poster(asset_id: str) -> FileResponse:
        path = service.poster_path(asset_id)
        if path is None:
            raise HTTPException(status_code=404, detail="poster 不存在")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/assets/{asset_id}/wordcloud")
    async def wordcloud(asset_id: str) -> FileResponse:
        path = service.wordcloud_path(asset_id)
        if path is None:
            raise HTTPException(status_code=404, detail="词云不存在")
        return FileResponse(path, media_type="image/svg+xml")

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

    @app.get("/api/commands")
    async def list_commands() -> dict:
        """Expose the supported command set, the queue and the audit trail."""
        try:
            return service.command_snapshot()
        except CommandError as exc:
            raise HTTPException(
                status_code=getattr(exc, "status", 503), detail=str(exc)
            ) from exc

    @app.post("/api/commands")
    async def submit_command(request: Request) -> JSONResponse:
        """Queue one command for the daemon to pick up on its next poll.

        Deliberately narrow: this endpoint can never delete local media.
        """
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象") from exc
        try:
            record = service.submit_command(body)
        except CommandError as exc:
            raise HTTPException(
                status_code=getattr(exc, "status", 422), detail=str(exc)
            ) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JSONResponse(record, status_code=202)

    @app.get("/api/commands/{command_id}")
    async def command_status(command_id: str) -> dict:
        """Poll one command's acknowledgement state."""
        try:
            return service.command_status(command_id)
        except CommandError as exc:
            raise HTTPException(
                status_code=getattr(exc, "status", 404), detail=str(exc)
            ) from exc
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
