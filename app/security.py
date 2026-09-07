import base64
import hmac
import os
from fastapi import Request
from starlette.responses import Response, RedirectResponse, PlainTextResponse

PUBLIC_PATHS = ("/api/health", "/static/")


def authenticate(request: Request) -> Response | None:
    if os.getenv("WEB_AUTH_REQUIRED", "false").lower() != "true":
        return None
    if any(request.url.path == path or request.url.path.startswith(path) for path in PUBLIC_PATHS):
        return None
    store = request.app.state.secure_settings
    if request.url.path in ("/setup", "/api/setup") and not store.is_complete():
        return None
    if not store.is_complete():
        return RedirectResponse("/setup", status_code=303)
    authorization = request.headers.get("authorization", "")
    api_secret = os.getenv("API_SECRET") or store.get("API_SECRET")
    if api_secret and authorization.startswith("Bearer ") and hmac.compare_digest(authorization[7:], str(api_secret)):
        return None
    if authorization.startswith("Basic "):
        try:
            username, password = base64.b64decode(authorization[6:]).decode().split(":", 1)
            if hmac.compare_digest(username, str(store.get("WEB_USERNAME", "admin"))) and store.verify_password(password):
                return None
        except (ValueError, UnicodeDecodeError):
            pass
    return PlainTextResponse("需要 Dashboard 用户名和密码", 401, {"WWW-Authenticate": 'Basic realm="Stock Agent"'})
