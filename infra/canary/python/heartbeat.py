"""
HeatRelief uptime canary (Amazon CloudWatch Synthetics, Python runtime).

Every few minutes it does what a citizen's phone does: API health, today's risk, the citizen
payload for a fixed point, and the citizen web page. Any failure raises, which marks the run as
failed; the CloudWatchSynthetics SuccessPercent metric then drives an alarm to the ops topic.
Only the standard library is used (urllib), so nothing has to be bundled.

Packaged by scripts/deploy.sh as a zip with this file at python/heartbeat.py
(handler "heartbeat.handler", per the Synthetics Python packaging rules).
Settings come from the canary's environment: API_URL, SITE_URL, CITY, CITY_LAT, CITY_LON.
"""

import json
import os
import urllib.request

try:  # present in the Synthetics runtime; the script also runs without it (local tests)
    from aws_synthetics.common import synthetics_logger as log
except ImportError:  # pragma: no cover
    import logging
    log = logging.getLogger("heartbeat")

LEVELS = ("green", "yellow", "orange", "red")


def fetch(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "heatrelief-canary/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # HTTP errors raise HTTPError
        if resp.status != 200:
            raise Exception(f"{url} answered HTTP {resp.status}")
        return resp.read()


def check(api: str, site: str, city: str, lat: str, lon: str) -> list[str]:
    done = []
    health = json.loads(fetch(f"{api}/health"))
    if health.get("status") != "ok":
        raise Exception(f"health check said {health}")
    done.append("health")

    today = json.loads(fetch(f"{api}/api/v1/risk/today?city={city}"))
    if today.get("alert_level") not in LEVELS:
        raise Exception(f"risk/today has no valid alert level: {today.get('alert_level')}")
    done.append(f"risk-today ({today['alert_level']}{', stale' if today.get('stale') else ''})")

    citizen = json.loads(fetch(f"{api}/api/v1/citizen?city={city}&lat={lat}&lon={lon}"))
    if not citizen.get("message_en") or not isinstance(citizen.get("nearest_cooling_spots"), list):
        raise Exception("citizen payload is missing the advice or the cooling places")
    done.append(f"citizen ({len(citizen['nearest_cooling_spots'])} places)")

    if site:
        page = fetch(f"{site}/citizen?city={city}")
        if b'id="root"' not in page:
            raise Exception("citizen page did not return the app shell")
        done.append("citizen page")
    return done


def handler(event, context):
    api = os.environ["API_URL"].rstrip("/")
    site = os.environ.get("SITE_URL", "").rstrip("/")
    done = check(api, site, os.environ.get("CITY", "new_delhi"),
                 os.environ.get("CITY_LAT", "28.6315"), os.environ.get("CITY_LON", "77.2167"))
    log.info("heatrelief canary passed: " + ", ".join(done))
    return "passed: " + ", ".join(done)
