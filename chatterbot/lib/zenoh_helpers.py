"""Zenoh session setup + pub/sub helpers for ChatterBot.

Adapted from the Body project (body/lib/zenoh_helpers.py). JSON helpers are used
for control + discrete messages; raw-bytes helpers exist for the future audio
stream (see DESIGN.md: audio goes as binary payloads, not base64-in-JSON).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import zenoh


def now() -> float:
    """Unix epoch seconds — the `ts` field carried by every message."""
    return time.time()


def repo_root() -> Path:
    """Repository root (directory containing config.json)."""
    return Path(__file__).resolve().parents[2]


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config.json; let ZENOH_CONNECT env var override the endpoint.

    The env override is how the desktop points itself at the Pi without editing
    the shared config, e.g. ``ZENOH_CONNECT=tcp/raspberrypi.local:7447``.
    """
    cfg_path = path or (repo_root() / "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    override = os.environ.get("ZENOH_CONNECT", "").strip()
    if override:
        data.setdefault("zenoh", {})["connect_endpoints"] = [_normalize(override)]
    return data


def _normalize(endpoint: str) -> str:
    """Accept a bare host:port and assume tcp/ if no protocol given."""
    s = endpoint.strip()
    return s if "/" in s else f"tcp/{s}"


def zenoh_config(cfg: dict[str, Any], multicast: bool = True) -> zenoh.Config:
    endpoints = cfg.get("zenoh", {}).get("connect_endpoints", ["tcp/127.0.0.1:7447"])
    endpoints = [_normalize(e) for e in endpoints]
    config = zenoh.Config()
    config.insert_json5("connect/endpoints", json.dumps(endpoints))
    if not multicast:
        # Predictable on a LAN with other zenoh peers: bind only to the
        # configured router instead of scouting.
        config.insert_json5("scouting/multicast/enabled", "false")
        config.insert_json5("scouting/gossip/enabled", "true")
    return config


def open_session(cfg: dict[str, Any], multicast: bool = True) -> zenoh.Session:
    return zenoh.open(zenoh_config(cfg, multicast=multicast))


def publish_json(session: zenoh.Session, key_expr: str, payload: dict[str, Any]) -> None:
    session.put(key_expr, json.dumps(payload))


def declare_subscriber_json(
    session: zenoh.Session,
    key_expr: str,
    handler: Callable[[str, dict[str, Any]], None],
) -> zenoh.Subscriber:
    def _cb(sample: zenoh.Sample) -> None:
        try:
            obj = json.loads(sample.payload.to_string())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if isinstance(obj, dict):
            handler(str(sample.key_expr), obj)

    return session.declare_subscriber(key_expr, _cb)


def publish_bytes(session: zenoh.Session, key_expr: str, payload: bytes) -> None:
    """Publish a raw binary payload (for the future audio stream)."""
    session.put(key_expr, payload)


def declare_subscriber_bytes(
    session: zenoh.Session,
    key_expr: str,
    handler: Callable[[str, bytes], None],
) -> zenoh.Subscriber:
    def _cb(sample: zenoh.Sample) -> None:
        handler(str(sample.key_expr), bytes(sample.payload.to_bytes()))

    return session.declare_subscriber(key_expr, _cb)
