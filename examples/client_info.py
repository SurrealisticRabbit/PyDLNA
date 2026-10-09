"""Show what PyDLNA can see about renderer clients on the network.

Run:  python examples/client_info.py
"""

from pydlna import DLNADiscovery

for client in DLNADiscovery().discover():
    if client.is_renderer:
        print(f"{client.name or '(unnamed)'}  @  {client.address}")
        print(f"  Manufacturer    : {client.manufacturer}  {client.manufacturer_url}")
        print(f"  Model           : {client.model_name}  {client.model_number}")
        print(f"  Playable formats: {client.playback_formats}")
        print(f"  Supported protocols: {client.supported_protocols}")