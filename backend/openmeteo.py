"""Récupération des prévisions Open-Meteo, modèle par modèle, avec cache par point de grille."""
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from . import config
from .db import get_db

log = logging.getLogger(__name__)

WAVE_VARS = ["wave_height", "wave_period", "wave_direction", "swell_wave_height", "swell_wave_period"]
WIND_VARS = ["wind_speed_10m", "wind_gusts_10m", "wind_direction_10m"]
CURRENT_VARS = ["ocean_current_velocity", "ocean_current_direction"]
SST_VARS = ["sea_surface_temperature"]
KMH_TO_KN = 1 / 1.852


class OpenMeteoError(RuntimeError):
    pass


def grid_point(lat: float, lon: float) -> tuple[float, float]:
    step = config.GRID_STEP
    return round(round(lat / step) * step, 4), round(round(lon / step) * step, 4)


def _http_get(url: str, params: dict, retries: int = 3) -> dict:
    if config.OPEN_METEO_API_KEY:
        params = {**params, "apikey": config.OPEN_METEO_API_KEY}
    last_error = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=20)
            if resp.status_code == 400:  # modèle ou variable inconnus : inutile de réessayer
                raise OpenMeteoError(resp.json().get("reason", resp.text))
            resp.raise_for_status()
            return resp.json()
        except OpenMeteoError:
            raise
        except requests.exceptions.SSLError as exc:  # réessayer ne changera rien
            raise OpenMeteoError(
                "Certificat HTTPS refusé (antivirus, proxy ou VPN qui inspecte le trafic ?). "
                "Installe le paquet truststore (pip install truststore) ou indique le certificat "
                f"de ton réseau dans REQUESTS_CA_BUNDLE. Détail : {exc}"
            )
        except Exception as exc:  # réseau, 5xx, 429
            last_error = exc
            time.sleep(2 * (attempt + 1))
    raise OpenMeteoError(f"Open-Meteo injoignable : {last_error}")


def _cache_get(key: str):
    limit = (datetime.now(timezone.utc) - timedelta(minutes=config.CACHE_TTL_MINUTES)).isoformat()
    with get_db() as conn:
        row = conn.execute(
            "SELECT payload FROM forecast_cache WHERE cache_key = ? AND fetched_at > ?", (key, limit)
        ).fetchone()
    return json.loads(row["payload"]) if row else None


def _cache_put(key: str, payload) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO forecast_cache (cache_key, fetched_at, payload) VALUES (?, ?, ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload",
            (key, datetime.now(timezone.utc).isoformat(), json.dumps(payload)),
        )


def _extract(data: dict, variables: list[str], model: str | None) -> dict:
    """Lit les séries horaires ; accepte les clés suffixées par le modèle ou non."""
    hourly = data.get("hourly", {})
    out = {}
    for var in variables:
        series = hourly.get(var)
        if series is None and model:
            series = hourly.get(f"{var}_{model}")
        out[var] = series or [None] * len(hourly.get("time", []))
    return out


def fill_gaps(series: list, max_gap: int = 6, circular: bool = False) -> list:
    """Interpole les valeurs manquantes entre deux valeurs connues (trous ≤ max_gap heures).

    Les directions (circulaires) prennent la valeur connue la plus proche au lieu d'une moyenne.
    Les trous au début ou à la fin de la série, ou trop longs, restent vides.
    """
    out = list(series)
    known = [i for i, v in enumerate(out) if v is not None]
    for a, b in zip(known, known[1:]):
        gap = b - a - 1
        if gap == 0 or gap > max_gap:
            continue
        for i in range(a + 1, b):
            if circular:
                out[i] = out[a] if i - a <= b - i else out[b]
            else:
                out[i] = round(out[a] + (out[b] - out[a]) * (i - a) / (b - a), 3)
    return out


def fetch_series(kind: str, lat: float, lon: float, model: str | None, tz: str) -> dict | None:
    """Une source (vagues, vent, courant, SST) pour un modèle.

    Renvoie {"timezone", "times", "values": {var: [...]}} ou None si le modèle
    ne couvre pas ce point (toutes les valeurs nulles) ou est indisponible.
    """
    glat, glon = grid_point(lat, lon)
    # « v2 » : change ce préfixe pour invalider tout le cache après une évolution du code
    key = f"v3:{kind}:{model or 'default'}:{glat}:{glon}:{tz}:{config.FORECAST_DAYS}"
    cached = _cache_get(key)
    if cached is not None:
        return cached or None  # {} en cache = « pas de données ici »

    if kind == "wind":
        url, variables = config.WEATHER_API_URL, WIND_VARS
        extra = {"wind_speed_unit": "kn"}
    else:
        url = config.MARINE_API_URL
        variables = {"waves": WAVE_VARS, "current": CURRENT_VARS, "sst": SST_VARS}[kind]
        extra = {"cell_selection": "sea"}  # prendre la maille de mer la plus proche, pas la côte
    params = {
        "latitude": glat,
        "longitude": glon,
        "hourly": ",".join(variables),
        # Même fuseau pour tous les modèles : sinon chaque API prend celui de sa propre maille
        # (Ceuta = Espagne, M'diq = Maroc) et les journées ne se recoupent plus.
        "timezone": tz,
        "forecast_days": config.FORECAST_DAYS,
        **extra,
    }
    if model:
        params["models"] = model

    try:
        data = _http_get(url, params)
    except OpenMeteoError as exc:
        log.warning("Open-Meteo %s/%s indisponible : %s", kind, model, exc)
        return None  # pas mis en cache : on réessaiera au prochain passage

    values = _extract(data, variables, model)
    # Modèles à pas de 3 h ou 6 h : on comble les petits trous pour avoir une série horaire
    values = {var: fill_gaps(series, circular=var.endswith("direction")) for var, series in values.items()}
    main_var = variables[0]
    if all(v is None for v in values[main_var]):
        _cache_put(key, {})
        return None
    if kind == "current":
        values["ocean_current_velocity"] = [
            None if v is None else round(v * KMH_TO_KN, 2) for v in values["ocean_current_velocity"]
        ]
    result = {
        "timezone": tz,
        "times": data.get("hourly", {}).get("time", []),
        "values": values,
    }
    _cache_put(key, result)
    return result


def fetch_all(lat: float, lon: float, tz: str | None = None) -> dict:
    """Toutes les sources pour un point, toutes à l'heure locale du spot (fuseau tz)."""
    tz = tz or resolve_timezone(lat, lon)
    bundle = {"timezone": tz, "waves": {}, "wind": {}, "current": None, "sst": None}

    def by_time(series: dict) -> dict:
        times = series["times"]
        return {var: dict(zip(times, vals)) for var, vals in series["values"].items()}

    for model in config.WAVE_MODELS:
        s = fetch_series("waves", lat, lon, model, tz)
        if s:
            bundle["waves"][model] = by_time(s)
    for model in config.WIND_MODELS:
        s = fetch_series("wind", lat, lon, model, tz)
        if s:
            bundle["wind"][model] = by_time(s)
    s = fetch_series("current", lat, lon, config.CURRENT_MODEL, tz)
    if s:
        bundle["current"] = by_time(s)
    s = fetch_series("sst", lat, lon, None, tz)
    if s:
        bundle["sst"] = by_time(s)

    if not bundle["waves"] and not bundle["wind"]:
        raise OpenMeteoError("Aucun modèle n'a renvoyé de données pour ce point.")
    return bundle


def resolve_timezone(lat: float, lon: float) -> str:
    """Fuseau horaire du point cliqué (ex. Africa/Casablanca), via un appel léger mis en cache."""
    key = f"tz:{round(lat, 3)}:{round(lon, 3)}"
    cached = _cache_get(key)
    if cached:
        return cached["tz"]
    try:
        data = _http_get(
            config.WEATHER_API_URL,
            {"latitude": lat, "longitude": lon, "hourly": "wind_speed_10m",
             "timezone": "auto", "forecast_days": 1},
            retries=2,
        )
        tz = data.get("timezone") or "UTC"
        _cache_put(key, {"tz": tz})
        return tz
    except OpenMeteoError:
        return "UTC"
