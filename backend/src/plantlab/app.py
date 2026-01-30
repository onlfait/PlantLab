from __future__ import annotations

import math
import random
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from plantlab.routes.health import router as health_router


def find_repo_root(start: Path) -> Path:
    """Walk up directories until we find the repo root (with README.md)."""
    current = start
    while current != current.parent:
        if (current / "README.md").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find PlantLab repo root")


HERE = Path(__file__).resolve()
REPO_ROOT = find_repo_root(HERE)

BASE_DIR = HERE.parent  # .../backend/src/plantlab
STATIC_DIR = (BASE_DIR / "../../static").resolve()  # .../backend/static
INDEX_HTML = (STATIC_DIR / "index.html").resolve()

app = FastAPI(title="PlantLab", version="0.1.0")

# Static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Health router
app.include_router(health_router, prefix="/api")

# Demo sensors (rename labels later to Radis, Tomate, Témoin, Laitue)
SENSORS = [
    {"id": "S1", "label": "Série 1"},
    {"id": "S2", "label": "Série 2"},
    {"id": "S3", "label": "Série 3"},
    {"id": "S4", "label": "Série 4"},
]


@app.get("/")
def index():
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return JSONResponse(
        {
            "message": "index.html not found",
            "expected_path": str(INDEX_HTML),
        },
        status_code=404,
    )


@app.get("/api/sensors")
def api_sensors():
    return {"sensors": SENSORS}


@app.get("/api/latest")
def api_latest():
    t = time.time()
    values = []
    for idx, s in enumerate(SENSORS):
        base = 55 + 18 * math.sin(t / 60.0 + idx)
        noise = random.uniform(-3, 3)
        val = max(0, min(100, base + noise))
        values.append(
            {
                "sensor_id": s["id"],
                "label": s["label"],
                "percent": round(val, 1),
            }
        )
    return {"ts": int(t), "values": values}


@app.get("/api/history")
def api_history(minutes: int = 180):
    minutes = max(10, min(minutes, 24 * 60))
    now = int(time.time())
    rows = []

    for m in range(minutes, -1, -1):
        ts = now - m * 60
        row = {"ts": ts}
        for idx, s in enumerate(SENSORS):
            base = 55 + 18 * math.sin(ts / 1800.0 + idx)
            drift = -0.02 * m
            noise = random.uniform(-2, 2)
            val = max(0, min(100, base + drift + noise))
            row[s["id"]] = round(val, 1)
        rows.append(row)

    return {"sensors": SENSORS, "series": rows}


@app.get("/api/history/{sensor_id}")
def api_history_one(sensor_id: str, minutes: int = 720):
    sensor_id = sensor_id.upper()
    ids = [s["id"] for s in SENSORS]
    if sensor_id not in ids:
        return JSONResponse({"error": "unknown sensor"}, status_code=404)

    minutes = max(10, min(minutes, 24 * 60))
    now = int(time.time())
    idx = ids.index(sensor_id)

    rows = []
    for m in range(minutes, -1, -1):
        ts = now - m * 60
        base = 55 + 18 * math.sin(ts / 1800.0 + idx)
        drift = -0.02 * m
        noise = random.uniform(-2, 2)
        val = max(0, min(100, base + drift + noise))
        rows.append({"ts": ts, "value": round(max(0, min(100, val)), 1)})

    label = next(s["label"] for s in SENSORS if s["id"] == sensor_id)
    return {"sensor": {"id": sensor_id, "label": label}, "series": rows}
