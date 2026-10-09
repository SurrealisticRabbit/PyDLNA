"""DLNA clients (discovered devices) and the control point that drives them."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping, Optional, Union
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from pydlna.errors import UPnPError
from pydlna.file import MediaFile, MediaItem
from pydlna.formatters import XMLFormatter

logger = logging.getLogger(__name__)

_DEVICE_NS = {"upnp": "urn:schemas-upnp-org:device-1-0"}


@dataclass
class UPnPServiceInfo:
    """One service entry from a device's description document."""

    service_type: str
    service_id: str = ""
    control_url: str = ""
    scpd_url: str = ""
    event_url: str = ""


@dataclass
class PlaybackPosition:
    """A snapshot of what a renderer is playing right now."""

    position: str = ""
    duration: str = ""
    title: str = ""
    uri: str = ""


@dataclass
class DLNA_Client:
    """A DLNA/UPnP device discovered on the network."""

    name: str = ""
    address: Optional[str] = None
    location: Optional[str] = None
    udn: str = ""
    server: str = ""
    st: str = ""
    usn: str = ""
    device_type: str = ""
    manufacturer: str = ""
    manufacturer_url: str = ""
    model_name: str = ""
    model_number: str = ""
    model_description: str = ""
    serial_number: str = ""
    icons: list[str] = field(default_factory=list)
    services: dict[str, str] = field(default_factory=dict)
    service_details: list[UPnPServiceInfo] = field(default_factory=list)
    _protocol_cache: Optional[dict] = field(default=None, repr=False)

    @classmethod
    def from_ssdp(cls, address: str, headers: Mapping[str, str]) -> "DLNA_Client":
        """Build a client from the sender address and headers of an SSDP message."""
        return cls(
            address=address,
            location=headers.get("location"),
            server=headers.get("server", ""),
            st=headers.get("st", ""),
            usn=headers.get("usn", ""),
        )

    @property
    def is_renderer(self) -> bool:
        return "MediaRenderer" in (self.device_type or self.st)

    @property
    def is_server(self) -> bool:
        return "MediaServer" in (self.device_type or self.st)

    @property
    def supported_protocols(self) -> list[str]:
        """Raw ``protocolInfo`` entries the renderer accepts (its Sink list)."""
        sink = self._protocols().get("Sink", "")
        return [entry for entry in sink.split(",") if entry.strip()]

    @property
    def playback_formats(self) -> list[str]:
        """MIME types the renderer can play, parsed from its Sink list."""
        return [p.split(":")[2] for p in self.supported_protocols if p.count(":") >= 2]

    def _protocols(self) -> dict[str, str]:
        """Cached ConnectionManager ``GetProtocolInfo`` call (best effort)."""
        if self._protocol_cache is None:
            try:
                self._protocol_cache = self.controller().get_protocol_info()
            except (UPnPError, OSError):
                self._protocol_cache = {}
        return self._protocol_cache

    def fetch_description(self, timeout: float = 5.0) -> bool:
        """Fetch and parse the device description document (best effort)."""
        if not self.location:
            return False
        try:
            with urllib.request.urlopen(self.location, timeout=timeout) as response:
                root = ET.fromstring(response.read())
        except (OSError, ET.ParseError) as exc:
            logger.debug("Could not fetch %s: %s", self.location, exc)
            return False
        device = root.find("upnp:device", _DEVICE_NS)
        if device is None:
            return False
        self.name = device.findtext("upnp:friendlyName", "", _DEVICE_NS)
        self.udn = device.findtext("upnp:UDN", "", _DEVICE_NS)
        self.device_type = device.findtext("upnp:deviceType", "", _DEVICE_NS)
        self.manufacturer = device.findtext("upnp:manufacturer", "", _DEVICE_NS)
        self.manufacturer_url = device.findtext("upnp:manufacturerURL", "", _DEVICE_NS)
        self.model_name = device.findtext("upnp:modelName", "", _DEVICE_NS)
        self.model_number = device.findtext("upnp:modelNumber", "", _DEVICE_NS)
        self.model_description = device.findtext("upnp:modelDescription", "", _DEVICE_NS)
        self.serial_number = device.findtext("upnp:serialNumber", "", _DEVICE_NS)
        self.icons.clear()
        self.services.clear()
        self.service_details.clear()
        for icon in device.findall("upnp:iconList/upnp:icon", _DEVICE_NS):
            url = icon.findtext("upnp:url", "", _DEVICE_NS)
            if url:
                self.icons.append(urljoin(self.location, url))
        for service in device.findall("upnp:serviceList/upnp:service", _DEVICE_NS):
            detail = UPnPServiceInfo(
                service_type=service.findtext("upnp:serviceType", "", _DEVICE_NS),
                service_id=service.findtext("upnp:serviceId", "", _DEVICE_NS),
                control_url=self._absolute(service.findtext("upnp:controlURL", "", _DEVICE_NS)),
                scpd_url=self._absolute(service.findtext("upnp:SCPDURL", "", _DEVICE_NS)),
                event_url=self._absolute(service.findtext("upnp:eventSubURL", "", _DEVICE_NS)),
            )
            self.service_details.append(detail)
            if detail.service_type and detail.control_url:
                self.services[detail.service_type] = detail.control_url
        return True

    def _absolute(self, url: str) -> str:
        """Resolve a possibly-relative URL against the description location."""
        return urljoin(self.location, url) if url else ""

    def controller(self) -> "DLNA_Controller":
        return DLNA_Controller(self)


class DLNA_Controller:
    """A UPnP control point: calls SOAP actions on a ``DLNAClient``."""

    def __init__(self, client: Optional[DLNA_Client] = None) -> None:
        self.client = client or DLNA_Client()

    def __enter__(self) -> "DLNA_Controller":
        """The controller doubles as a ``with`` session for readability."""
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    # -- Generic action call -----------------------------------------------

    def _request(self, service: str, action: str, **args: object) -> dict[str, str]:
        service_type = f"urn:schemas-upnp-org:service:{service}:1"
        url = self.client.services.get(service_type)
        if url is None and self.client.fetch_description():
            url = self.client.services.get(service_type)
        if url is None:
            raise UPnPError(401, f"Device does not expose {service}")
        envelope = XMLFormatter.soap_envelope(action, service_type, args)
        request = urllib.request.Request(
            url,
            data=envelope.encode("utf-8"),
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPAction": f'"{service_type}#{action}"',
                "User-Agent": "PyDLNA/0.1 UPnP/1.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return XMLFormatter.parse_soap_response(response.read(), action)
        except urllib.error.HTTPError as exc:
            # UPnP devices answer failures with HTTP 500 + a SOAP fault body.
            return XMLFormatter.parse_soap_response(exc.read(), action)

    # -- ContentDirectory ----------------------------------------------------

    def browse(self, object_id: str = "0", browse_flag: str = "BrowseDirectChildren",
               filter: str = "*", start: int = 0, count: int = 0,
               sort: str = "") -> dict[str, str]:
        """Browse a media server; returns the raw response fields."""
        return self._request(
            "ContentDirectory", "Browse",
            ObjectID=object_id, BrowseFlag=browse_flag, Filter=filter,
            StartingIndex=str(start), RequestedCount=str(count), SortCriteria=sort,
        )

    def browse_items(self, object_id: str = "0", **kwargs: object) -> list[MediaItem]:
        """Browse a media server and parse the DIDL-Lite result."""
        response = self.browse(object_id, **kwargs)
        return XMLFormatter.parse_didl_lite(response.get("Result", ""))

    # -- AVTransport (renderers) ----------------------------------------------

    def set_av_transport_uri(self, uri: str, metadata: str = "") -> dict[str, str]:
        return self._request("AVTransport", "SetAVTransportURI",
                             InstanceID="0", CurrentURI=uri, CurrentURIMetaData=metadata)

    def play(self, media: Optional[Union[MediaFile, str]] = None,
             speed: str = "1") -> dict[str, str]:
        """Start playback, optionally loading a ``MediaFile`` or URL first."""
        if isinstance(media, MediaFile):
            url = media.url_for(self.client.address)
            if not url:
                raise ValueError("MediaFile is not attached to a server library")
            base_url = url.rsplit("/media/", 1)[0]
            self.set_av_transport_uri(url, XMLFormatter.didl_items([media], base_url))
        elif isinstance(media, str):
            self.set_av_transport_uri(media)
        return self._request("AVTransport", "Play", InstanceID="0", Speed=speed)

    def is_playing(self) -> bool:
        """True while the renderer reports ``PLAYING`` (best effort)."""
        try:
            return self.get_transport_info().get("CurrentTransportState") == "PLAYING"
        except (UPnPError, OSError):
            return False

    @property
    def currently_playing(self) -> PlaybackPosition:
        """Position, duration and title of the current track (best effort)."""
        try:
            info = self.get_position_info()
        except (UPnPError, OSError):
            return PlaybackPosition()
        title = ""
        metadata = info.get("TrackMetaData", "")
        if metadata:
            tracks = XMLFormatter.parse_didl_lite(metadata)
            if tracks:
                title = tracks[0].title
        return PlaybackPosition(
            position=info.get("RelTime", ""),
            duration=info.get("TrackDuration", ""),
            title=title,
            uri=info.get("TrackURI", ""),
        )

    def pause(self) -> dict[str, str]:
        return self._request("AVTransport", "Pause", InstanceID="0")

    def stop(self) -> dict[str, str]:
        return self._request("AVTransport", "Stop", InstanceID="0")

    # -- RenderingControl --------------------------------------------------------

    def get_volume(self, channel: str = "Master") -> int:
        response = self._request("RenderingControl", "GetVolume",
                                 InstanceID="0", Channel=channel)
        return int(response.get("CurrentVolume") or 0)

    def set_volume(self, volume: int, channel: str = "Master") -> dict[str, str]:
        return self._request("RenderingControl", "SetVolume",
                             InstanceID="0", Channel=channel, DesiredVolume=str(volume))

    # -- Status queries ---------------------------------------------------------

    def get_transport_info(self) -> dict[str, str]:
        """Playback state: CurrentTransportState, CurrentTransportStatus, Speed."""
        return self._request("AVTransport", "GetTransportInfo", InstanceID="0")

    def get_media_info(self) -> dict[str, str]:
        """The renderer's currently loaded media (CurrentURI, duration, ...)."""
        return self._request("AVTransport", "GetMediaInfo", InstanceID="0")

    def get_position_info(self) -> dict[str, str]:
        """Position within the current track (RelTime, TrackDuration, ...)."""
        return self._request("AVTransport", "GetPositionInfo", InstanceID="0")

    def get_protocol_info(self) -> dict[str, str]:
        """Source/Sink protocol lists; a renderer's Sink is its format support."""
        return self._request("ConnectionManager", "GetProtocolInfo")