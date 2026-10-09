"""SSDP discovery: find DLNA devices on the LAN, and advertise our server."""

from __future__ import annotations

import logging
import socket
import threading
import time

from pydlna.client import DLNAClient

logger = logging.getLogger(__name__)

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900

MEDIA_SERVER = "urn:schemas-upnp-org:device:MediaServer:1"
MEDIA_RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"

_SERVER_HEADER = "PyDLNA/0.1 UPnP/1.0 DLNADOC/1.50"


class DeviceList(list):
    """The result of a discovery run; usable as a context manager.

    ``with DLNADiscovery().discover() as devices:`` works purely for
    symmetry with the server/controller — there is nothing to close.
    """

    def __enter__(self) -> "DeviceList":
        return self

    def __exit__(self, *exc: object) -> None:
        pass


class DLNADiscovery:
    """Finds DLNA/UPnP devices on the local network via SSDP M-SEARCH."""

    def __init__(self, st: str = "ssdp:all") -> None:
        self.st = st
        self.clients: list[DLNAClient] = []

    def discover(self, timeout: float = 3.0, resolve_names: bool = True) -> list[DLNAClient]:
        """Send an M-SEARCH multicast and collect the devices that answer."""
        request = _msearch(self.st, mx=max(1, min(int(timeout), 5)))
        found: dict[str, DLNAClient] = {}
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.settimeout(0.2)
            sock.sendto(request.encode("ascii"), (SSDP_ADDR, SSDP_PORT))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    data, address = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                headers = _parse_headers(data.decode("latin-1"))
                usn = headers.get("usn") or headers.get("location", "")
                # A device announces once per ST as "udn::nt"; dedupe on the UDN.
                key = usn.split("::")[0]
                if not key or key in found:
                    continue
                found[key] = DLNAClient.from_ssdp(address[0], headers)
        finally:
            sock.close()
        self.clients = DeviceList(found.values())
        if resolve_names:
            for client in self.clients:
                client.fetch_description(timeout=1.5)  # best effort
        return self.clients


class SSDPResponder(threading.Thread):
    """Answers M-SEARCH requests and multicasts alive/byebye notifications."""

    def __init__(self, udn: str, location: str, interval: float = 60.0) -> None:
        super().__init__(name="pydlna-ssdp", daemon=True)
        self.udn = udn
        self.location = location
        self.interval = interval
        self._stop_event = threading.Event()

    @property
    def targets(self) -> list[tuple[str, str]]:
        """Every ``(NT, USN)`` pair this device advertises."""
        content_directory = "urn:schemas-upnp-org:service:ContentDirectory:1"
        connection_manager = "urn:schemas-upnp-org:service:ConnectionManager:1"
        return [
            ("upnp:rootdevice", f"{self.udn}::upnp:rootdevice"),
            (self.udn, self.udn),
            (MEDIA_SERVER, f"{self.udn}::{MEDIA_SERVER}"),
            (content_directory, f"{self.udn}::{content_directory}"),
            (connection_manager, f"{self.udn}::{connection_manager}"),
        ]

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", SSDP_PORT))
            membership = socket.inet_aton(SSDP_ADDR) + socket.inet_aton("0.0.0.0")
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
            sock.settimeout(1.0)
        except OSError as exc:
            logger.warning("SSDP responder disabled: %s", exc)
            sock.close()
            return
        try:
            self._announce(sock, "ssdp:alive")
            next_announce = time.monotonic() + self.interval
            while not self._stop_event.is_set():
                try:
                    data, address = sock.recvfrom(2048)
                except socket.timeout:
                    pass
                except OSError:
                    break
                else:
                    self._maybe_respond(sock, data, address)
                if time.monotonic() >= next_announce:
                    self._announce(sock, "ssdp:alive")
                    next_announce = time.monotonic() + self.interval
        finally:
            try:
                self._announce(sock, "ssdp:byebye")
            except OSError:
                pass
            sock.close()

    def _maybe_respond(self, sock: socket.socket, data: bytes, address: tuple) -> None:
        message = data.decode("latin-1", errors="replace")
        if not message.startswith("M-SEARCH"):
            return
        st = _parse_headers(message).get("st", "")
        if st == "ssdp:all":
            matches = self.targets
        else:
            matches = [(nt, usn) for nt, usn in self.targets if nt == st]
        for nt, usn in matches:
            response = (
                "HTTP/1.1 200 OK\r\n"
                "CACHE-CONTROL: max-age=1800\r\n"
                "EXT:\r\n"
                f"LOCATION: {self.location}\r\n"
                f"SERVER: {_SERVER_HEADER}\r\n"
                f"ST: {nt}\r\n"
                f"USN: {usn}\r\n\r\n"
            )
            try:
                sock.sendto(response.encode("ascii"), address)
            except OSError:
                pass

    def _announce(self, sock: socket.socket, nts: str) -> None:
        for nt, usn in self.targets:
            message = (
                "NOTIFY * HTTP/1.1\r\n"
                f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
                "CACHE-CONTROL: max-age=1800\r\n"
                f"LOCATION: {self.location}\r\n"
                f"NT: {nt}\r\n"
                f"NTS: {nts}\r\n"
                f"SERVER: {_SERVER_HEADER}\r\n"
                f"USN: {usn}\r\n\r\n"
            )
            try:
                sock.sendto(message.encode("ascii"), (SSDP_ADDR, SSDP_PORT))
            except OSError:
                pass


def _msearch(st: str, mx: int) -> str:
    return (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {mx}\r\n"
        f"ST: {st}\r\n"
        f"USER-AGENT: {_SERVER_HEADER}\r\n\r\n"
    )


def _parse_headers(message: str) -> dict[str, str]:
    """Parse the header block of an SSDP message into a lowercase-keyed dict."""
    headers = {}
    for line in message.split("\r\n")[1:]:
        key, separator, value = line.partition(":")
        if separator:
            headers[key.strip().lower()] = value.strip()
    return headers