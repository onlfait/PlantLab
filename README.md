# PlantLab — Soil Moisture Dashboard (offline kiosk)

PlantLab is a small self-hosted dashboard to visualize soil moisture for multiple plant pots in a workshop/exhibition setting. It runs on a Raspberry Pi as a local web server, can operate as a Wi-Fi access point for an iPad kiosk, and exposes simple API endpoints for live values and history (demo data for now, real sensors later).

## Features

- **Offline-first:** runs locally on a Raspberry Pi, no internet required for viewing
- **Kiosk-friendly:** designed for an iPad in fullscreen / guided access
- **Multiple pots:** 4 series by default (easy to rename)
- **Alerts:** visual warning when humidity is below a configurable threshold
- **Interactive charts:** toggles per pot + selectable ranges (1h/6h/12h/24h + date range)
- **Simple config:** rename pots and change alarm threshold via `config.json` (no code edits)

## Architecture (current)

Raspberry Pi runs:

- FastAPI + Uvicorn web server (`/`, `/static/*`, `/api/*`)
- demo data generator (live + history)

Optional network mode:

- Raspberry Pi can act as Wi-Fi Access Point (PlantLab SSID) for kiosk clients
- Raspberry Pi can also connect to an upstream network using a second Wi-Fi interface (USB dongle)

## Repository layout

```
PlantLab/
├─ backend/
│  ├─ src/plantlab/app.py          # FastAPI app (API + static + demo data)
│  ├─ static/
│  │  ├─ index.html                # main dashboard
│  │  ├─ pot.html                  # per-pot page
│  │  ├─ Chart.min.js              # Chart.js bundle
│  │  └─ plantlab-logo.svg
│  └─ ...
├─ frontend/                       # (optional / experimental)
├─ config.json                     # local configuration (not code)
├─ deploy/                         # install/service scripts (optional)
└─ README.md
```

## API endpoints

### `GET /api/health`
Simple health check for monitoring/debugging.

### `GET /api/config`
Returns `alarm_threshold` and sensors labels.

### `GET /api/sensors`
Returns sensors list (id + label).

### `GET /api/latest`
Returns latest values for each sensor (demo).

### `GET /api/history?minutes=360`
Returns time series for all sensors for the last N minutes.

### `GET /api/history?start=YYYY-MM-DD&end=YYYY-MM-DD`
Returns time series for a date range (UTC) (demo, capped to 31 days).

### `GET /api/history/{sensor_id}?minutes=720`
Returns a single sensor time series.

## Configuration

Create / edit `config.json` at the repo root:

```json
{
  "alarm_threshold": 30,
  "sensors": [
    {"id": "S1", "label": "Radis"},
    {"id": "S2", "label": "Tomate"},
    {"id": "S3", "label": "Témoin"},
    {"id": "S4", "label": "Laitue"}
  ]
}
```

- **`alarm_threshold`:** humidity percent under which the UI shows an alert
- **`sensors`:** list of sensors (IDs must match what you use later with real hardware)

Changes are picked up by the backend automatically (reload the page).

## Quick start (development)

### Requirements

- Python 3.11+ (works on Raspberry Pi OS / Debian)
- `uv` (recommended) for dependency and venv management

### Install

```bash
git clone <your-repo-url>
cd PlantLab/backend

# Create venv + install deps
uv sync
```

### Run locally

```bash
uv run uvicorn plantlab.app:app --app-dir src --host 0.0.0.0 --port 8000
```

Open: `http://<pi-ip>:8000/`

## Running as a systemd service (Raspberry Pi)

This is the recommended mode for kiosk/exhibition usage.

Create a service file:

```bash
sudo nano /etc/systemd/system/plantlab-web.service
```

Example:

```ini
[Unit]
Description=PlantLab Web (FastAPI via uv)
After=network-online.target
Wants=network-online.target

[Service]
User=plantlab
WorkingDirectory=/home/plantlab/PlantLab/backend
ExecStart=/home/plantlab/.local/bin/uv run uvicorn plantlab.app:app --app-dir src --host 0.0.0.0 --port 8000
Restart=always
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable + start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable plantlab-web
sudo systemctl start plantlab-web
sudo systemctl status plantlab-web
```

Logs:

```bash
sudo journalctl -u plantlab-web -f
```

## Kiosk mode (iPad)

Best experience:

- Add the dashboard to Home Screen (Safari → Share → "Add to Home Screen")
- Enable Guided Access (optional) to lock navigation

Tip for cache refresh during development:

- Open `http://<pi-ip>:8000/?v=10` (increment `v` when needed)

## Network mode (Wi-Fi Access Point)

PlantLab can be used in environments where you don't control the local network.

Typical setup:

- `wlan1` (USB dongle) connects to the existing Wi-Fi (upstream)
- `wlan0` (Pi built-in) provides an Access Point (SSID: PlantLab) for the iPad

Implementation details depend on the OS image and your constraints; this repo focuses on the web stack. If you want, document your AP setup steps in `docs/network-access-point.md` (recommended).

## Roadmap (next steps)

- Replace demo generator with real sensor ingestion:
  - ESP32 → HTTP/MQTT → Raspberry Pi
  - or direct ADC readings if wiring allows
- Persist raw data (CSV/SQLite) and provide download for students
- Add "visitor mode" pages and basic explanations (what is humidity, what to observe)
- Extend to multiple cohorts ("volées") via separate datasets

## License

Choose a permissive license to maximize reuse in education/maker contexts:

- **MIT** is a good default (simple, permissive)
- **Apache-2.0** if you want explicit patent language

## Credits

Built for a hands-on educational plant monitoring project ("PlantLab") with a Raspberry Pi + iPad kiosk workflow.
