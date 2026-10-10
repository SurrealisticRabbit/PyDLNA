"""Serve folder media and play first file on first DLNA renderer.

Usage:
    python examples/basic.py [folder]
"""

from pathlib import Path
from pydlna import DLNA_Discovery, DLNA_Server

folder = Path("D:/Movies")

with DLNA_Server() as server:
    added = server.library.add_directory(folder)
    if not added:
        raise RuntimeError(f"No media files found in {folder}")

    renderer = next(
        (device for device in DLNA_Discovery().discover() if device.is_renderer),
        None,
    )
    if renderer is None:
        raise RuntimeError("No DLNA renderer found")

    media = server.library[0]
    renderer.controller().play(media)
    print(f"Playing {media.title} on {renderer.name}")