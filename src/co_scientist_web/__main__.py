import argparse
from pathlib import Path

import uvicorn

from co_scientist import __version__

from .app import create_app
from .diagnostics import Diagnostics, configure_libraries


def main():
    parser = argparse.ArgumentParser(description=f"Local Co-Scientist DEV Workbench {__version__}")
    parser.add_argument("--data-dir", type=Path, default=Path(".co-scientist-workbench"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO",
                        help="Safe console/file diagnostics (default INFO; DEBUG includes read APIs)")
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Enable LIVE interface; still requires explicit per-Run approval",
    )
    args = parser.parse_args()
    observer = Diagnostics(args.data_dir / "logs/workbench.jsonl", level=args.log_level)
    configure_libraries(observer)
    observer.emit("web.start_requested", phase="startup", port=args.port, live_enabled=args.allow_live)
    try:
        uvicorn.run(
            create_app(args.data_dir, allow_live=args.allow_live, log_level=args.log_level,
                       observer=observer),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
            log_level=args.log_level.lower(),
            log_config=None,
        )
    except (Exception, SystemExit) as error:  # noqa: BLE001 -- redact CLI failure boundary
        observer.error(error, phase="web_server", code="WEB_SERVER_STOPPED_WITH_ERROR")
        raise SystemExit(1) from None
    finally:
        observer.emit("web.stopped", phase="shutdown")
        observer.close()


if __name__ == "__main__":
    main()
