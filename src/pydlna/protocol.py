"""DLNA/UPnP ``protocolInfo`` parsing and compatibility matching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MediaCompatibility:
    """Compatibility result for a media resource and a renderer."""

    status: str
    reason: str = ""

    @classmethod
    def supported(cls) -> "MediaCompatibility":
        return cls("supported")

    @classmethod
    def unsupported(cls, reason: str) -> "MediaCompatibility":
        return cls("unsupported", reason)

    @classmethod
    def unknown(cls) -> "MediaCompatibility":
        return cls("unknown", "renderer does not publish usable Sink protocol information")

    @property
    def can_play(self) -> bool:
        """Whether playback should be attempted."""
        return self.status != "unsupported"


@dataclass(frozen=True)
class ProtocolInfo:
    """A parsed UPnP ``protocolInfo`` entry."""

    protocol: str
    network: str
    mime_type: str
    additional_info: str

    @classmethod
    def parse(cls, value: str) -> Optional["ProtocolInfo"]:
        parts = [part.strip() for part in value.strip().split(":")]
        if len(parts) != 4 or not parts[0] or not parts[2]:
            return None
        return cls(*parts)

    def matches(self, source: "ProtocolInfo") -> bool:
        """Whether this Sink entry accepts source protocol information."""
        return (
            _matches(self.protocol, source.protocol)
            and _matches(self.network, source.network)
            and _matches_mime(self.mime_type, source.mime_type)
            and _matches_additional_info(self.additional_info, source.additional_info)
        )


def _matches(expected: str, actual: str) -> bool:
    return expected == "*" or expected.lower() == actual.lower()


def _matches_mime(expected: str, actual: str) -> bool:
    if expected == "*":
        return True
    expected_type, separator, expected_subtype = expected.lower().partition("/")
    actual_type, actual_separator, actual_subtype = actual.lower().partition("/")
    if not separator or not actual_separator:
        return expected == actual
    return expected_type == actual_type and (expected_subtype == "*" or expected_subtype == actual_subtype)


def _matches_additional_info(expected: str, actual: str) -> bool:
    if expected in ("", "*"):
        return True
    expected_values = _parameters(expected)
    actual_values = _parameters(actual)
    for key, value in expected_values.items():
        if value != "*" and actual_values.get(key) != value:
            return False
    return True


def _parameters(value: str) -> dict[str, str]:
    values = {}
    for part in value.split(";"):
        key, separator, parameter = part.strip().partition("=")
        if separator:
            values[key.upper()] = parameter
    return values
