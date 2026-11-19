"""Comparaison des modèles, indice d'accord et score de plongée.

Tout chiffre du mail sort d'ici : le LLM ne fait que les mettre en phrases.
"""
import math
from datetime import date, timedelta
from statistics import median

from . import config

JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
LABELS = ["Aujourd'hui", "Demain", "Après-demain"]
POINTS_CARDINAUX = ["nord", "nord-est", "est", "sud-est", "sud", "sud-ouest", "ouest", "nord-ouest"]
AGREEMENT_RANK = {"élevé": 3, "moyen": 2, "faible": 1, "inconnu": 0}

# Fiabilité formulée pour le plongeur (mail et site) : pas de note, une phrase directe
RELIABILITY = {
    "élevé": {"tone": "ok", "icon": "✅", "short": "D'accord", "headline": "Les modèles sont d'accord",
              "advice": "Tu peux t'y fier."},
    "moyen": {"tone": "warn", "icon": "⚠️", "short": "Divergent un peu", "headline": "Les modèles divergent un peu",
              "advice": "Prévision à prendre avec une marge."},
    "faible": {"tone": "bad", "icon": "❌", "short": "Pas d'accord", "headline": "Les modèles ne sont pas d'accord",
               "advice": "Prévision incertaine : revérifie la veille et sur place."},
    "inconnu": {"tone": "warn", "icon": "⚠️", "short": "Un seul modèle", "headline": "Un seul modèle disponible",
                "advice": "Impossible de croiser les sources."},
}


def verdict_label(score) -> str | None:
    """Verdict en mots (le chiffre reste sur le site)."""
    if score is None:
        return None
    return "Bonnes conditions" if score >= 70 else "Conditions moyennes" if score >= 45 else "Conditions difficiles"


# Seuils d'accord entre modèles (à ajuster avec l'expérience du spot)
HS_SPREAD_OK, HS_SPREAD_BAD = 0.3, 0.6      # m
WIND_SPREAD_OK, WIND_SPREAD_BAD = 5, 10     # nœuds


def french_date(d: date) -> str:
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"


def direction_name(degrees) -> str | None:
    if degrees is None:
        return None
    return POINTS_CARDINAUX[int(((degrees % 360) + 22.5) // 45) % 8]


def wind_from_text(name: str | None) -> str | None:
    """« d'ouest », « du nord-est »… pour écrire « vent d'ouest »."""
    if name is None:
        return None
    return f"d'{name}" if name[0] in "aeiou" else f"du {name}"


def _circular_mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    if not values:
        return None
    x = sum(math.cos(math.radians(v)) for v in values)
    y = sum(math.sin(math.radians(v)) for v in values)
    return math.degrees(math.atan2(y, x)) % 360


def _stats(values: list) -> dict | None:
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"median": median(values), "min": min(values), "max": max(values), "n": len(values)}


def _linear(value: float, good: float, bad: float, points: float) -> float:
    """Tous les points sous `good`, zéro au-dessus de `bad`, linéaire entre les deux."""
    if value <= good:
        return points
    if value >= bad:
        return 0.0
    return points * (bad - value) / (bad - good)


def hour_score(hs, tp, wind, gust, current) -> float | None:
    if hs is None and wind is None:
        return None
    parts, weights = 0.0, 0.0
    if hs is not None:
        wave_pts = _linear(hs, 0.3, 1.5, 45)
        if hs > 0.5 and tp is not None and tp < 6:  # mer courte et hachée
            wave_pts *= 0.8
        parts, weights = parts + wave_pts, weights + 45
    if wind is not None:
        wind_pts = _linear(wind, 8, 22, 35)
        if gust is not None and gust > 25:
            wind_pts = max(0.0, wind_pts - 5)
        parts, weights = parts + wind_pts, weights + 35
    cur = 0.3 if current is None else current  # inconnu : hypothèse neutre
    parts, weights = parts + _linear(cur, 0.3, 1.5, 20), weights + 20
    return 100 * parts / weights


def agreement_level(hs_stats, wind_stats) -> str:
    hs_spread = hs_stats["max"] - hs_stats["min"] if hs_stats and hs_stats["n"] >= 2 else None
    ws_spread = wind_stats["max"] - wind_stats["min"] if wind_stats and wind_stats["n"] >= 2 else None
    if hs_spread is None and ws_spread is None:
        return "inconnu"
    if (hs_spread or 0) >= HS_SPREAD_BAD or (ws_spread or 0) >= WIND_SPREAD_BAD:
        return "faible"
    if (hs_spread or 0) < HS_SPREAD_OK and (ws_spread or 0) < WIND_SPREAD_OK:
        return "élevé"
    return "moyen"


def cap_score(score: float, agreement: str) -> int:
    """Un bon score sur lequel les modèles ne s'entendent pas ne doit pas paraître sûr."""
    if agreement == "faible":
        score = min(score, 60)
    elif agreement == "moyen":
        score = min(score, 80)
    return int(round(score))


def _hour_snapshot(bundle: dict, t: str) -> dict:
    waves, wind = bundle["waves"], bundle["wind"]
    hs = _stats([m["wave_height"].get(t) for m in waves.values()])
    tp = _stats([m["wave_period"].get(t) for m in waves.values()])
    ws = _stats([m["wind_speed_10m"].get(t) for m in wind.values()])
    wg = _stats([m["wind_gusts_10m"].get(t) for m in wind.values()])
    wd = _circular_mean([m["wind_direction_10m"].get(t) for m in wind.values()])
    cur = bundle["current"]["ocean_current_velocity"].get(t) if bundle.get("current") else None
    agreement = agreement_level(hs, ws)
    if waves and hs is None:  # pas de vagues à cette heure : on ne note pas sur le vent seul
        return {"time": t, "hs": None, "tp": tp, "wind": ws, "gust": wg, "wind_dir": wd,
                "current": cur, "agreement": agreement, "score": None}
    raw = hour_score(
        hs["median"] if hs else None, tp["median"] if tp else None,
        ws["median"] if ws else None, wg["median"] if wg else None, cur,
    )
    return {"time": t, "hs": hs, "tp": tp, "wind": ws, "gust": wg, "wind_dir": wd,
            "current": cur, "agreement": agreement,
            "score": None if raw is None else cap_score(raw, agreement)}


def _day_value(bundle: dict, source: str, var: str, day: str):
    """Valeur moyenne de la journée pour les séries à un seul modèle (courant, SST)."""
    series = (bundle.get(source) or {}).get(var, {})
    values = [v for t, v in series.items() if t.startswith(day) and v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _r(value, digits=1):
    return None if value is None else round(value, digits)


def build_report(bundle: dict, today: date, spot_name: str = "", now_hour: int | None = None) -> dict:
    """Rapport sur aujourd'hui + 2 jours, à partir du paquet renvoyé par openmeteo.fetch_all.

    now_hour : heure locale actuelle ; si donnée, les heures déjà passées d'aujourd'hui sont ignorées.
    """
    start_h, end_h = config.DIVE_HOURS
    width = config.BEST_WINDOW_HOURS
    days = []
    for offset in range(config.FORECAST_DAYS):
        d = today + timedelta(days=offset)
        day = d.isoformat()
        first_h = max(start_h, now_hour) if (offset == 0 and now_hour is not None) else start_h
        hours = [_hour_snapshot(bundle, f"{day}T{h:02d}:00") for h in range(first_h, end_h)]
        scored = [h for h in hours if h["score"] is not None]

        best, best_mean = None, -1.0
        for i in range(len(hours) - width + 1):
            window = hours[i:i + width]
            if any(h["score"] is None for h in window):
                continue
            m = sum(h["score"] for h in window) / width
            if m > best_mean:
                best, best_mean = window, m

        entry = {"date": day, "label": LABELS[offset] if offset < len(LABELS) else day,
                 "date_fr": french_date(d), "score": None, "agreement": "inconnu",
                 "best_window": None, "summary": {}, "per_model": None,
                 "reliability": None, "verdict": None,
                 "water_temp": _day_value(bundle, "sst", "sea_surface_temperature", day),
                 "current_kn": _day_value(bundle, "current", "ocean_current_velocity", day)}
        if not scored or best is None:
            if not hours:
                entry["note"] = "Journée de plongée terminée."
            elif bundle["waves"] and all(h["hs"] is None for h in hours):
                entry["note"] = "Les modèles de vagues n'ont pas de données pour cette journée."
            else:
                entry["note"] = "Pas assez de données."
            days.append(entry)
            continue

        worst = min((h["agreement"] for h in best), key=lambda a: AGREEMENT_RANK[a])
        entry["agreement"] = worst
        entry["reliability"] = RELIABILITY[worst]
        entry["verdict"] = verdict_label(round(best_mean))
        entry["score"] = int(round(best_mean))
        end_hour = int(best[-1]["time"][11:13]) + 1
        entry["best_window"] = {"start": best[0]["time"][11:16], "end": f"{end_hour:02d}:00"}

        def window_stat(key, field):
            return _mean([h[key][field] for h in best if h[key]])

        entry["summary"] = {
            "wave_height": {"median": _r(window_stat("hs", "median")), "min": _r(window_stat("hs", "min")),
                            "max": _r(window_stat("hs", "max"))},
            "wave_period": {"median": _r(window_stat("tp", "median"), 0)},
            "wind_speed": {"median": _r(window_stat("wind", "median"), 0), "min": _r(window_stat("wind", "min"), 0),
                           "max": _r(window_stat("wind", "max"), 0)},
            "wind_gusts": {"median": _r(window_stat("gust", "median"), 0)},
            "wind_from": wind_from_text(direction_name(_circular_mean([h["wind_dir"] for h in best]))),
            "current_kn": _r(_mean([h["current"] for h in best])),
        }
        # Détail par institut au milieu du meilleur créneau : son modèle de vagues + son modèle de vent
        t = best[len(best) // 2]["time"]
        rows = []
        for provider, wave_model, wind_model in config.PROVIDERS:
            w = bundle["waves"].get(wave_model)
            a = bundle["wind"].get(wind_model)
            if w is None and a is None:
                continue
            names = ([config.WAVE_MODELS[wave_model].split(" (")[0]] if w else []) + \
                    ([config.WIND_MODELS[wind_model].split(" (")[0]] if a else [])
            rows.append({
                "provider": provider,
                "models": " + ".join(n.removeprefix(provider + " ") for n in names),  # « WAM + IFS »
                "wave_height": _r(w["wave_height"].get(t)) if w else None,
                "wave_period": _r(w["wave_period"].get(t), 0) if w else None,
                "wind_speed": _r(a["wind_speed_10m"].get(t), 0) if a else None,
            })
        entry["per_model"] = {"time": t[11:16], "rows": rows}
        days.append(entry)

    return {
        "spot": spot_name,
        "timezone": bundle["timezone"],
        "models": {
            "waves": [config.WAVE_MODELS[m] for m in config.WAVE_MODELS if m in bundle["waves"]],
            "wind": [config.WIND_MODELS[m] for m in config.WIND_MODELS if m in bundle["wind"]],
        },
        "days": days,
    }
