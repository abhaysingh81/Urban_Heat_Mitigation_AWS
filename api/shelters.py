"""
Cool refuges and their live status (Feature L: live operations).

A cool refuge is an indoor public place from the city's OpenStreetMap cooling-spot list that
people can shelter in (hospital, clinic, shelter, community centre, library). Ward officers set
each one open / busy / full / closed; the citizen page then stops sending people to a refuge
that is full or closed. A status older than STALE_HOURS reads as "unknown" so an old "open"
is never trusted on a heatwave afternoon. Parks and drinking-water points are not tracked.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np

from api import store
from models.ward_factors import REFUGE_TYPES
from pipeline.config import city_cooling_spots_file

STALE_HOURS = 12
UNAVAILABLE = ("full", "closed")


def spot_id(city_id: str, spot: dict) -> str:
    """Stable id from the place itself (cooling-spot files carry no ids)."""
    key = f"{city_id}|{spot['type']}|{float(spot['lat']):.5f}|{float(spot['lon']):.5f}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


@lru_cache(maxsize=8)
def _refuges(city_id: str, mtime: float) -> tuple:
    f = city_cooling_spots_file(city_id)
    spots = json.loads(f.read_text()) if f.exists() else []
    return tuple({**s, "id": spot_id(city_id, s)} for s in spots if s.get("type") in REFUGE_TYPES)


def refuges(city_id: str) -> list[dict]:
    f = city_cooling_spots_file(city_id)
    return [dict(s) for s in _refuges(city_id, f.stat().st_mtime if f.exists() else 0)]


def live_status(doc: dict | None, now: datetime | None = None) -> dict:
    if not doc:
        return {"status": "unknown", "updated_at": None, "stale": False}
    now = now or datetime.now(timezone.utc)
    age_h = (now - datetime.fromisoformat(doc["updated_at"])).total_seconds() / 3600
    if age_h > STALE_HOURS:
        return {"status": "unknown", "last_status": doc["status"], "updated_at": doc["updated_at"], "stale": True}
    return {"status": doc["status"], "updated_at": doc["updated_at"], "stale": False}


def annotate(city_id: str, spots: list[dict]) -> list[dict]:
    """Add id + live status to the refuges in `spots`; other places get status None (not tracked)."""
    statuses = store.list_shelter_statuses(city_id)
    out = []
    for s in spots:
        s = dict(s)
        if s.get("type") in REFUGE_TYPES:
            s["id"] = spot_id(city_id, s)
            s.update(live_status(statuses.get(s["id"])))
        else:
            s["status"] = None
        out.append(s)
    return out


def recommend(city_id: str, nearest: list[dict], k: int = 3) -> tuple[list[dict], int]:
    """Nearest places with full / closed refuges moved out of the way. Returns (places, n_skipped)."""
    places = annotate(city_id, nearest)
    usable = [p for p in places if p.get("status") not in UNAVAILABLE]
    skipped = len(places) - len(usable)
    return (usable[:k] if usable else places[:k]), skipped


def distances_m(lat: float, lon: float, places: list[dict]) -> np.ndarray:
    if not places:
        return np.zeros(0)
    la, lo = np.radians(lat), np.radians(lon)
    arr = np.radians(np.array([[p["lat"], p["lon"]] for p in places], dtype=float))
    a = np.sin((arr[:, 0] - la) / 2) ** 2 + np.cos(la) * np.cos(arr[:, 0]) * np.sin((arr[:, 1] - lo) / 2) ** 2
    return 2 * 6371000 * np.arcsin(np.sqrt(a))
