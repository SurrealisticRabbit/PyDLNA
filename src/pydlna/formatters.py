"""XML builders and parsers for every UPnP/DLNA document PyDLNA speaks.

Everything on the wire (SSDP aside) is XML: the device description, the
service descriptions (SCPD), the SOAP envelopes used for actions, and the
DIDL-Lite metadata describing media. Keeping all of it in one place makes
the wire format easy to audit.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from pydlna.errors import UPnPError
from pydlna.file import MediaFile, MediaItem

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"

_DIDL_OPEN = (
    '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
    'xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">'
)

# SCPD tables: (action, [(argument, direction, related state variable), ...])
_CONTENT_DIRECTORY_ACTIONS = [
    ("GetSearchCapabilities", [("SearchCaps", "out", "SearchCapabilities")]),
    ("GetSortCapabilities", [("SortCaps", "out", "SortCapabilities")]),
    ("GetSystemUpdateID", [("Id", "out", "SystemUpdateID")]),
    ("Browse", [
        ("ObjectID", "in", "A_ARG_TYPE_ObjectID"),
        ("BrowseFlag", "in", "A_ARG_TYPE_BrowseFlag"),
        ("Filter", "in", "A_ARG_TYPE_Filter"),
        ("StartingIndex", "in", "A_ARG_TYPE_Index"),
        ("RequestedCount", "in", "A_ARG_TYPE_Count"),
        ("SortCriteria", "in", "A_ARG_TYPE_SortCriteria"),
        ("Result", "out", "A_ARG_TYPE_Result"),
        ("NumberReturned", "out", "A_ARG_TYPE_Count"),
        ("TotalMatches", "out", "A_ARG_TYPE_Count"),
        ("UpdateID", "out", "A_ARG_TYPE_UpdateID"),
    ]),
    ("Search", [
        ("ContainerID", "in", "A_ARG_TYPE_ObjectID"),
        ("SearchCriteria", "in", "A_ARG_TYPE_SearchCriteria"),
        ("Filter", "in", "A_ARG_TYPE_Filter"),
        ("StartingIndex", "in", "A_ARG_TYPE_Index"),
        ("RequestedCount", "in", "A_ARG_TYPE_Count"),
        ("SortCriteria", "in", "A_ARG_TYPE_SortCriteria"),
        ("Result", "out", "A_ARG_TYPE_Result"),
        ("NumberReturned", "out", "A_ARG_TYPE_Count"),
        ("TotalMatches", "out", "A_ARG_TYPE_Count"),
        ("UpdateID", "out", "A_ARG_TYPE_UpdateID"),
    ]),
]

# SCPD state variables: (name, data type, sends events, allowed values)
_CONTENT_DIRECTORY_VARIABLES = [
    ("A_ARG_TYPE_ObjectID", "string", False, None),
    ("A_ARG_TYPE_Result", "string", False, None),
    ("A_ARG_TYPE_SearchCriteria", "string", False, None),
    ("A_ARG_TYPE_BrowseFlag", "string", False, ["BrowseMetadata", "BrowseDirectChildren"]),
    ("A_ARG_TYPE_Filter", "string", False, None),
    ("A_ARG_TYPE_SortCriteria", "string", False, None),
    ("A_ARG_TYPE_Index", "ui4", False, None),
    ("A_ARG_TYPE_Count", "ui4", False, None),
    ("A_ARG_TYPE_UpdateID", "ui4", False, None),
    ("SearchCapabilities", "string", False, None),
    ("SortCapabilities", "string", False, None),
    ("SystemUpdateID", "ui4", True, None),
]

_CONNECTION_MANAGER_ACTIONS = [
    ("GetProtocolInfo", [
        ("Source", "out", "SourceProtocolInfo"),
        ("Sink", "out", "SinkProtocolInfo"),
    ]),
    ("GetCurrentConnectionIDs", [("ConnectionIDs", "out", "CurrentConnectionIDs")]),
    ("GetCurrentConnectionInfo", [
        ("ConnectionID", "in", "A_ARG_TYPE_ConnectionID"),
        ("RcsID", "out", "A_ARG_TYPE_RcsID"),
        ("AVTransportID", "out", "A_ARG_TYPE_AVTransportID"),
        ("ProtocolInfo", "out", "A_ARG_TYPE_ProtocolInfo"),
        ("PeerConnectionManager", "out", "A_ARG_TYPE_ConnectionManager"),
        ("PeerConnectionID", "out", "A_ARG_TYPE_ConnectionID"),
        ("Direction", "out", "A_ARG_TYPE_Direction"),
        ("Status", "out", "A_ARG_TYPE_ConnectionStatus"),
    ]),
]

_CONNECTION_MANAGER_VARIABLES = [
    ("SourceProtocolInfo", "string", True, None),
    ("SinkProtocolInfo", "string", True, None),
    ("CurrentConnectionIDs", "string", True, None),
    ("A_ARG_TYPE_ConnectionStatus", "string", False,
     ["OK", "ContentFormatMismatch", "InsufficientBandwidth", "UnreliableChannel"]),
    ("A_ARG_TYPE_ConnectionManager", "string", False, None),
    ("A_ARG_TYPE_Direction", "string", False, ["Input", "Output"]),
    ("A_ARG_TYPE_ProtocolInfo", "string", False, None),
    ("A_ARG_TYPE_ConnectionID", "i4", False, None),
    ("A_ARG_TYPE_AVTransportID", "i4", False, None),
    ("A_ARG_TYPE_RcsID", "i4", False, None),
]


class XMLFormatter:
    """Builds and parses every XML document PyDLNA speaks."""

    # -- Device & service descriptions -----------------------------------

    @staticmethod
    def device_description(udn: str, friendly_name: str) -> str:
        services = "".join(
            "<service>"
            f"<serviceType>urn:schemas-upnp-org:service:{name}:1</serviceType>"
            f"<serviceId>urn:upnp-org:serviceId:{name}</serviceId>"
            f"<SCPDURL>/scpd/{name}.xml</SCPDURL>"
            f"<controlURL>/control/{name}</controlURL>"
            f"<eventSubURL>/events/{name}</eventSubURL>"
            "</service>"
            for name in ("ContentDirectory", "ConnectionManager")
        )
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<root xmlns="urn:schemas-upnp-org:device-1-0">'
            "<specVersion><major>1</major><minor>0</minor></specVersion>"
            "<device>"
            "<deviceType>urn:schemas-upnp-org:device:MediaServer:1</deviceType>"
            f"<friendlyName>{escape(friendly_name)}</friendlyName>"
            "<manufacturer>PyDLNA</manufacturer>"
            "<modelName>PyDLNA Media Server</modelName>"
            "<modelNumber>0.1</modelNumber>"
            f"<UDN>{escape(udn)}</UDN>"
            '<dlna:X_DLNADOC xmlns:dlna="urn:schemas-dlna-org:device-1-0">DMS-1.50</dlna:X_DLNADOC>'
            f"<serviceList>{services}</serviceList>"
            "</device></root>"
        )

    @staticmethod
    def scpd_content_directory() -> str:
        return XMLFormatter._scpd(_CONTENT_DIRECTORY_ACTIONS, _CONTENT_DIRECTORY_VARIABLES)

    @staticmethod
    def scpd_connection_manager() -> str:
        return XMLFormatter._scpd(_CONNECTION_MANAGER_ACTIONS, _CONNECTION_MANAGER_VARIABLES)

    @staticmethod
    def _scpd(actions: list, variables: list) -> str:
        action_xml = "".join(
            "<action>"
            f"<name>{name}</name>"
            "<argumentList>"
            + "".join(
                f"<argument><name>{arg}</name><direction>{direction}</direction>"
                f"<relatedStateVariable>{related}</relatedStateVariable></argument>"
                for arg, direction, related in arguments
            )
            + "</argumentList></action>"
            for name, arguments in actions
        )
        variable_xml = "".join(
            f'<stateVariable sendEvents="{"yes" if events else "no"}">'
            f"<name>{name}</name><dataType>{data_type}</dataType>"
            + (
                "<allowedValueList>"
                + "".join(f"<allowedValue>{value}</allowedValue>" for value in allowed)
                + "</allowedValueList>"
                if allowed
                else ""
            )
            + "</stateVariable>"
            for name, data_type, events, allowed in variables
        )
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<scpd xmlns="urn:schemas-upnp-org:service-1-0">'
            "<specVersion><major>1</major><minor>0</minor></specVersion>"
            f"<actionList>{action_xml}</actionList>"
            f"<serviceStateTable>{variable_xml}</serviceStateTable>"
            "</scpd>"
        )

    # -- SOAP envelopes ----------------------------------------------------

    @staticmethod
    def soap_envelope(action: str, service_type: str, args: Mapping[str, object]) -> str:
        args_xml = "".join(
            f"<{key}>{escape(str(value))}</{key}>" for key, value in args.items()
        )
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<s:Envelope xmlns:s="{SOAP_NS}" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<s:Body><u:{action} xmlns:u="{service_type}">{args_xml}</u:{action}></s:Body>'
            "</s:Envelope>"
        )

    @staticmethod
    def soap_response(action: str, service_type: str, fields: Mapping[str, str]) -> str:
        return XMLFormatter.soap_envelope(f"{action}Response", service_type, fields)

    @staticmethod
    def soap_fault(code: int, description: str) -> str:
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<s:Envelope xmlns:s="{SOAP_NS}" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            "<s:Body><s:Fault>"
            "<faultcode>s:Client</faultcode><faultstring>UPnPError</faultstring>"
            '<detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0">'
            f"<errorCode>{code}</errorCode>"
            f"<errorDescription>{escape(description)}</errorDescription>"
            "</UPnPError></detail>"
            "</s:Fault></s:Body></s:Envelope>"
        )

    @staticmethod
    def parse_soap_action(body: bytes) -> tuple[str, dict[str, str]]:
        """Extract ``(action, arguments)`` from an incoming SOAP request."""
        element = _body_child(ET.fromstring(body))
        if element is None:
            raise ValueError("SOAP body is empty")
        return _local_name(element.tag), {
            _local_name(child.tag): (child.text or "") for child in element
        }

    @staticmethod
    def parse_soap_response(body: bytes, action: str) -> dict[str, str]:
        """Parse a SOAP response body into a dict; raise on SOAP faults."""
        element = _body_child(ET.fromstring(body))
        if element is None:
            raise ValueError("SOAP body is empty")
        if _local_name(element.tag) == "Fault":
            code, description = XMLFormatter.parse_soap_fault(body)
            raise UPnPError(code, description)
        return {_local_name(child.tag): (child.text or "") for child in element}

    @staticmethod
    def parse_soap_fault(body: bytes) -> tuple[int, str]:
        code, description = 0, "Unknown UPnP error"
        for element in ET.fromstring(body).iter():
            name = _local_name(element.tag)
            if name == "errorCode":
                try:
                    code = int(element.text or 0)
                except ValueError:
                    pass
            elif name == "errorDescription":
                description = element.text or description
        return code, description

    # -- DIDL-Lite -----------------------------------------------------------

    @staticmethod
    def didl_root_container(title: str, child_count: int) -> str:
        return (
            _DIDL_OPEN
            + f'<container id="0" parentID="-1" childCount="{child_count}" '
            'restricted="1" searchable="1">'
            f"<dc:title>{escape(title)}</dc:title>"
            "<upnp:class>object.container.storageFolder</upnp:class>"
            "</container></DIDL-Lite>"
        )

    @staticmethod
    def didl_items(files: Iterable[MediaFile], base_url: str) -> str:
        items = []
        for media in files:
            url = f"{base_url}/media/{media.id}"
            items.append(
                f'<item id="{escape(media.id)}" parentID="0" restricted="1">'
                f"<dc:title>{escape(media.title or '')}</dc:title>"
                f"<upnp:class>{media.upnp_class}</upnp:class>"
                f'<res protocolInfo="{escape(media.protocol_info)}" '
                f'size="{media.size}">{escape(url)}</res>'
                "</item>"
            )
        return _DIDL_OPEN + "".join(items) + "</DIDL-Lite>"

    @staticmethod
    def parse_didl_lite(xml_text: str) -> list[MediaItem]:
        """Parse a DIDL-Lite document (e.g. a Browse result) into media items."""
        if not xml_text.strip():
            return []
        items = []
        for element in ET.fromstring(xml_text):
            kind = _local_name(element.tag)
            if kind not in ("item", "container"):
                continue
            entry = MediaItem(
                id=element.get("id", ""),
                parent_id=element.get("parentID", "0"),
                is_container=(kind == "container"),
            )
            for child in element:
                name = _local_name(child.tag)
                if name == "title":
                    entry.title = child.text or ""
                elif name == "class":
                    entry.upnp_class = child.text or ""
                elif name == "res":
                    entry.url = (child.text or "").strip()
                    parts = child.get("protocolInfo", "").split(":")
                    if len(parts) >= 3:
                        entry.mime_type = parts[2]
                    try:
                        entry.size = int(child.get("size") or 0)
                    except ValueError:
                        pass
            items.append(entry)
        return items


def _local_name(tag: str) -> str:
    """Strip the ``{namespace}`` prefix from an ElementTree tag."""
    return tag.rsplit("}", 1)[-1]


def _body_child(envelope: ET.Element) -> Optional[ET.Element]:
    """The first element inside the SOAP ``Body`` of an envelope."""
    for child in envelope:
        if _local_name(child.tag) == "Body":
            return next(iter(child), None)
    return None