"""Media models shared by the PyDLNA server and client."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pydlna.server import MediaLibrary

_MIME_BY_EXTENSION = {
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mka": "audio/x-matroska",
    ".mkv": "video/x-matroska",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
    ".ogv": "video/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
    ".webm": "video/webm",
    ".wma": "audio/x-ms-wma",
    ".wmv": "video/x-ms-wmv",
}


def detect_mime_type(path: Path) -> str:
    """Return a stable media MIME type from host data or a known extension."""
    guessed = mimetypes.guess_type(path.name)[0]
    return guessed or _MIME_BY_EXTENSION.get(path.suffix.lower(), "application/octet-stream")


@dataclass
class MediaFile:
    """A local file exposed by the media server."""

    path: Path
    title: Optional[str] = None
    mime_type: Optional[str] = None
    id: str = ""
    library: Optional["MediaLibrary"] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.title is None:
            self.title = self.path.stem
        if self.mime_type is None:
            self.mime_type = detect_mime_type(self.path)

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0


    @property
    def upnp_class(self) -> str:
        top = (self.mime_type or "").split("/", 1)[0]
        return {
            "audio": "object.item.audioItem.musicTrack",
            "video": "object.item.videoItem",
            "image": "object.item.imageItem.photo",
        }.get(top, "object.item")

    @property
    def protocol_info(self) -> str:
        """Conservative ``protocolInfo`` for this file's DIDL-Lite resource."""
        return f"http-get:*:{self.mime_type}:DLNA.ORG_OP=01;DLNA.ORG_CI=0"

    def compatibility_with(self, renderer: object) -> "MediaCompatibility":
        """Return this file's compatibility with a renderer's Sink capabilities."""
        from pydlna.protocol import MediaCompatibility, ProtocolInfo

        protocols = getattr(renderer, "supported_protocols", ())
        candidates = [ProtocolInfo.parse(value) for value in protocols]
        candidates = [candidate for candidate in candidates if candidate is not None]
        if not candidates:
            return MediaCompatibility.unknown()
        source = ProtocolInfo.parse(self.protocol_info)
        if source is None:
            return MediaCompatibility.unsupported("invalid media protocol information")
        if any(candidate.matches(source) for candidate in candidates):
            return MediaCompatibility.supported()
        return MediaCompatibility.unsupported("renderer Sink does not accept this protocol information")

    @property
    def url(self) -> str:
        """Stream URL of this file, once it lives in a server's library."""
        return self.url_for()

    def url_for(self, target: Optional[str] = None) -> str:
        """Stream URL whose local IP is chosen to be reachable from ``target``.

        On multi-homed machines (VPN, Hyper-V/WSL adapters) the default LAN
        IP guess can pick the wrong interface; passing the renderer's address
        picks the local IP that would actually route to it.
        """
        server = self.library.server if self.library else None
        if server is None or not self.id:
            return ""
        host = server.local_ip_for(target) if target else server.local_ip
        return f"http://{host}:{server.port}/media/{self.id}"


@dataclass
class MediaItem:
    """A media entry parsed from a DIDL-Lite document (client side)."""

    id: str
    parent_id: str = "0"
    title: str = ""
    upnp_class: str = ""
    is_container: bool = False
    url: str = ""
    mime_type: str = ""
    size: int = 0