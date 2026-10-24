"""Run the API server with the settings from .env (port, optional TLS)."""
from __future__ import annotations

import uvicorn

from app.core.config import get_settings


def serve() -> None:
    s = get_settings()
    kwargs = {}
    if s.ssl_certfile and s.ssl_keyfile:
        kwargs.update(ssl_certfile=s.ssl_certfile, ssl_keyfile=s.ssl_keyfile)
    uvicorn.run("app.main:app", host="0.0.0.0", port=s.http_port, proxy_headers=True, forwarded_allow_ips="127.0.0.1",
                log_config=None, **kwargs)


if __name__ == "__main__":
    serve()
