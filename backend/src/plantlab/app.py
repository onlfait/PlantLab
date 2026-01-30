from __future__ import annotations

import json
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from plantlab.routes.health import router as health_router


def find_repo_root(start: Path) -> Path:
    current = start
    while current != current.parent:
        if (current / "README.md").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find PlantLab repo root")


HERE = Path(__file__).resolve()
REPO_ROOT = find_repo_root(HERE)

# Static served version (we’re using backend/static/index.html now)
BASE_DIR = Path(__file__).resolve().parent          # .../src/plantlab
STATIC_DIR = (BASE_DIR / "../../static").resolve()  # .../backend/static
FRONTEND_INDEX = STATIC_DIR / "index.html"

CONFIG_PATH = (REPO_ROOT / "config.json").resolve()

DEFAULT_CONFIG = {
    "alarm_threshold": 30,
    "sensors": [
        {"id": "S1", "label": "Série 1"},
        {"id": "S2", "label": "Série 2"},
        {"id": "S3", "label": "Série 3"},
        {"id": "S4", "label": "Série 4"},
    ],
}

app = FastAPI(title="PlantLab", version="0.1.0")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(health_router, prefix="/api")


def parse_iso_date(s: str) -> datetime:
    """
    Accepts 'YYYY-MM-DD' -> returns timezone-aware UTC datetime at 00:00:00.
    """
    d = datetime.strptime(s, "%Y-%m-%d")
    return d.replace(tzinfo=timezone.utc)


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def load_config() -> dict:
    """
    Loads config from ~/PlantLab/config.json.
    Falls back to DEFAULT_CONFIG if file missing or invalid.
    """
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            cfg = json.load(f)

        # Minimal validation + merge defaults
        if not isinstance(cfg, dict):
            return DEFAULT_CONFIG

        sensors = cfg.get("sensors", None)
        if not isinstance(sensors, list) or len(sensors) == 0:
            cfg["sensors"] = DEFAULT_CONFIG["sensors"]

        # Ensure sensor objects have id/label
        cleaned = []
        for s in cfg["sensors"]:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id", "")).strip().upper()
            lab = str(s.get("label", sid)).strip()
            if not sid:
                continue
            cleaned.append({"id": sid, "label": lab if lab else sid})

        if not cleaned:
            cleaned = DEFAULT_CONFIG["sensors"]
        cfg["sensors"] = cleaned

        thr = cfg.get("alarm_threshold", DEFAULT_CONFIG["alarm_threshold"])
        try:
            cfg["alarm_threshold"] = int(thr)
        except Exception:
            cfg["alarm_threshold"] = DEFAULT_CONFIG["alarm_threshold"]

        return cfg

    except Exception:
        return DEFAULT_CONFIG


def get_sensors() -> list[dict]:
    return load_config()["sensors"]


def get_alarm_threshold() -> int:
    return int(load_config().get("alarm_threshold", DEFAULT_CONFIG["alarm_threshold"]))


@app.get("/api/config")
def config():
    cfg = load_config()
    return {
        "alarm_threshold": int(cfg.get("alarm_threshold", 30)),
        "sensors": cfg.get("sensors", []),
    }


@app.get("/api/sensors")
def sensors():
    return {"sensors": get_sensors()}


@app.get("/api/latest")
def latest():
    sensors = get_sensors()
    t = time.time()
    values = []

    for idx, s in enumerate(sensors):
        base = 55 + 18 * math.sin(t / 60.0 + idx)
        noise = random.uniform(-3, 3)
        val = max(0, min(100, base + noise))
        values.append({
            "sensor_id": s["id"],
            "label": s["label"],
            "percent": round(val, 1),
        })

    return {"ts": int(t), "values": values}


@app.get("/api/history")
def history(
    minutes: int = 180,
    start: Optional[str] = Query(default=None, description="YYYY-MM-DD (UTC)"),
    end: Optional[str] = Query(default=None, description="YYYY-MM-DD (UTC), inclusive end day"),
):
    """
    Returns:
      {"sensors": [...], "series": [{"ts": <epoch>, "S1": <pct>, ...}, ...]}
    Either:
      - minutes=N (default)
      - OR start=YYYY-MM-DD&end=YYYY-MM-DD (overrides minutes)
    """
    sensors = get_sensors()
    now = int(time.time())

    # If dates provided: build a range from start 00:00 to end 23:59:59 UTC
    if start and end:
        try:
            start_dt = parse_iso_date(start)
            end_dt = parse_iso_date(end)
        except ValueError:
            return JSONResponse({"error": "Invalid date format, expected YYYY-MM-DD"}, status_code=400)

        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp() + 24 * 3600 - 1)

        # Safety: cap max range to 31 days for demo
        max_span = 31 * 24 * 3600
        if end_ts < start_ts:
            return JSONResponse({"error": "end must be >= start"}, status_code=400)
        if (end_ts - start_ts) > max_span:
            return JSONResponse({"error": "Range too large (max 31 days for demo)"}, status_code=400)

        # sampling: 60s per point for date ranges to keep payload reasonable
        step = 60
        rows = []
        ts = start_ts
        while ts <= end_ts:
            row = {"ts": ts}
            for idx, s in enumerate(sensors):
                base = 55 + 18 * math.sin(ts / 1800.0 + idx)
                noise = random.uniform(-2, 2)
                drift = -0.00002 * (ts - start_ts)  # slight drift across whole range
                val = max(0, min(100, base + drift + noise))
                row[s["id"]] = round(val, 1)
            rows.append(row)
            ts += step

        return {"sensors": sensors, "series": rows}

    # Otherwise: minutes mode
    minutes = clamp(minutes, 10, 24 * 60)
    rows = []
    for m in range(minutes, -1, -1):
        ts = now - m * 60
        row = {"ts": ts}
        for idx, s in enumerate(sensors):
            base = 55 + 18 * math.sin(ts / 1800.0 + idx)
            drift = -0.02 * m
            noise = random.uniform(-2, 2)
            val = max(0, min(100, base + drift + noise))
            row[s["id"]] = round(val, 1)
        rows.append(row)

    return {"sensors": sensors, "series": rows}


@app.get("/api/history/{sensor_id}")
def history_one(sensor_id: str, minutes: int = 720):
    sensors = get_sensors()
    sensor_id = sensor_id.upper()
    ids = {s["id"] for s in sensors}
    if sensor_id not in ids:
        return JSONResponse({"error": "unknown sensor"}, status_code=404)

    minutes = clamp(minutes, 10, 24 * 60)
    now = int(time.time())
    rows = []

    idx = [s["id"] for s in sensors].index(sensor_id)
    for m in range(minutes, -1, -1):
        ts = now - m * 60
        base = 55 + 18 * math.sin(ts / 1800.0 + idx)
        drift = -0.02 * m
        noise = random.uniform(-2, 2)
        val = max(0, min(100, base + drift + noise))
        rows.append({"ts": ts, "value": round(max(0, min(100, val)), 1)})

    label = next(s["label"] for s in sensors if s["id"] == sensor_id)
    return {"sensor": {"id": sensor_id, "label": label}, "series": rows}


@app.get("/")
def index():
    if FRONTEND_INDEX.exists():
        return FileResponse(str(FRONTEND_INDEX))
    return {"message": "index.html not found", "expected_path": str(FRONTEND_INDEX)}
