"""Find the offline server on the LAN.

Server: answers UDP broadcast "MYTECH_DISCOVER" on DISCOVERY_UDP_PORT and
publishes an mDNS service "_mytech._tcp.local.". Clients that cannot use
either (e.g. a browser) type the server IP manually.

Client (desktop apps, tools/find_server.py): `discover()` broadcasts and
collects the answers.
"""
from __future__ import annotations

import json
import logging
import socket
import threading

from app.core.config import get_settings

MAGIC = b"MYTECH_DISCOVER"
SERVICE_TYPE = "_mytech._tcp.local."
log = logging.getLogger("mytech.discovery")


def server_info() -> dict:
    s = get_settings()
    return {"product": s.app_name, "version": s.version, "host": socket.gethostname(), "port": s.http_port,
            "scheme": "https" if s.ssl_certfile else "http", "api": "/api/v1"}


class UdpResponder:
    def __init__(self, port: int | None = None) -> None:
        self.port = port if port is not None else get_settings().discovery_udp_port
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("", self.port))
        self.port = self._sock.getsockname()[1]
        self._sock.settimeout(1.0)
        self._thread = threading.Thread(target=self._run, name="udp-discovery", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                break
            if data.startswith(MAGIC):
                info = server_info()
                info["address"] = _local_ip_for(addr[0])
                try:
                    self._sock.sendto(json.dumps(info).encode(), addr)
                except OSError:
                    pass

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            self._sock.close()
        if self._thread:
            self._thread.join(timeout=3)


def _local_ip_for(peer: str) -> str:
    """The server address the peer can reach (route-based, no packets sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((peer, 9))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return socket.gethostbyname(socket.gethostname())


class MdnsAdvertiser:
    def __init__(self) -> None:
        self._zc = None
        self._info = None

    def start(self) -> None:
        from zeroconf import ServiceInfo, Zeroconf

        info = server_info()
        ip = _local_ip_for("8.8.8.8")
        self._info = ServiceInfo(SERVICE_TYPE, f"MYTech Server {info['host']}.{SERVICE_TYPE}",
                                 addresses=[socket.inet_aton(ip)], port=info["port"],
                                 properties={"version": info["version"], "scheme": info["scheme"], "api": info["api"]},
                                 server=f"{info['host']}.local.")
        self._zc = Zeroconf()
        self._zc.register_service(self._info)

    def stop(self) -> None:
        if self._zc:
            try:
                self._zc.unregister_service(self._info)
            finally:
                self._zc.close()


def discover(timeout: float = 2.0, port: int | None = None, target: str = "<broadcast>") -> list[dict]:
    port = port or get_settings().discovery_udp_port
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    sock.sendto(MAGIC, (target, port))
    found = []
    try:
        while True:
            data, addr = sock.recvfrom(2048)
            try:
                info = json.loads(data)
            except ValueError:
                continue
            info.setdefault("address", addr[0])
            found.append(info)
    except socket.timeout:
        pass
    finally:
        sock.close()
    return found
