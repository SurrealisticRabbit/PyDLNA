"""UPnP service implementations exposed by the media server.

Each service owns a set of SOAP actions. The HTTP layer (handlers.py) parses
the envelope and calls ``handle()``; the service does the actual work and
returns the response fields. This keeps protocol parsing and business logic
in separate, testable places.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Mapping

from pydlna.errors import UPnPError
from pydlna.formatters import XMLFormatter

if TYPE_CHECKING:
    from pydlna.server import MediaLibrary

logger = logging.getLogger(__name__)


class UPnPService:
    """Base class: dispatches SOAP action names to Python callables."""

    service_type = ""

    def __init__(self) -> None:
        self._actions: dict[str, Callable] = {}

    def handle(self, action: str, args: Mapping[str, str], base_url: str) -> dict[str, str]:
        method = self._actions.get(action)
        if method is None:
            raise UPnPError(401, f"Invalid action: {action}")
        logger.debug("%s.%s(%s)", type(self).__name__, action, dict(args))
        return method(args, base_url)


class ContentDirectoryService(UPnPService):
    """Implements ``ContentDirectory:1`` over a flat media library."""

    service_type = "urn:schemas-upnp-org:service:ContentDirectory:1"

    def __init__(self, library: "MediaLibrary", root_title: str = "PyDLNA") -> None:
        super().__init__()
        self.library = library
        self.root_title = root_title
        self._actions = {
            "Browse": self._browse,
            "Search": self._search,
            "GetSearchCapabilities": lambda args, base_url: {"SearchCaps": ""},
            "GetSortCapabilities": lambda args, base_url: {"SortCaps": ""},
            "GetSystemUpdateID": lambda args, base_url: {"Id": "1"},
        }

    def _browse(self, args: Mapping[str, str], base_url: str) -> dict[str, str]:
        object_id = args.get("ObjectID", "0")
        browse_flag = args.get("BrowseFlag", "BrowseDirectChildren")
        start = _to_int(args.get("StartingIndex"), 0)
        count = _to_int(args.get("RequestedCount"), 0)

        if browse_flag == "BrowseMetadata":
            didl, returned, total = self._metadata(object_id, base_url)
        elif object_id == "0":
            files = self.library.files
            selection = files[start:] if count == 0 else files[start:start + count]
            didl = XMLFormatter.didl_items(selection, base_url)
            returned, total = len(selection), len(files)
        else:
            # The library is flat: only the root container has children.
            raise UPnPError(701, f"No such object: {object_id}")
        return {
            "Result": didl,
            "NumberReturned": str(returned),
            "TotalMatches": str(total),
            "UpdateID": "1",
        }

    def _metadata(self, object_id: str, base_url: str) -> tuple[str, int, int]:
        if object_id == "0":
            didl = XMLFormatter.didl_root_container(self.root_title, len(self.library))
            return didl, 1, 1
        media = self.library.get(object_id)
        if media is None:
            raise UPnPError(701, f"No such object: {object_id}")
        return XMLFormatter.didl_items([media], base_url), 1, 1

    def _search(self, args: Mapping[str, str], base_url: str) -> dict[str, str]:
        # Searching is out of scope for a flat library; answer with an empty
        # (but valid) result instead of an error so renderers don't choke.
        return {
            "Result": XMLFormatter.didl_items([], base_url),
            "NumberReturned": "0",
            "TotalMatches": "0",
            "UpdateID": "1",
        }


class ConnectionManagerService(UPnPService):
    """Implements ``ConnectionManager:1`` for HTTP-pull streaming."""

    service_type = "urn:schemas-upnp-org:service:ConnectionManager:1"

    def __init__(self, library: "MediaLibrary") -> None:
        super().__init__()
        self.library = library
        self._actions = {
            "GetProtocolInfo": self._protocol_info,
            "GetCurrentConnectionIDs": lambda args, base_url: {"ConnectionIDs": ""},
            "GetCurrentConnectionInfo": self._connection_info,
        }

    def _protocol_info(self, args: Mapping[str, str], base_url: str) -> dict[str, str]:
        mime_types = sorted({media.mime_type for media in self.library if media.mime_type})
        source = ";".join(f"http-get:*:{mime}:*" for mime in mime_types)
        return {"Source": source, "Sink": ""}

    def _connection_info(self, args: Mapping[str, str], base_url: str) -> dict[str, str]:
        raise UPnPError(701, "Invalid connection ID")


def _to_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
