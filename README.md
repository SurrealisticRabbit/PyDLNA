# PyDLNA

A simple, zero-dependency Python library for DLNA streaming, discovery, and device control.

Most DLNA libraries out there are either overly complex, poorly documented, or unmaintained. **PyDLNA** is built to be fit-for-purpose, straightforward, and ready to use in a few lines of code.

```bash
pip install PyDLNA

```

---

## Quick Concepts

* **`DLNA_Discovery()`** — Finds DLNA devices (renderers, media servers) on local network.
* **`DLNA_Server()`** — Hosts and serves local media files over HTTP with DLNA headers.
* **`device.controller()`** — Gives active playback control session (`.play()`, `.pause()`, track info) for a renderer.

---

## Renderer Compatibility

`MediaFile.compatibility_with(renderer)` compares source `protocolInfo` against renderer ConnectionManager Sink entries. Result status is `supported`, `unsupported`, or `unknown`; `unknown` allows playback attempt because many renderers omit usable Sink data.

```python
result = media.compatibility_with(target)
if result.can_play:
    session.play(media)
```

MIME detection uses host MIME data plus common media-extension fallbacks. It does not inspect codecs, resolution, audio tracks, or containers beyond file extension. PyDLNA does not claim a DLNA profile from MIME type alone, because that can falsely advertise codec compatibility.

## Usage Examples

### 1. Basic Streaming — `examples/basic.py`

Serve a directory, find a smart TV or speaker on the network, and throw a video/audio track directly to it:

```python
import time
from pydlna import DLNA_Discovery, DLNA_Server

folder = "D:/Movies"

with DLNA_Server(name="PyDLNA Example") as server:
    server.library.add_directory(folder)

    target = None
    with DLNA_Discovery().discover() as devices:
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
from pydlna import DLNA_Discovery

for client in DLNA_Discovery().discover():
    if client.is_renderer:
        print(f"{client.name or '(unnamed)'}  @  {client.address}")
        print(f"  Manufacturer       : {client.manufacturer} ({client.manufacturer_url})")
        print(f"  Model              : {client.model_name} {client.model_number}")
        print(f"  Playable formats   : {client.playback_formats}")
        print(f"  Supported protocols: {client.supported_protocols}")
        print("-" * 50)

```