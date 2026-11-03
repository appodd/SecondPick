from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from shopping_agent.web.app import create_app


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local research workbench.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", type=Path, default=Path("config/default.toml"))
    parser.add_argument("--settings", type=Path, default=Path("data/settings.json"))
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.host not in LOOPBACK_HOSTS:
        parser.error("--host must be a loopback host: 127.0.0.1, localhost, or ::1")
    uvicorn.run(
        create_app(args.config, args.settings),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
