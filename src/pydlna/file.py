"""Media models shared by the PyDLNA server and client."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pydlna.server import MediaLibrary

# Best-effort DLNA profile names keyed by MIME type. Anything not listed is
# advertised with a wildcard profile, which most renderers still accept.
_DLNA_PROFILES = {
    "audio/mpeg": "MP3",
    "audio/mp4": "AAC_ISO",
    "audio/x-m4a": "AAC_ISO",
    "audio/wav": "LPCM",
    "audio/x-wav": "LPCM",
    "image/jpeg": "JPEG_LRG",
    "image/png": "PNG_LRG",
    "video/mp4": "AVC_MP4_MP_HD_720p_AAC",
    "video/mpeg": "MPEG_PS_PAL",
}


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
            self.mime_type = mimetypes.guess_type(self.path.name)[0] or "application/octet-stream"

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    @property
    def dlna_profile(self) -> str:
        return _DLNA_PROFILES.get(self.mime_type or "", "*")

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
        """The ``protocolInfo`` attribute used in DIDL-Lite ``<res>`` elements."""
        profile = f"DLNA.ORG_PN={self.dlna_profile};" if self.dlna_profile != "*" else ""
        return f"http-get:*:{self.mime_type}:{profile}DLNA.ORG_OP=01;DLNA.ORG_CI=0"

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