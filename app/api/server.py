from __future__ import annotations

import os

import uvicorn

from app.api.main import app


def run() -> None:
    host = os.getenv("DISCO_NOTES_HOST", "127.0.0.1")
    port = int(os.getenv("DISCO_NOTES_PORT", "8765"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
