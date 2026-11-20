import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from . import config, openmeteo

log = logging.getLogger(__name__)

LEVELS = ["faible", "moyenne", "bonne"]
RANGES = {"bonne": "15 m et plus", "moyenne": "8 à 15 m", "faible": "moins de 8 m"}
# Seuils Kd490 (1/m) : valeurs de départ, à ajuster avec tes observations en plongée
KD_GOOD, KD_POOR = 0.07, 0.15
SWELL_MALUS_M = 1.0      # houle médiane au-delà de laquelle l'eau est brassée
RAIN_MALUS_MM = 10.0     # pluie cumulée sur les 48 h précédentes
BOX = 0.1                # demi-côté (°) de la zone téléchargée autour du point


def is_configured() -> bool:
    if not (config.COPERNICUS_USERNAME and config.COPERNICUS_PASSWORD):
        return False
    try:
        import copernicusmarine  # noqa: F401
    except ImportError:
        log.warning("Identifiants Copernicus présents mais paquet absent : pip install copernicusmarine")
        return False
    return True


def _nearest_valid(da, lat: float, lon: float):
    """Valeur de la maille de mer valide la plus proche (les mailles à terre sont NaN)."""
    import numpy as np

    values = np.asarray(da.values, dtype=float)
    lats = np.asarray(da["latitude"].values)
    lons = np.asarray(da["longitude"].values)
    grid_lat, grid_lon = np.meshgrid(lats, lons, indexing="ij")
    dist = (grid_lat - lat) ** 2 + ((grid_lon - lon) * np.cos(np.radians(lat))) ** 2
    dist = np.where(np.isfinite(values), dist, np.inf)
    if not np.isfinite(dist).any():
        return None
    return float(values.flat[int(np.argmin(dist))])


def _open(dataset_id: str, variables: list[str], lat: float, lon: float, start: date, end: date) -> dict:
    """Ouvre le jeu de données UNE fois pour toutes les variables demandées : {variable: tableau}."""
    import copernicusmarine

    # Identifiants passés explicitement : la boîte à outils ne lit pas toujours les variables d'environnement.
    ds = copernicusmarine.open_dataset(
        dataset_id=dataset_id,
        username=config.COPERNICUS_USERNAME,
        password=config.COPERNICUS_PASSWORD,
        variables=variables,
        minimum_latitude=lat - BOX, maximum_latitude=lat + BOX,
        minimum_longitude=lon - BOX, maximum_longitude=lon + BOX,
        start_datetime=f"{start.isoformat()}T00:00:00",
        end_datetime=f"{end.isoformat()}T23:59:59",
    )
    out = {}
    for variable in variables:
        da = ds[variable]
        if "depth" in da.dims:  # modèle 3D : on garde la surface
            da = da.isel(depth=0)
        out[variable] = da.load()
    return out


def _daily_values(da, lat: float, lon: float) -> dict:
    out = {}
    for i in range(da.sizes.get("time", 0)):
        day = str(da["time"].values[i])[:10]
        value = _nearest_valid(da.isel(time=i), lat, lon)
        if value is not None:
            out[day] = round(value, 3)
    return out


def _cached(key: str, fetch):
    cached = openmeteo._cache_get(key)
    if cached is not None:
        return cached
    try:
        value = fetch()
    except Exception as exc:  # réseau, identifiants, jeu de données renommé…
        log.warning("Copernicus indisponible (%s) : %s", key.split(":")[1], exc)
        return None
    openmeteo._cache_put(key, value)
    return value


def fetch_kd490_forecast(lat: float, lon: float, start: date, days: int) -> dict | None:
    """Kd490 prévu par jour {AAAA-MM-JJ: valeur}."""
    key = f"vis:forecast:{round(lat, 2)}:{round(lon, 2)}:{start.isoformat()}:{days}"
    return _cached(key, lambda: _daily_values(
        _open(config.COPERNICUS_FORECAST_DATASET, [config.COPERNICUS_FORECAST_VARIABLE],
              lat, lon, start, start + timedelta(days=days - 1))[config.COPERNICUS_FORECAST_VARIABLE],
        lat, lon))


def fetch_satellite(lat: float, lon: float, today: date) -> dict | None:
    """Dernière observation satellite des 6 derniers jours : {date, zsd, kd490}."""
    key = f"vis:satellite:{round(lat, 2)}:{round(lon, 2)}:{today.isoformat()}"

    def fetch():
        start = today - timedelta(days=6)
        arrays = _open(config.COPERNICUS_SATELLITE_DATASET, ["ZSD", "KD490"], lat, lon, start, today)
        zsd = _daily_values(arrays["ZSD"], lat, lon)
        kd = _daily_values(arrays["KD490"], lat, lon)
        days = sorted(set(zsd) | set(kd))
        if not days:
            return {}
        last = days[-1]
        return {"date": last, "zsd": zsd.get(last), "kd490": kd.get(last)}

    return _cached(key, fetch)


def fetch_recent_rain(lat: float, lon: float, tz: str) -> dict | None:
    """Pluie journalière (mm) sur 2 jours passés + jours prévus, via Open-Meteo."""
    key = f"vis:rain:{round(lat, 2)}:{round(lon, 2)}:{tz}"
    cached = openmeteo._cache_get(key)
    if cached is not None:
        return cached
    try:
        data = openmeteo._http_get(config.WEATHER_API_URL, {
            "latitude": lat, "longitude": lon, "daily": "precipitation_sum",
            "timezone": tz, "past_days": 2, "forecast_days": config.FORECAST_DAYS,
        }, retries=2)
    except openmeteo.OpenMeteoError as exc:
        log.warning("Pluie indisponible : %s", exc)
        return None
    daily = data.get("daily", {})
    rain = {d: v for d, v in zip(daily.get("time", []), daily.get("precipitation_sum", [])) if v is not None}
    openmeteo._cache_put(key, rain)
    return rain


def level_from_kd490(kd: float) -> str:
    if kd < KD_GOOD:
        return "bonne"
    if kd < KD_POOR:
        return "moyenne"
    return "faible"


def estimate(day: str, kd_forecast: dict | None, satellite: dict | None,
             swell_m: float | None, rain: dict | None) -> dict:
    """Estimation pour un jour. Tous les chiffres renvoyés sont des données, pas des calculs du LLM."""
    reasons = []
    kd = (kd_forecast or {}).get(day)
    source = "prévision Copernicus"
    if kd is None and satellite and satellite.get("kd490") is not None:
        kd, source = satellite["kd490"], f"satellite du {satellite['date']}"
    if kd is None:
        return {"level": "inconnue", "range": None, "reasons": ["pas de donnée de transparence"]}

    rank = LEVELS.index(level_from_kd490(kd))
    reasons.append(f"Kd490 {kd:g} ({source})")
    if swell_m is not None and swell_m >= SWELL_MALUS_M:
        rank -= 1
        reasons.append(f"houle de {swell_m:g} m : eau brassée")
    if rain:
        d = date.fromisoformat(day)
        recent = sum(rain.get((d - timedelta(days=k)).isoformat(), 0) for k in (1, 2))
        if recent >= RAIN_MALUS_MM:
            rank -= 1
            reasons.append(f"{recent:g} mm de pluie sur 48 h : apports des oueds")
    level = LEVELS[max(0, rank)]
    result = {"level": level, "range": RANGES[level], "kd490": kd, "reasons": reasons}
    if satellite and satellite.get("zsd") is not None:
        result["secchi_m"] = satellite["zsd"]
        result["secchi_date"] = satellite["date"]
    return result


def enrich_report(report: dict, lat: float, lon: float) -> dict:
    """Ajoute day["visibility"] à chaque jour du rapport (si Copernicus est configuré)."""
    if not is_configured() or not report.get("days"):
        return report
    start = date.fromisoformat(report["days"][0]["date"])
    # Les trois sources sont indépendantes : on les interroge en même temps (surtout Copernicus, lent).
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_kd = pool.submit(fetch_kd490_forecast, lat, lon, start, len(report["days"]))
        f_sat = pool.submit(fetch_satellite, lat, lon, start)
        f_rain = pool.submit(fetch_recent_rain, lat, lon, report["timezone"])
        kd_forecast, satellite, rain = f_kd.result(), f_sat.result(), f_rain.result()
    if not kd_forecast and not satellite:
        return report
    for day in report["days"]:
        swell = ((day.get("summary") or {}).get("wave_height") or {}).get("median")
        day["visibility"] = estimate(day["date"], kd_forecast, satellite, swell, rain)
    return report
