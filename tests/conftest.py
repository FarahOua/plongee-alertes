"""Environnement de test isolé + faux Open-Meteo (aucun appel réseau)."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

TMP = tempfile.mkdtemp(prefix="plongee-tests-")
# Les tests tournent sur une base Postgres VIDÉE à chaque session : jamais celle de production.
# Crée un second projet Supabase (ou une base locale) et mets son URL dans TEST_DATABASE_URL.
def _from_dotenv(name: str) -> str:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or _from_dotenv("TEST_DATABASE_URL")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["OUTBOX_DIR"] = str(Path(TMP) / "outbox")
os.environ["GEMINI_API_KEY"] = ""
# Aucun envoi réel, aucun appel Copernicus, même si le .env en contient les clés
os.environ["BREVO_API_KEY"] = ""
os.environ["COPERNICUS_USERNAME"] = ""
os.environ["COPERNICUS_PASSWORD"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TZ = "Africa/Casablanca"

# Vent par modèle (nœuds) : J et J+2 cohérents, J+1 très dispersé (ICON s'emballe)
WIND = {"ecmwf_ifs025": 6, "meteofrance_seamless": 8, "icon_seamless": 7, "gfs_seamless": 9}
WAVES = {"meteofrance_wave": 0.4, "ecmwf_wam": 0.5, "ewam": 0.45}  # GFS Wave : pas de données ici


def fake_times():
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(TZ)).date()
    start = datetime(today.year, today.month, today.day)
    return [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(72)]


def fake_http_get(url, params, retries=3):
    times = fake_times()
    n = len(times)
    model = params.get("models")
    hourly = {"time": times}
    variables = params["hourly"].split(",")
    if "marine" in url:
        if model in WAVES:
            base = WAVES[model]
            hourly.update({
                "wave_height": [base] * n, "wave_period": [6.0] * n, "wave_direction": [90.0] * n,
                "swell_wave_height": [base / 2] * n, "swell_wave_period": [8.0] * n,
            })
        elif model == "meteofrance_currents":
            hourly.update({"ocean_current_velocity": [0.6] * n, "ocean_current_direction": [45.0] * n})
        elif model is None and "sea_surface_temperature" in variables:
            hourly["sea_surface_temperature"] = [18.2] * n
        else:  # modèle qui ne couvre pas le point
            hourly.update({v: [None] * n for v in variables})
    else:
        speed = WIND.get(model, 7)
        winds = []
        for t in times:
            day_index = times.index(t) // 24
            winds.append(25.0 if (model == "icon_seamless" and day_index == 1) else float(speed))
        hourly.update({"wind_speed_10m": winds, "wind_gusts_10m": [w + 4 for w in winds],
                       "wind_direction_10m": [270.0] * n})
    return {"timezone": TZ, "hourly": {k: v for k, v in hourly.items() if k == "time" or k in variables}}


@pytest.fixture(scope="session", autouse=True)
def clean_database():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL non défini (base Postgres de test requise)", allow_module_level=False)
    from backend.db import TABLES, get_db, init_db
    init_db()
    with get_db() as conn:
        conn.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE")


@pytest.fixture(autouse=True)
def fake_open_meteo(monkeypatch):
    from backend import openmeteo
    from backend.db import get_db, init_db
    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM forecast_cache")
    monkeypatch.setattr(openmeteo, "_http_get", fake_http_get)
    yield


@pytest.fixture
def client():
    from backend.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()
