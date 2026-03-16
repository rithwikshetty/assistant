from __future__ import annotations

import json
import re
import socket
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_FRONTEND_PORT = 3000
DEFAULT_BACKEND_PORT = 8000
LOCALHOST = "127.0.0.1"
LOCALHOST_URL = "http://localhost"


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def get_runtime_state_path() -> Path:
    return get_repo_root() / ".tmp" / "dev-runtime.json"


def _normalize_service(service: str) -> str:
    normalized = str(service or "").strip().lower()
    if normalized not in {"frontend", "backend"}:
        raise ValueError(f"Unsupported runtime service: {service}")
    return normalized


def _load_runtime_state() -> dict[str, Any]:
    state_path = get_runtime_state_path()
    if not state_path.exists():
        return {"services": {}}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {"services": {}}
    services = payload.get("services")
    if not isinstance(services, dict):
        payload["services"] = {}
    return payload


def _save_runtime_state(state: dict[str, Any]) -> None:
    state_path = get_runtime_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def is_port_available(port: int, host: str = LOCALHOST) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, int(port)))
    except OSError:
        return False

    if host != "0.0.0.0":
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("0.0.0.0", int(port)))
        except OSError:
            return False
    return True


def find_available_port(start_port: int) -> int:
    port = max(1, int(start_port))
    while port <= 65535:
        if is_port_available(port):
            return port
        port += 1
    raise RuntimeError(f"Unable to find an available port starting at {start_port}")


def reserve_runtime_ports(primary_service: str) -> dict[str, dict[str, Any]]:
    normalized_primary = _normalize_service(primary_service)
    defaults = {
        "frontend": DEFAULT_FRONTEND_PORT,
        "backend": DEFAULT_BACKEND_PORT,
    }
    state = _load_runtime_state()
    services = state.setdefault("services", {})

    ordered_services = [normalized_primary] + [name for name in ("frontend", "backend") if name != normalized_primary]
    reserved_ports = {
        name: int(data.get("port"))
        for name, data in services.items()
        if isinstance(data, dict) and str(data.get("port", "")).isdigit()
    }

    for service in ordered_services:
        current_port = reserved_ports.get(service)
        if current_port and service != normalized_primary:
            chosen_port = current_port
        else:
            start_port = current_port if current_port else defaults[service]
            chosen_port = current_port if current_port and is_port_available(current_port) else find_available_port(start_port)
        reserved_ports[service] = chosen_port
        services[service] = {
            "port": chosen_port,
            "url": f"{LOCALHOST_URL}:{chosen_port}",
        }

    _save_runtime_state(state)
    return {service: dict(services[service]) for service in ("frontend", "backend")}


def get_reserved_service_url(service: str) -> str | None:
    normalized = _normalize_service(service)
    state = _load_runtime_state()
    service_data = state.get("services", {}).get(normalized)
    if not isinstance(service_data, dict):
        return None
    raw_url = str(service_data.get("url") or "").strip()
    return raw_url.rstrip("/") if raw_url else None


def _parse_compose_port_output(raw: str) -> int | None:
    match = re.search(r":(\d+)\s*$", str(raw or "").strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def discover_compose_host_port(service: str, container_port: int) -> int | None:
    repo_root = get_repo_root()
    compose_file = repo_root / "docker-compose.yml"
    command = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "port",
        service,
        str(container_port),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None

    if completed.returncode != 0:
        return None
    return _parse_compose_port_output(completed.stdout)


def build_dynamic_database_url() -> str | None:
    port = discover_compose_host_port("postgres", 5432)
    if port is None:
        return None
    return f"postgresql+psycopg://assistant:assistant@{LOCALHOST}:{port}/assistant"


def build_dynamic_redis_url() -> str | None:
    port = discover_compose_host_port("redis", 6379)
    if port is None:
        return None
    return f"redis://{LOCALHOST}:{port}/0"


def build_dynamic_sandbox_url() -> str | None:
    port = discover_compose_host_port("sandbox", 8100)
    if port is None:
        return None
    return f"http://{LOCALHOST}:{port}"
