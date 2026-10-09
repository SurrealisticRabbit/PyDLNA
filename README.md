# PyDLNA

A simple, zero-dependency Python library for DLNA streaming, discovery, and device control.

Most DLNA libraries out there are either overly complex, poorly documented, or unmaintained. **PyDLNA** is built to be fit-for-purpose, straightforward, and ready to use in a few lines of code.

```bash
pip install PyDLNA

```

---

## Quick Concepts

* **`DLNADiscovery()`** — Your best friend for finding DLNA devices (renderers, media servers, etc.) on your local network.
* **`DLNAServer()`** — Hosts and serves your local media files over HTTP with proper DLNA headers.
* **`device.controller()`** — Gives you an active playback control session (`.play()`, `.pause()`, track info) for a specific renderer.

---

## Usage Examples

### 1. Basic Streaming — `examples/basic.py`

Serve a directory, find a smart TV or speaker on the network, and throw a video/audio track directly to it:

```python
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
                print(f"Playing: {media.title[:18]} > {current.position}:{current.duration}", end="\r")
                time.sleep(1)

```

---

### 2. Inspecting Network Devices — `examples/client_info.py`

Scan your network and inspect the hardware, model numbers, and supported playback formats of discovered renderers:

```python
from pydlna import DLNADiscovery

for client in DLNADiscovery().discover():
    if client.is_renderer:
        print(f"{client.name or '(unnamed)'}  @  {client.address}")
        print(f"  Manufacturer       : {client.manufacturer} ({client.manufacturer_url})")
        print(f"  Model              : {client.model_name} {client.model_number}")
        print(f"  Playable formats   : {client.playback_formats}")
        print(f"  Supported protocols: {client.supported_protocols}")
        print("-" * 50)

```