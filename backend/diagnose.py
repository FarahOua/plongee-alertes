"""Diagnostic : ce que chaque modèle Open-Meteo renvoie vraiment pour un point (sans cache).

Usage : python -m backend.diagnose 35.69 -5.30
(vide le cache : DELETE FROM forecast_cache; dans Supabase, ou attends 3 h pour voir des valeurs fraîches)
"""
import sys

from . import config, openmeteo


def check(kind: str, model: str | None, lat: float, lon: float, tz: str) -> None:
    if kind == "wind":
        url, variables, extra = config.WEATHER_API_URL, openmeteo.WIND_VARS, {"wind_speed_unit": "kn"}
    else:
        url = config.MARINE_API_URL
        variables = {"waves": openmeteo.WAVE_VARS, "current": openmeteo.CURRENT_VARS,
                     "sst": openmeteo.SST_VARS}[kind]
        extra = {"cell_selection": "sea"}
    params = {"latitude": lat, "longitude": lon, "hourly": ",".join(variables), "timezone": tz,
              "forecast_days": config.FORECAST_DAYS, **extra}
    if model:
        params["models"] = model
    label = f"{kind:7} {model or '(défaut)':22}"
    try:
        data = openmeteo._http_get(url, params, retries=1)
    except openmeteo.OpenMeteoError as exc:
        print(f"{label} ERREUR : {exc}")
        return
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    raw = openmeteo._extract(data, variables, model)[variables[0]]
    ok = [i for i, v in enumerate(raw) if v is not None]
    keys = ", ".join(k for k in hourly if k != "time")
    if not ok:
        print(f"{label} 0/{len(raw)} valeurs · clés : {keys}")
        return
    step = ok[1] - ok[0] if len(ok) > 1 else "?"
    sample = ", ".join(f"{times[i][11:16]}={raw[i]}" for i in ok[:4])
    print(f"{label} {len(ok)}/{len(raw)} valeurs · de {times[ok[0]]} à {times[ok[-1]]} · pas {step} h · "
          f"point {data.get('latitude')},{data.get('longitude')} · ex. {sample}")


def main() -> None:
    lat, lon = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) == 3 else (35.69, -5.30)
    tz = openmeteo.resolve_timezone(lat, lon)
    print(f"Point demandé : {lat}, {lon} · fuseau commun : {tz}\n")
    for model in config.WAVE_MODELS:
        check("waves", model, lat, lon, tz)
    for model in config.WIND_MODELS:
        check("wind", model, lat, lon, tz)
    check("current", config.CURRENT_MODEL, lat, lon, tz)
    check("sst", None, lat, lon, tz)

    print("\nVisibilité (Copernicus Marine) :")
    from datetime import date
    from . import visibility
    if not visibility.is_configured():
        print("  non configurée : COPERNICUS_USERNAME / COPERNICUS_PASSWORD dans .env + pip install copernicusmarine")
        return
    today = date.today()
    for label, fn in (("prévision Kd490", lambda: visibility.fetch_kd490_forecast(lat, lon, today, 3)),
                      ("satellite ZSD/KD490", lambda: visibility.fetch_satellite(lat, lon, today))):
        try:
            print(f"  {label:20} {fn()}")
        except Exception as exc:
            print(f"  {label:20} ERREUR : {exc}")


if __name__ == "__main__":
    main()
