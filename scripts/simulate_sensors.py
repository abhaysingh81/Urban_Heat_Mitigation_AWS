#!/usr/bin/env python3
"""Pretend to be street temperature sensors (Feature G), for demos and testing.

On AWS it publishes MQTT messages to AWS IoT Core exactly where real devices would
(heatrelief/sensors/<city>/<sensor id>), so the IoT rules, the tables and the alarm Lambda are
exercised for real. It uses your AWS credentials instead of a device certificate.

    python scripts/simulate_sensors.py --city new_delhi                 # 8 sensors, 5 rounds, 10 s apart
    python scripts/simulate_sensors.py --city mumbai --hot              # readings hot enough to alarm
    python scripts/simulate_sensors.py --city jaipur --local            # no AWS: write to the local store

Needs the stack deployed with ENABLE_IOT_SENSORS=1 (not for --local).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.config import CITIES, REAL_CITIES  # noqa: E402


def sensors_for(city: str, count: int, seed: int = 7) -> list[dict]:
    """Stable fake sensor positions around the city centre (same ids and places on every run)."""
    rng = random.Random(f"{city}-{seed}")
    lon, lat = CITIES[city]["center"]
    return [{"sensor_id": f"{city.replace('_', '')}-{i + 1:02d}",
             "lat": round(lat + rng.uniform(-0.06, 0.06), 5), "lon": round(lon + rng.uniform(-0.06, 0.06), 5),
             "bias": rng.uniform(-1.5, 2.5)} for i in range(count)]


def reading(sensor: dict, hot: bool) -> dict:
    base = 46.5 if hot else 37.0
    return {"temp_c": round(base + sensor["bias"] + random.uniform(-0.6, 0.6), 1),
            "humidity": round(random.uniform(22, 48)), "lat": sensor["lat"], "lon": sensor["lon"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--city", default="new_delhi", choices=REAL_CITIES)
    ap.add_argument("--count", type=int, default=8, help="number of sensors")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--interval", type=float, default=10.0, help="seconds between rounds (real sensors: 60)")
    ap.add_argument("--hot", action="store_true", help="heatwave readings (trigger the operator alarm)")
    ap.add_argument("--local", action="store_true", help="write to the local runtime store, no AWS")
    ap.add_argument("--region", default="us-east-1")
    a = ap.parse_args()
    sensors = sensors_for(a.city, a.count)

    if a.local:
        from api import store
        publish = lambda s, r: store.put_sensor_reading(  # noqa: E731
            {**r, "city": a.city, "sensor_id": s["sensor_id"], "received_at": int(time.time() * 1000)})
    else:
        import boto3
        endpoint = boto3.client("iot", region_name=a.region).describe_endpoint(endpointType="iot:Data-ATS")
        data = boto3.client("iot-data", region_name=a.region, endpoint_url=f"https://{endpoint['endpointAddress']}")
        publish = lambda s, r: data.publish(  # noqa: E731
            topic=f"heatrelief/sensors/{a.city}/{s['sensor_id']}", qos=1, payload=json.dumps(r))

    for n in range(a.rounds):
        for s in sensors:
            r = reading(s, a.hot)
            publish(s, r)
        print(f"round {n + 1}/{a.rounds}: {len(sensors)} readings for {a.city}"
              f" ({'local store' if a.local else 'AWS IoT Core'}), last {r['temp_c']} °C")
        if n + 1 < a.rounds:
            time.sleep(a.interval)


if __name__ == "__main__":
    main()
