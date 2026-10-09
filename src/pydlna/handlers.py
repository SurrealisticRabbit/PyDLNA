"""HTTP request handlers for the PyDLNA media server.

One handler class routes everything a DLNA device can send:

* ``GET``/``HEAD`` — device description, SCPD documents, and media bytes
  with byte-range support (renderers rely on ranges for seeking),
* ``POST`` — SOAP control actions, dispatched to the UPnP services,
* ``SUBSCRIBE``/``UNSUBSCRIBE`` — GENA eventing stubs.
"""

from __future__ import annotations

import logging
import uuid
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
from xml.etree.ElementTree import ParseError

from pydlna.errors import UPnPError
from pydlna.formatters import XMLFormatter

logger = logging.getLogger(__name__)

_CHUNK = 64 * 1024


class DLNA_RequestHandler(BaseHTTPRequestHandler):
    """Routes HTTP requests to the services and media of a ``DLNAServer``."""

    server_version = "PyDLNA/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def app(self):
        """The ``DLNAServer`` instance behind this request."""
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: object) -> None:
        logger.debug("%s - %s", self.address_string(), fmt % args)

    # -- GET / HEAD ------------------------------------------------------

    def do_GET(self) -> None:
        self._route_get(send_body=True)

    def do_HEAD(self) -> None:
        self._route_get(send_body=False)

    def _route_get(self, send_body: bool) -> None:
        path = urlsplit(self.path).path
        if path in ("/", "/device.xml"):
            self._send_xml(self.app.device_description(), send_body=send_body)
        elif path == "/scpd/ContentDirectory.xml":
            self._send_xml(XMLFormatter.scpd_content_directory(), send_body=send_body)
        elif path == "/scpd/ConnectionManager.xml":
            self._send_xml(XMLFormatter.scpd_connection_manager(), send_body=send_body)
        elif path.startswith("/media/"):
            self._send_media(path.rsplit("/", 1)[-1], send_body)
        else:
            self.send_error(404, "Not Found")

    # -- POST (SOAP control) ----------------------------------------------

    _CONTROL_SERVICES = {
        "/control/ContentDirectory": "content_directory",
        "/control/ConnectionManager": "connection_manager",
    }

    def do_POST(self) -> None:
        attribute = self._CONTROL_SERVICES.get(urlsplit(self.path).path)
        if attribute is None:
            self.send_error(404, "Not Found")
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(length)
        try:
            action, args = XMLFormatter.parse_soap_action(payload)
        except (ParseError, ValueError):
            self.send_error(400, "Malformed SOAP request")
            return
        service = getattr(self.app, attribute)
        try:
            result = service.handle(action, args, base_url=self._request_base())
        except UPnPError as exc:
            self._send_xml(XMLFormatter.soap_fault(exc.code, exc.description), status=500)
            return
        self._send_xml(XMLFormatter.soap_response(action, service.service_type, result))

    # -- SUBSCRIBE / UNSUBSCRIBE (GENA) -------------------------------------
    # Eventing is stubbed: subscriptions are accepted so renderers stay
    # happy, but no NOTIFY messages are sent (the library is static).

    def do_SUBSCRIBE(self) -> None:
        if "CALLBACK" not in self.headers and "SID" not in self.headers:
            self.send_error(412, "Precondition Failed")
            return
        self.send_response(200)
        self.send_header("SID", f"uuid:{uuid.uuid4()}")
        self.send_header("TIMEOUT", "Second-1800")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_UNSUBSCRIBE(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- Internals -----------------------------------------------------------

    def _request_base(self) -> str:
        host = self.headers.get("Host")
        return f"http://{host}" if host else self.app.base_url

    def _send_xml(self, text: str, status: int = 200, send_body: bool = True) -> None:
        payload = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if send_body:
            self.wfile.write(payload)

    def _send_media(self, item_id: str, send_body: bool) -> None:
        media = self.app.library.get(item_id)
        if media is None:
            self.send_error(404, "Not Found")
            return
        try:
            size = media.path.stat().st_size
        except OSError:
            self.send_error(404, "Not Found")
            return
        start, end, status = self._resolve_range(size)
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", media.mime_type or "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("contentFeatures.dlna.org", "DLNA.ORG_OP=01;DLNA.ORG_CI=0")
        self.send_header("transferMode.dlna.org", "Streaming")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not send_body:
            return
        try:
            with media.path.open("rb") as stream:
                stream.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = stream.read(min(_CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # The renderer wandered off mid-stream; nothing to fix.

    def _resolve_range(self, size: int) -> tuple[int, int, int]:
        """Translate a ``Range`` header into ``(start, end, http_status)``."""
        header = self.headers.get("Range", "")
        if header.startswith("bytes="):
            first, _, last = header[6:].split(",", 1)[0].partition("-")
            try:
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                else:  # Suffix range: the last N bytes.
                    start, end = max(0, size - int(last)), size - 1
                if 0 <= start <= end:
                    return start, end, 206
            except ValueError:
                pass
        return 0, size - 1, 200
