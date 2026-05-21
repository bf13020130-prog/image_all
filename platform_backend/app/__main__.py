from __future__ import annotations

import uvicorn

from .config import CONFIG


if __name__ == "__main__":
    CONFIG.ensure_dirs()
    uvicorn.run(
        "platform_backend.app.main:app",
        host=CONFIG.server_host,
        port=CONFIG.server_port,
        reload=False,
    )
