#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config.dev_runtime import (  # noqa: E402
    build_dynamic_database_url,
    build_dynamic_redis_url,
    build_dynamic_sandbox_url,
    reserve_runtime_ports,
)


def _format_shell_exports(values: dict[str, str]) -> str:
    return "\n".join(
        f"export {key}={shlex.quote(str(value))}"
        for key, value in values.items()
    )


def _reserve_command(service: str, output_format: str) -> int:
    payload = reserve_runtime_ports(service)
    if output_format == "json":
        print(json.dumps(payload))
        return 0

    shell_values = {
        "ASSISTANT_FRONTEND_PORT": str(payload["frontend"]["port"]),
        "ASSISTANT_FRONTEND_URL": payload["frontend"]["url"],
        "ASSISTANT_BACKEND_PORT": str(payload["backend"]["port"]),
        "ASSISTANT_BACKEND_URL": payload["backend"]["url"],
    }
    print(_format_shell_exports(shell_values))
    return 0


def _backend_env_command(output_format: str) -> int:
    runtime_ports = reserve_runtime_ports("backend")
    database_url = build_dynamic_database_url()
    redis_url = build_dynamic_redis_url()
    sandbox_url = build_dynamic_sandbox_url()

    missing = [
        label
        for label, value in (
            ("postgres", database_url),
            ("redis", redis_url),
            ("sandbox", sandbox_url),
        )
        if not value
    ]
    if missing:
        joined = ", ".join(missing)
        print(
            f"Unable to discover Docker host ports for {joined}. Start the local infra first with `docker compose up -d`.",
            file=sys.stderr,
        )
        return 1

    payload = {
        "UVICORN_HOST": "0.0.0.0",
        "UVICORN_PORT": str(runtime_ports["backend"]["port"]),
        "DATABASE_URL": database_url,
        "REDIS_URL": redis_url,
        "SANDBOX_URL": sandbox_url,
    }

    if output_format == "json":
        print(json.dumps(payload))
        return 0

    print(_format_shell_exports(payload))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Reserve dynamic local dev ports for assistant.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reserve_parser = subparsers.add_parser("reserve")
    reserve_parser.add_argument("service", choices=["frontend", "backend"])
    reserve_parser.add_argument("--format", choices=["json", "shell"], default="json")

    backend_env_parser = subparsers.add_parser("backend-env")
    backend_env_parser.add_argument("--format", choices=["json", "shell"], default="shell")

    args = parser.parse_args()

    if args.command == "reserve":
        return _reserve_command(args.service, args.format)
    if args.command == "backend-env":
        return _backend_env_command(args.format)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
