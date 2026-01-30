from __future__ import annotations

from datetime import datetime, timezone
from random import Random

_rng = Random(42)

def get_fake_sensors() -> dict:
    """Return stable-ish fake sensor values for early UI testing."""
    now = datetime.now(timezone.utc).isoformat()
    # Simple pseudo values (keep them plausible)
    humidity = round(35 + _rng.random() * 30, 1)     # 35..65 %
    temperature = round(18 + _rng.random() * 8, 1)   # 18..26 °C
    moisture = round(0.25 + _rng.random() * 0.5, 3)  # 0..1-ish

    return {
        "ts": now,
        "sensors": [
            {"id": "plant-1", "humidity_pct": humidity, "temp_c": temperature, "moisture": moisture},
        ],
    }
