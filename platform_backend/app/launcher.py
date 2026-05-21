from __future__ import annotations

import socket
import threading
from collections.abc import Iterable

import uvicorn

from .config import CONFIG
from .database import init_db
from .worker import run_forever


def _lan_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if _is_lan_address(address):
                addresses.add(address)
    except OSError:
        pass

    if not addresses:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("10.255.255.255", 1))
                address = sock.getsockname()[0]
                if _is_lan_address(address):
                    addresses.add(address)
        except OSError:
            pass

    return sorted(addresses)


def _is_lan_address(address: str) -> bool:
    if (
        address.startswith("127.")
        or address.startswith("169.254.")
        or address == "0.0.0.0"
    ):
        return False
    # Avoid common virtual adapter ranges that usually cannot be reached from
    # another phone/PC on the same office or home Wi-Fi.
    if address.startswith(("172.16.", "172.17.", "172.18.", "172.19.")):
        return False
    return True


def _can_bind(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
        return True
    except OSError:
        return False


def _select_port(host: str, preferred_port: int) -> int:
    for port in range(preferred_port, preferred_port + 50):
        if _can_bind(host, port):
            return port
    raise RuntimeError(f"No free port found from {preferred_port} to {preferred_port + 49}.")


def _url(host: str, port: int, path: str = "") -> str:
    return f"http://{host}:{port}{path}"


def _print_urls(lan_addresses: Iterable[str], port: int) -> None:
    print("Starting Design Output Web Platform...", flush=True)
    if port != CONFIG.server_port:
        print(f"Port {CONFIG.server_port} is busy, using {port} instead.", flush=True)
    print(f"User:  {_url('127.0.0.1', port, '/user/')}", flush=True)
    print(f"Admin: {_url('127.0.0.1', port, '/admin/')}", flush=True)
    print(f"API docs: {_url('127.0.0.1', port, '/docs')}", flush=True)
    for address in lan_addresses:
        print(f"LAN user:  {_url(address, port, '/user/')}", flush=True)
        print(f"LAN admin: {_url(address, port, '/admin/')}", flush=True)
    if not lan_addresses:
        print("LAN address: not detected. Check ipconfig if another device needs access.", flush=True)
    print("", flush=True)
    print("Close this window or press Ctrl+C to stop backend and worker.", flush=True)
    print("", flush=True)
    print(f"Starting backend at http://{CONFIG.server_host}:{port}", flush=True)
    print("Starting worker in the same window.", flush=True)
    print("", flush=True)


def main() -> int:
    CONFIG.ensure_dirs()
    init_db()
    port = _select_port(CONFIG.server_host, CONFIG.server_port)
    stop_event = threading.Event()
    worker_thread = threading.Thread(
        target=run_forever,
        args=(stop_event,),
        kwargs={"initialize": False},
        name="platform-worker",
        daemon=True,
    )
    _print_urls(_lan_addresses(), port)
    worker_thread.start()

    server = uvicorn.Server(
        uvicorn.Config(
            "platform_backend.app.main:app",
            host=CONFIG.server_host,
            port=port,
            reload=False,
            use_colors=False,
        )
    )
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        stop_event.set()
        worker_thread.join(timeout=5)
        print("", flush=True)
        print("Stopped backend and worker.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
