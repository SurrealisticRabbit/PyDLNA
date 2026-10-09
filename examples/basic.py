"""Serve a folder of media over DLNA and play it on the first renderer found.

Usage:
    python examples/basic.py [folder]
"""

import time
from pydlna import DLNADiscovery, DLNAServer

folder = "D:/Movies"

with DLNAServer(name="PyDLNA Example") as server:
    server.library.add_directory(folder)

    target = None
    with DLNADiscovery().discover() as devices:
        for device in devices:
            if device.is_renderer:
                print(f"Found renderer: {device.name}")
                target = device
                break

    if target is None:
        print("No renderer found.")
    else:
        with target.controller() as session:
            media = server.library[0]
            print(f"Sending: {media.url_for(target.address)}")
            session.play(media)

            while session.is_playing():
                current = session.currently_playing
                print(f"Playing: {server.library[0].title[:18]}> {current.position}:{current.duration}", end="\r")
                time.sleep(1)