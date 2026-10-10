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

## Usage Examples

### Stream one file

Start a server, find first renderer, play a file:

```python
from pydlna import DLNA_Discovery, DLNA_Server

with DLNA_Server() as server:
    media = server.library.add("D:/Movies/movie.mp4")
    renderer = next(
        (device for device in DLNA_Discovery().discover() if device.is_renderer),
        None,
    )
    if renderer is None:
        raise RuntimeError("No DLNA renderer found")

    renderer.controller().play(media)
    print(f"Playing {media.title} on {renderer.name}")
```

Server stays alive inside `with` block. `play(media)` builds reachable media URL and sends both required UPnP commands.

### Stream a folder

`add_directory()` finds common audio, video, and image files. Select any file from library:

```python
from pydlna import DLNA_Discovery, DLNA_Server

with DLNA_Server() as server:
    server.library.add_directory("D:/Movies")
    renderer = next(device for device in DLNA_Discovery().discover() if device.is_renderer)
    renderer.controller().play(server.library[0])
```

### Find renderers

```python
from pydlna import DLNA_Discovery

for device in DLNA_Discovery().discover():
    if device.is_renderer:
        print(f"{device.name} at {device.address}")
```

## Renderer Compatibility

Compatibility check is optional. Use it when app must avoid sending files a renderer explicitly rejects:

```python
result = media.compatibility_with(renderer)
if result.can_play:
    renderer.controller().play(media)
```

Result status is `supported`, `unsupported`, or `unknown`. `unknown` permits playback because many renderers publish no usable Sink capabilities.

MIME detection uses host MIME data plus common media-extension fallbacks. It does not inspect codecs, resolution, audio tracks, or containers beyond file extension. PyDLNA avoids claiming a DLNA profile from MIME type alone because that can falsely advertise codec compatibility.