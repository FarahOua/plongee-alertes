"""Configuration centrale, lue depuis les variables d'environnement (fichier .env)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Charge un fichier .env simple (CLE=valeur) sans dépendance externe."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# --- Application -----------------------------------------------------------
DATABASE_URL = env("DATABASE_URL")   # chaîne de connexion Postgres (Supabase)
PUBLIC_BACKEND_URL = env("PUBLIC_BACKEND_URL", "http://localhost:5000")
FRONTEND_URL = env("FRONTEND_URL", "http://localhost:8501")

MAX_ACTIVE_SUBSCRIPTIONS = int(env("MAX_ACTIVE_SUBSCRIPTIONS", "5"))
MAX_PERIOD_DAYS = int(env("MAX_PERIOD_DAYS", "90"))
FORECAST_DAYS = 3                 # aujourd'hui + 2 jours
DIVE_HOURS = (7, 19)              # fenêtre utile de plongée, heure locale [début, fin[
BEST_WINDOW_HOURS = 3             # durée du « meilleur créneau »
CACHE_TTL_MINUTES = int(env("CACHE_TTL_MINUTES", "180"))
GRID_STEP = 0.01                  # ~1 km : partage du cache sans déplacer un spot côtier à terre

# --- Modèles comparés (identifiants Open-Meteo) ----------------------------
# Chaque modèle est interrogé séparément ; un modèle qui ne renvoie que des
# valeurs nulles à cet endroit est simplement ignoré.
WAVE_MODELS = {
    "meteofrance_wave": "MFWAM (Météo-France)",
    "ecmwf_wam": "ECMWF WAM",
    "ncep_gfswave016": "GFS Wave (NOAA)",
    "ewam": "EWAM (DWD)",
}
WIND_MODELS = {
    "ecmwf_ifs025": "ECMWF IFS",
    "meteofrance_seamless": "ARPEGE (Météo-France)",
    "icon_seamless": "ICON (DWD)",
    "gfs_seamless": "GFS (NOAA)",
}
CURRENT_MODEL = "meteofrance_currents"

# Un institut = un modèle de vagues + le modèle de vent qui l'alimente (tableau « détail par institut »)
PROVIDERS = [
    ("Météo-France", "meteofrance_wave", "meteofrance_seamless"),
    ("ECMWF", "ecmwf_wam", "ecmwf_ifs025"),
    ("NOAA", "ncep_gfswave016", "gfs_seamless"),
    ("DWD", "ewam", "icon_seamless"),
]

# --- Visibilité estimée (Copernicus Marine, compte gratuit) -----------------
COPERNICUS_USERNAME = env("COPERNICUS_USERNAME")
COPERNICUS_PASSWORD = env("COPERNICUS_PASSWORD")
# Prévision Méditerranée (MEDSEA_ANALYSISFORECAST_BGC_006_014), jeu « optics » : variable kd490
COPERNICUS_FORECAST_DATASET = env("COPERNICUS_FORECAST_DATASET", "cmems_mod_med_bgc-optics_anfc_4.2km_P1D-m")
COPERNICUS_FORECAST_VARIABLE = env("COPERNICUS_FORECAST_VARIABLE", "kd490")
# Observation satellite mondiale sans trous (GlobColour L4) : variables ZSD et KD490
COPERNICUS_SATELLITE_DATASET = env("COPERNICUS_SATELLITE_DATASET",
                                   "cmems_obs-oc_glo_bgc-transp_nrt_l4-gapfree-multi-4km_P1D")

MARINE_API_URL = env("MARINE_API_URL", "https://marine-api.open-meteo.com/v1/marine")
WEATHER_API_URL = env("WEATHER_API_URL", "https://api.open-meteo.com/v1/forecast")
OPEN_METEO_API_KEY = env("OPEN_METEO_API_KEY", "")  # seulement pour un usage commercial

# --- Rédaction par LLM (API compatible OpenAI, offre gratuite) --------------
# Sans clé Gemini, ou si Gemini échoue, on utilise le texte gabarit.
LLM_PROVIDERS = [
    {
        "name": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key": env("GEMINI_API_KEY"),
        "model": env("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        # Essayés dans l'ordre si le modèle principal est surchargé (503) ou saturé (429)
        "fallback_models": [m.strip() for m in env("GEMINI_FALLBACK_MODELS", "gemini-flash-lite-latest,gemini-flash-latest").split(",") if m.strip()],
    },
]

# --- Envoi des mails (API HTTPS de Brevo) -----------------------------------
# Sans BREVO_API_KEY, les mails sont écrits dans le dossier outbox/ (mode dev).
BREVO_API_KEY = env("BREVO_API_KEY")
MAIL_FROM = env("MAIL_FROM", "Alertes Plongée <alertes@example.com>")
OUTBOX_DIR = env("OUTBOX_DIR", str(BASE_DIR / "outbox"))
