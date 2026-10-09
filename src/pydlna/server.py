"""The PyDLNA media server: HTTP, UPnP services and SSDP glued together."""

from __future__ import annotations

import logging
import mimetypes
import socket
import threading
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Iterator, Optional, Union

from pydlna.discovery import SSDPResponder
from pydlna.file import MediaFile
from pydlna.formatters import XMLFormatter
from pydlna.handlers import DLNA_RequestHandler
from pydlna.services import ConnectionManagerService, ContentDirectoryService

logger = logging.getLogger(__name__)

_MEDIA_TOP_TYPES = ("audio", "video", "image")


class MediaLibrary:
    """A flat collection of media files, each with a stable DLNA object id."""

    def __init__(self, server: Optional["DLNA_Server"] = None) -> None:
        self.server = server
        self._items: dict[str, MediaFile] = {}

    def add(self, path: Union[str, Path, MediaFile]) -> MediaFile:
        """Add a single file and return it with its new object id."""
        media = path if isinstance(path, MediaFile) else MediaFile(Path(path))
        media.id = f"item-{len(self._items)}"
        media.library = self
        self._items[media.id] = media
        return media

    def add_directory(self, root: Union[str, Path], recursive: bool = True) -> int:
        """Add every audio/video/image file under a directory; returns the count."""
        root = Path(root).expanduser()
        pattern = "**/*" if recursive else "*"
        added = 0
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            mime_type = mimetypes.guess_type(path.name)[0] or ""
            if mime_type.split("/", 1)[0] in _MEDIA_TOP_TYPES:
                self.add(path)
                added += 1
        return added

    def get(self, item_id: str) -> Optional[MediaFile]:
        return self._items.get(item_id)

    def __getitem__(self, index: int) -> MediaFile:
        return self.files[index]

    @property
    def files(self) -> list[MediaFile]:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[MediaFile]:
        return iter(self._items.values())


class DLNA_Server:
    """A DLNA Digital Media Server.

    Serves device/service descriptions and media bytes over HTTP, answers
    SOAP actions on its UPnP services, and advertises itself over SSDP.
    """

    def __init__(self, name: str = "PyDLNA Media Server", host: str = "0.0.0.0",
                 port: int = 8200, udn: Optional[str] = None) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.udn = udn or f"uuid:{uuid.uuid4()}"
        self.library = MediaLibrary(server=self)
        self.content_directory = ContentDirectoryService(self.library, root_title=name)
        self.connection_manager = ConnectionManagerService(self.library)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._ssdp: Optional[SSDPResponder] = None

    def __enter__(self) -> "DLNA_Server":
        """Start the server; usable as ``with DLNAServer(...) as server:``."""
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- Properties -----------------------------------------------------------

    @property
    def local_ip(self) -> str:
        """Best-effort guess of the LAN IP to advertise."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("239.255.255.250", 1900))  # UDP: no traffic is sent
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            sock.close()

    def local_ip_for(self, target: str) -> str:
        """The local IP that traffic to ``target`` would leave from."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((target, 80))  # UDP: no traffic is sent
            return sock.getsockname()[0]
        except OSError:
            return self.local_ip
        finally:
            sock.close()

    @property
    def base_url(self) -> str:
        return f"http://{self.local_ip}:{self.port}"

    # -- Descriptions ------------------------------------------------------------

    def device_description(self) -> str:
        return XMLFormatter.device_description(self.udn, self.name)

    # -- Lifecycle ------------------------------------------------------------------

    def start(self, advertise: bool = True) -> None:
        """Start the HTTP server (and SSDP advertisements) in the background."""
        if self._httpd is not None:
            return
        self._httpd = ThreadingHTTPServer((self.host, self.port), DLNA_RequestHandler)
        self._httpd.daemon_threads = True
        self._httpd.app = self  # type: ignore[attr-defined]
        self.port = self._httpd.server_address[1]  # resolves port=0
        threading.Thread(
            target=self._httpd.serve_forever, name="pydlna-http", daemon=True
        ).start()
        if advertise:
            self._ssdp = SSDPResponder(udn=self.udn, location=f"{self.base_url}/device.xml")
            self._ssdp.start()
        logger.info("Serving '%s' at %s", self.name, self.base_url)

    def serve_forever(self) -> None:
        """Start (if needed) and block until ``stop()`` or Ctrl+C."""
        self.start()
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        if self._ssdp is not None:
            self._ssdp.stop()
            self._ssdp.join(timeout=2)
            self._ssdp = None
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
