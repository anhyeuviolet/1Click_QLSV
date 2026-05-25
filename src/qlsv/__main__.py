"""`python -m qlsv` entrypoint.

Boots uvicorn against the FastAPI app produced by `create_app(load_config())`.
On config error: prints the Vietnamese error to stderr and exits 1 (D-03, D-09, D-10).
"""
from __future__ import annotations

import os
import sys

import uvicorn

from qlsv import __version__
from qlsv.app import create_app
from qlsv.config import CONFIGFILE, ConfigError, load_config


def main() -> None:
    # Test affordance — production path uses /root/.quanlyserver.json (D-13).
    path = os.environ.get("QLSV_CONFIG_PATH", CONFIGFILE)

    try:
        config = load_config(path)
    except ConfigError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    app = create_app(config)

    web = config.get("web", {})
    bind_addr = web.get("bind_addr", "0.0.0.0")
    port = int(web.get("port", 8080))

    # Vietnamese startup banner (D-09, D-10). journalctl handles UTF-8.
    print(f"Quản lý server v{__version__} - lắng nghe trên http://{bind_addr}:{port}")

    uvicorn.run(app, host=bind_addr, port=port, log_level="info")


if __name__ == "__main__":
    main()
