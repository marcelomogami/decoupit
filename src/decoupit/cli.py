"""Command line entry point for DecoupIt."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("a porta deve estar entre 1 e 65535")
    return port


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="decoupit", description="Inicia a aplicação local DecoupIt."
    )
    parser.add_argument("--port", type=_port, default=8000)
    arguments = parser.parse_args(argv)
    uvicorn.run(
        "decoupit.web:create_app",
        factory=True,
        host="127.0.0.1",
        port=arguments.port,
    )


if __name__ == "__main__":
    main()
