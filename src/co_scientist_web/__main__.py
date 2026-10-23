import argparse
from pathlib import Path

import uvicorn

from co_scientist import __version__

from .app import create_app


def main():
    parser = argparse.ArgumentParser(description=f"Local Co-Scientist DEV Workbench {__version__}")
    parser.add_argument("--data-dir", type=Path, default=Path(".co-scientist-workbench"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Enable LIVE interface; still requires explicit per-Run approval",
    )
    args = parser.parse_args()
    uvicorn.run(
        create_app(args.data_dir, allow_live=args.allow_live),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
