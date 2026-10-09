"""Exceptions raised by PyDLNA."""


class UPnPError(Exception):
    """A UPnP-level error.

    Raised by the server to abort a SOAP action (the HTTP layer turns it
    into a SOAP fault) and by the client when a remote device answers an
    action call with a fault.
    """

    def __init__(self, code: int, description: str = "") -> None:
        super().__init__(f"UPnP error {code}: {description or 'unknown'}")
        self.code = code
        self.description = description
