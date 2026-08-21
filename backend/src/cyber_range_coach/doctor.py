from __future__ import annotations

import asyncio
import json
from typing import cast

from .app import create_app


async def collect() -> dict[str, object]:
    app = create_app()
    result = await app.state.preflight.run()
    return cast(dict[str, object], result.model_dump(mode="json"))


def main() -> None:
    print(json.dumps(asyncio.run(collect()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
