"""
Static alert map for the HTML heat card (Feature I + Amazon Location Service GetStaticMap).

Once per city per alert day, the daily job renders a small map: the highest-risk zones as numbered
red pins and the nearest open cool refuges in blue. The JPEG is stored in the frontend bucket and
served through CloudFront at <site>/alert-maps/<city>/<date>.jpg, so the link in an email does not
expire (a presigned URL made with Lambda credentials would stop working within hours).

The call is signed with the function's IAM role (no browser API key in emails). Needs
STATIC_MAP_ENABLED=true (set when the stack is deployed with the Location map switch) and
FRONTEND_BUCKET. Never raises: without them, or on any error, the card is sent without a map.

API reference: GET /v2/static/{FileName} (geo-maps GetStaticMap). FileName is "map" or "map@2x";
the response is a JPEG. Markers use CompactOverlay: "point:lon,lat;label=..;color=..|point:...".
"""

from __future__ import annotations

import os
from datetime import date

from api import aws

WIDTH, HEIGHT = 560, 320            # GetStaticMap allows 64–1400 px per side
MAX_OVERLAY = 5000                  # CompactOverlay length limit
ZONE_COLOUR, REFUGE_COLOUR = "#c81e3a", "#1f6feb"


def enabled() -> bool:
    return os.environ.get("STATIC_MAP_ENABLED") == "true" and bool(os.environ.get("FRONTEND_BUCKET"))


def overlay(zones: list[dict], refuges: list[dict]) -> str:
    """CompactOverlay string: numbered red zone pins, then blue refuge pins (dropped if too long)."""
    parts = [f"point:{z['lon']:.5f},{z['lat']:.5f};label={z['rank']};size=medium;color={ZONE_COLOUR}"
             for z in zones]
    for r in refuges:
        nxt = f"point:{r['lon']:.5f},{r['lat']:.5f};size=small;color={REFUGE_COLOUR}"
        if len("|".join(parts + [nxt])) > MAX_OVERLAY:
            break
        parts.append(nxt)
    return "|".join(parts)


def bounding_box(points: list[tuple[float, float]], pad_deg: float = 0.01) -> str:
    """'west,south,east,north' around the points (BoundingBox format: SW corner then NE corner)."""
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (f"{min(lons) - pad_deg:.5f},{min(lats) - pad_deg:.5f},"
            f"{max(lons) + pad_deg:.5f},{max(lats) + pad_deg:.5f}")


def map_points(city_id: str, top_wards: list[dict], per_zone: int = 2) -> tuple[list[dict], list[dict]]:
    """Top-5 zones and, for each, its nearest refuges that are not reported full or closed."""
    from api import shelters
    from models.risk import nearest_cooling_spots
    zones = [w for w in top_wards[:5] if w.get("lat") is not None and w.get("lon") is not None]
    seen, refuges = set(), []
    for z in zones:
        near = [s for s in nearest_cooling_spots(city_id, float(z["lat"]), float(z["lon"]), 12)
                if s.get("type") in shelters.REFUGE_TYPES]
        # unlike the citizen list (which falls back to showing something), the map never shows
        # a refuge reported full or closed
        picked = [p for p in shelters.annotate(city_id, near) if p["status"] not in shelters.UNAVAILABLE][:per_zone]
        for s in picked:
            key = (round(s["lat"], 5), round(s["lon"], 5))
            if key not in seen:
                seen.add(key)
                refuges.append(s)
    return zones, refuges


def render(city_id: str, top_wards: list[dict], day: str | None = None) -> str | None:
    """Render, store and return the public URL of today's alert map, or None."""
    if not enabled():
        return None
    try:
        from api.email_alerts import site_url
        base = site_url()
        if not base:
            return None
        zones, refuges = map_points(city_id, top_wards)
        if not zones:
            return None
        points = [(float(z["lon"]), float(z["lat"])) for z in zones] + [(r["lon"], r["lat"]) for r in refuges]
        resp = aws.client("geo-maps").get_static_map(
            FileName="map", Width=WIDTH, Height=HEIGHT,
            BoundingBox=bounding_box(points), Padding=30,
            CompactOverlay=overlay(zones, refuges),
            Style=os.environ.get("STATIC_MAP_STYLE", "Satellite"),   # the developer guide lists Satellite for static maps
            PoliticalView="IND", ScaleBarUnit="Kilometers")
        image = resp["Blob"].read()
        key = f"alert-maps/{city_id}/{day or date.today().isoformat()}.jpg"
        aws.client("s3").put_object(Bucket=os.environ["FRONTEND_BUCKET"], Key=key, Body=image,
                                    ContentType="image/jpeg", CacheControl="public, max-age=86400")
        return f"{base}/{key}"
    except Exception as e:  # the map is a bonus; the alert must still go out
        print(f"static map failed for {city_id}: {type(e).__name__}: {e}")
        return None
