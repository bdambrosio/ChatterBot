"""Zenoh session for desktop apps.

Connects to one explicit router endpoint (the Pi) with multicast scouting
disabled — predictable on a LAN with other zenoh peers. Mirrors Body's
desktop/chassis/transport.py.
"""

from __future__ import annotations

import json


def normalize_endpoint(endpoint: str) -> str:
    s = endpoint.strip()
    return s if "/" in s else f"tcp/{s}"


def open_session(endpoint: str):
    import zenoh

    ep = normalize_endpoint(endpoint)
    config = zenoh.Config()
    config.insert_json5("connect/endpoints", json.dumps([ep]))
    config.insert_json5("scouting/multicast/enabled", "false")
    config.insert_json5("scouting/gossip/enabled", "true")
    print(f"transport: opening zenoh session -> {ep}")
    return zenoh.open(config)
