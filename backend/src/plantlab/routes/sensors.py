from datetime import datetime, timedelta, timezone
from random import Random

from fastapi import APIRouter

from plantlab.services.fake_data import get_fake_sensors


router = APIRouter()


@router.get("/sensors")
def sensors() -> dict:
    return get_fake_sensors()


@router.get("/history")
def history(minutes: int = 60, step_s: int = 30) -> dict:
    rng = Random(42)
    now = datetime.now(timezone.utc)

    points = []
    t = now - timedelta(minutes=minutes)

    while t <= now:
        humidity = round(45 + (rng.random() - 0.5) * 10, 1)  # ~40..50%
        points.append(
            {
                "ts": t.isoformat(),
                "humidity_pct": humidity,
            }
        )
        t += timedelta(seconds=step_s)

    return {"series": points}
