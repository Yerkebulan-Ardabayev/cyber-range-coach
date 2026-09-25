from __future__ import annotations

import asyncio
import json
import sys
from typing import cast

from .app import create_app
from .config import Settings


def doctor_settings(platform_name: str | None = None) -> Settings:
    settings = Settings()
    if (platform_name or sys.platform) == "win32" and settings.environment == "production":
        settings.lan_mode = True
        settings.tls_enabled = True
        settings.bind_host = "0.0.0.0"
    return settings


async def collect() -> dict[str, object]:
    app = create_app(doctor_settings())
    try:
        result = await app.state.preflight.run()
    finally:
        # No lifespan here: stop the WSL keep-alive the preflight may have started.
        await app.state.wsl_keepalive.close()
    return cast(dict[str, object], result.model_dump(mode="json"))


def main() -> None:
    print(json.dumps(asyncio.run(collect()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
