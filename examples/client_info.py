"""List DLNA renderers found on local network.

Usage:
    python examples/client_info.py
"""

from pydlna import DLNA_Discovery

renderers = [device for device in DLNA_Discovery().discover() if device.is_renderer]
if not renderers:
    print("No DLNA renderers found.")

for renderer in renderers:
    print(f"{renderer.name or '(unnamed)'} at {renderer.address}")
    if renderer.model_name:
        print(f"  {renderer.manufacturer} {renderer.model_name}")