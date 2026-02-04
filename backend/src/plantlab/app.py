from __future__ import annotations

import json
import math
import random
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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

app = FastAPI(title="PlantLab", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(health_router, prefix="/api")

# Consider a sensor offline if no data for this many seconds.
# Rule of thumb: ~3x your ESP post interval.
OFFLINE_AFTER_S = 180

# ---------------------------
# Helpers
# ---------------------------
def parse_iso_date(s: str) -> datetime:
    d = datetime.strptime(s, "%Y-%m-%d")
    return d.replace(tzinfo=timezone.utc)


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def now_ts() -> int:
    return int(time.time())


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            cfg = json.load(f)

        if not isinstance(cfg, dict):
            return DEFAULT_CONFIG

        sensors = cfg.get("sensors")
        if not isinstance(sensors, list) or not sensors:
            sensors = DEFAULT_CONFIG["sensors"]

        cleaned = []
        for s in sensors:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id", "")).strip().upper()
            lab = str(s.get("label", sid)).strip()
            if sid:
                cleaned.append({"id": sid, "label": lab if lab else sid})

        if not cleaned:
            cleaned = DEFAULT_CONFIG["sensors"]

        thr = cfg.get("alarm_threshold", DEFAULT_CONFIG["alarm_threshold"])
        try:
            thr_i = int(thr)
        except Exception:
            thr_i = int(DEFAULT_CONFIG["alarm_threshold"])

        return {"alarm_threshold": thr_i, "sensors": cleaned}

    except Exception:
        return DEFAULT_CONFIG


def get_sensors() -> list[dict]:
    return load_config()["sensors"]


def sensor_ids_from_config() -> set[str]:
    return {s["id"] for s in get_sensors()}


# ---------------------------
# In-memory real-data store
# ---------------------------
@dataclass
class Sample:
    ts: int
    percent: float
    adc: Optional[int] = None


MAX_POINTS_PER_SENSOR = 8000
STORE: dict[str, deque[Sample]] = {}


def ensure_store_keys() -> None:
    ids = sensor_ids_from_config()

    for sid in ids:
        if sid not in STORE:
            STORE[sid] = deque(maxlen=MAX_POINTS_PER_SENSOR)

    for sid in list(STORE.keys()):
        if sid not in ids:
            del STORE[sid]


def have_real_data() -> bool:
    ensure_store_keys()
    return any(len(q) > 0 for q in STORE.values())


# ---------------------------
# Ingest payload
# ---------------------------
class IngestPayload(BaseModel):
    sensor_id: str = Field(..., description="S1, S2, ...")
    percent: float = Field(..., ge=0.0, le=100.0)
    adc: Optional[int] = Field(None, description="raw/avg ADC value (optional)")
    ts: Optional[int] = Field(None, description="device timestamp (optional). Server time is authoritative.")


# ---------------------------
# Config endpoints
# ---------------------------
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


# ---------------------------
# ESP32 -> Pi ingestion endpoint
# ---------------------------
@app.post("/api/ingest")
def ingest(payload: IngestPayload):
    ensure_store_keys()

    sid = payload.sensor_id.strip().upper()
    if sid not in STORE:
        return JSONResponse(
            {"error": "unknown sensor_id", "sensor_id": sid, "known": sorted(STORE.keys())},
            status_code=400,
        )

    ts = now_ts()
    STORE[sid].append(Sample(ts=ts, percent=float(payload.percent), adc=payload.adc))
    return {"ok": True, "sensor_id": sid, "stored_ts": ts}


# ---------------------------
# Latest
# ---------------------------
@app.get("/api/latest")
def latest():
    sensors = get_sensors()
    ensure_store_keys()

    t = now_ts()

    if have_real_data():
        values = []
        for s in sensors:
            sid = s["id"]
            q = STORE.get(sid)

            if q and len(q) > 0:
                last = q[-1]
                age = t - int(last.ts)
                online = age <= OFFLINE_AFTER_S

                values.append({
                    "sensor_id": sid,
                    "label": s["label"],
                    "percent": round(last.percent, 1) if online else None,
                    "last_seen": int(last.ts),
                    "status": "online" if online else "offline",
                    "age_s": int(age),
                })
            else:
                values.append({
                    "sensor_id": sid,
                    "label": s["label"],
                    "percent": None,
                    "last_seen": None,
                    "status": "offline",
                    "age_s": None,
                })

        return {"ts": t, "values": values}

    # simulation fallback
    t_float = time.time()
    values = []
    for idx, s in enumerate(sensors):
        base = 55 + 18 * math.sin(t_float / 60.0 + idx)
        noise = random.uniform(-3, 3)
        val = max(0, min(100, base + noise))
        values.append({
            "sensor_id": s["id"],
            "label": s["label"],
            "percent": round(val, 1),
            "last_seen": t,
            "status": "online",
            "age_s": 0,
        })
    return {"ts": int(t_float), "values": values}


# ---------------------------
# History helpers (real data)
# ---------------------------
def minute_bucket_history(minutes: int) -> dict:
    sensors = get_sensors()
    ensure_store_keys()

    minutes = clamp(minutes, 10, 24 * 60)
    end_ts = now_ts()
    start_ts = end_ts - minutes * 60

    per_sensor = {sid: list(STORE[sid]) for sid in STORE.keys()}

    rows = []
    for ts in range(start_ts, end_ts + 1, 60):
        row = {"ts": ts}
        for s in sensors:
            sid = s["id"]
            samples = per_sensor.get(sid, [])
            val = None
            for smp in reversed(samples):
                if smp.ts <= ts:
                    val = round(smp.percent, 1)
                    break
            row[sid] = val
        rows.append(row)

    return {"sensors": sensors, "series": rows}


def minute_bucket_history_one(sensor_id: str, minutes: int):
    sensors = get_sensors()
    ensure_store_keys()

    sid = sensor_id.strip().upper()
    ids = {s["id"] for s in sensors}
    if sid not in ids:
        return JSONResponse({"error": "unknown sensor"}, status_code=404)

    minutes = clamp(minutes, 10, 24 * 60)
    end_ts = now_ts()
    start_ts = end_ts - minutes * 60

    samples = list(STORE.get(sid, deque()))
    rows = []
    for ts in range(start_ts, end_ts + 1, 60):
        val = None
        for smp in reversed(samples):
            if smp.ts <= ts:
                val = round(smp.percent, 1)
                break
        rows.append({"ts": ts, "value": val})

    label = next(s["label"] for s in sensors if s["id"] == sid)
    return {"sensor": {"id": sid, "label": label}, "series": rows}


# ---------------------------
# History
# ---------------------------
@app.get("/api/history")
def history(
    minutes: int = 180,
    start: Optional[str] = Query(default=None, description="YYYY-MM-DD (UTC)"),
    end: Optional[str] = Query(default=None, description="YYYY-MM-DD (UTC), inclusive end day"),
):
    sensors = get_sensors()
    ensure_store_keys()
    now = now_ts()

    if start and end:
        # simulated date-range (for now)
        try:
            start_dt = parse_iso_date(start)
            end_dt = parse_iso_date(end)
        except ValueError:
            return JSONResponse({"error": "Invalid date format, expected YYYY-MM-DD"}, status_code=400)

        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp() + 24 * 3600 - 1)

        max_span = 31 * 24 * 3600
        if end_ts < start_ts:
            return JSONResponse({"error": "end must be >= start"}, status_code=400)
        if (end_ts - start_ts) > max_span:
            return JSONResponse({"error": "Range too large (max 31 days for demo)"}, status_code=400)

        step = 60
        rows = []
        ts = start_ts
        while ts <= end_ts:
            row = {"ts": ts}
            for idx, s in enumerate(sensors):
                base = 55 + 18 * math.sin(ts / 1800.0 + idx)
                noise = random.uniform(-2, 2)
                drift = -0.00002 * (ts - start_ts)
                val = max(0, min(100, base + drift + noise))
                row[s["id"]] = round(val, 1)
            rows.append(row)
            ts += step

        return {"sensors": sensors, "series": rows}

    minutes = clamp(minutes, 10, 24 * 60)

    if have_real_data():
        return minute_bucket_history(minutes)

    # simulation fallback
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
    ensure_store_keys()

    sid = sensor_id.strip().upper()
    ids = {s["id"] for s in sensors}
    if sid not in ids:
        return JSONResponse({"error": "unknown sensor"}, status_code=404)

    minutes = clamp(minutes, 10, 24 * 60)
    now = now_ts()

    if have_real_data():
        return minute_bucket_history_one(sid, minutes)

    rows = []
    idx = [s["id"] for s in sensors].index(sid)
    for m in range(minutes, -1, -1):
        ts = now - m * 60
        base = 55 + 18 * math.sin(ts / 1800.0 + idx)
        drift = -0.02 * m
        noise = random.uniform(-2, 2)
        val = max(0, min(100, base + drift + noise))
        rows.append({"ts": ts, "value": round(max(0, min(100, val)), 1)})

    label = next(s["label"] for s in sensors if s["id"] == sid)
    return {"sensor": {"id": sid, "label": label}, "series": rows}


@app.get("/")
def index():
    if FRONTEND_INDEX.exists():
        return FileResponse(str(FRONTEND_INDEX))
    return {"message": "index.html not found", "expected_path": str(FRONTEND_INDEX)}
