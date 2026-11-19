"""Rédaction du texte du mail : LLM gratuit (Google Gemini), sinon texte gabarit.

Règle : le LLM reçoit des chiffres déjà calculés et n'a pas le droit d'en écrire
d'autres. Un contrôle automatique rejette tout texte contenant un nombre absent
des données ; on retombe alors sur le gabarit.
"""
import json
import logging
import re

import requests

from . import config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es moniteur de plongée et tu rédiges le court briefing météo-mer du matin pour des plongeurs.
Les tableaux sous ton texte donnent déjà tous les chiffres : ton rôle est de résumer, pas de tout répéter.
Règles :
- Français, ton direct et chaleureux, phrases courtes, pas d'emoji.
- Utilise UNIQUEMENT les chiffres présents dans les données JSON fournies. N'en calcule pas, n'en arrondis pas, n'en invente pas.
- Ne parle d'aucune note ni de « sur 100 » : donne le verdict en mots (« bonnes conditions », etc.).
- Dis clairement si les modèles sont d'accord ou non. Accord « élevé » : on peut s'y fier. « moyen » : ils divergent un peu. « faible » : prévision incertaine.
- La visibilité est une ESTIMATION indicative : présente-la comme telle (« visibilité estimée »).
- Ne remplace pas le jugement du directeur de plongée.
Réponds uniquement par un objet JSON de la forme :
{"subject": "...", "intro": "...", "paragraphs": ["..."]}
- subject : 70 caractères maximum : spot, jour, verdict en mots et si les modèles sont d'accord. Aucun chiffre de score.
- intro : UNE phrase : verdict du premier jour avec données (champ premier_jour_avec_donnees) et accord des modèles. Si ce n'est pas aujourd'hui, dis que la journée de plongée d'aujourd'hui est terminée.
- paragraphs : 1 ou 2 paragraphes de 2 phrases maximum : ce premier jour (meilleur créneau, l'essentiel de la mer et du vent), puis une phrase sur les jours suivants."""

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _fmt(value, unit: str = "") -> str:
    if value is None:
        return "?"
    text = f"{value:g}".replace(".", ",")
    return f"{text} {unit}".strip()


def _hour(hhmm: str) -> str:
    return f"{int(hhmm[:2])}h"


def _lead_day(report: dict) -> dict | None:
    """Premier jour qui a des données : aujourd'hui, ou demain une fois la journée de plongée terminée."""
    return next((d for d in report["days"] if d["score"] is not None), None)


def build_facts(report: dict) -> dict:
    """Données compactes envoyées au LLM (aucune donnée personnelle)."""
    jours = []
    for day in report["days"]:
        s = day.get("summary") or {}
        w = day.get("best_window")
        jours.append({
            "jour": day["label"],
            "date": day["date_fr"],
            "conditions": day.get("verdict"),
            "accord_des_modeles": day["agreement"],
            "meilleur_creneau": f"{_hour(w['start'])}-{_hour(w['end'])}" if w else None,
            "vagues_m": s.get("wave_height"),
            "periode_s": (s.get("wave_period") or {}).get("median"),
            "vent_noeuds": s.get("wind_speed"),
            "rafales_noeuds": (s.get("wind_gusts") or {}).get("median"),
            "provenance_du_vent": s.get("wind_from"),  # ex. « d'ouest »
            "courant_noeuds_indicatif": day.get("current_kn"),
            "eau_degres": day.get("water_temp"),
            "visibilite_estimee": (f"{day['visibility']['level']} ({day['visibility']['range']})"
                                   if day.get("visibility") and day["visibility"].get("range") else None),
        })
    lead = _lead_day(report)
    return {
        "spot": report.get("spot") or "ton spot",
        "premier_jour_avec_donnees": lead["label"] if lead else None,
        "modeles_vagues": report["models"]["waves"],
        "modeles_vent": report["models"]["wind"],
        "jours": jours,
    }


def _allowed_numbers(obj, acc: set) -> set:
    if isinstance(obj, dict):
        for v in obj.values():
            _allowed_numbers(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _allowed_numbers(v, acc)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        acc.add(round(float(obj), 2))
    elif isinstance(obj, str):
        for n in NUMBER_RE.findall(obj):
            acc.add(round(float(n.replace(",", ".")), 2))
    return acc


def numbers_are_grounded(text: str, facts: dict) -> bool:
    allowed = _allowed_numbers(facts, set()) | {1.0, 2.0, 3.0, 100.0}  # J+1, J+2, « /100 »
    for n in NUMBER_RE.findall(text):
        if round(float(n.replace(",", ".")), 2) not in allowed:
            log.info("Nombre non justifié dans le texte du LLM : %s", n)
            return False
    return True


def _parse_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content[content.find("{"):]
    data = json.loads(content[content.find("{"): content.rfind("}") + 1])
    if not isinstance(data.get("subject"), str) or not isinstance(data.get("paragraphs"), list):
        raise ValueError("Réponse LLM mal formée")
    data["intro"] = str(data.get("intro", ""))
    data["paragraphs"] = [str(p) for p in data["paragraphs"] if str(p).strip()][:2]
    data["subject"] = data["subject"][:90]
    return data


def _call_llm(provider: dict, facts: dict) -> dict:
    body = {
        "model": provider["model"],
        "temperature": 0.3,
        "max_tokens": 2000,   # large : les modèles « réflexion » dépensent des jetons avant de répondre
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
    }
    url = f"{provider['base_url']}/chat/completions"
    headers = {"Authorization": f"Bearer {provider['api_key']}"}
    resp = requests.post(url, headers=headers, json=body, timeout=40)
    if resp.status_code == 400:  # le fournisseur refuse le mode JSON : on retente sans, le prompt l'exige déjà
        body.pop("response_format")
        resp = requests.post(url, headers=headers, json=body, timeout=40)
    resp.raise_for_status()
    return _parse_json(resp.json()["choices"][0]["message"]["content"])


def template_text(report: dict) -> dict:
    """Texte sans LLM : bref, toujours disponible, ne peut pas inventer de chiffre."""
    spot = report.get("spot") or "Ton spot"
    days = report["days"]
    today = _lead_day(report)
    if today is None:
        return {"subject": f"{spot} — {days[0]['date_fr']} : prévisions indisponibles",
                "intro": "Les modèles n'ont pas renvoyé assez de données.",
                "paragraphs": [], "source": "gabarit"}
    is_today = today is days[0]

    def accord(a):
        return {"élevé": "les modèles sont d'accord", "moyen": "les modèles divergent un peu",
                "faible": "les modèles ne sont pas d'accord, prévision incertaine",
                "inconnu": "un seul modèle disponible"}[a]

    s, w = today["summary"], today["best_window"]
    hs, ws = s["wave_height"], s["wind_speed"]
    parts = [f"Meilleur créneau {_hour(w['start'])}–{_hour(w['end'])}."]
    if not is_today:
        parts[0] = f"{today['label']}, meilleur créneau {_hour(w['start'])}–{_hour(w['end'])}."
    if hs["median"] is not None:
        parts.append(f"Mer à {_fmt(hs['median'], 'm')}"
                     + (f", vent de {_fmt(ws['median'], 'nœuds')}" + (f" {s['wind_from']}" if s["wind_from"] else "")
                        if ws["median"] is not None else "") + ".")
    vis = today.get("visibility")
    if vis and vis.get("range"):
        parts.append(f"Visibilité estimée {vis['level']} ({vis['range']}), à confirmer sur place.")
    paragraphs = [" ".join(parts)]

    suite = []
    for day in days[days.index(today) + 1:]:
        if day["score"] is None:
            suite.append(f"{day['label']} : pas assez de données.")
        else:
            suite.append(f"{day['label']} : {day['verdict'].lower()}, {accord(day['agreement'])}.")
    if suite:
        paragraphs.append(" ".join(suite))

    return {
        "subject": f"{spot} — {today['date_fr']} : {today['verdict'].lower()}, {accord(today['agreement'])}",
        "intro": (f"{today['verdict']} aujourd'hui : {accord(today['agreement'])}." if is_today else
                  f"La journée de plongée d'aujourd'hui est terminée. {today['label']} : "
                  f"{today['verdict'].lower()}, {accord(today['agreement'])}."),
        "paragraphs": paragraphs,
        "source": "gabarit",
    }


def write_email_text(report: dict) -> dict:
    """Texte du mail : premier LLM qui répond avec des chiffres vérifiés, sinon gabarit."""
    if report["days"][0]["score"] is None:
        return template_text(report)
    facts = build_facts(report)
    for provider in config.LLM_PROVIDERS:
        if not provider["api_key"]:
            continue
        try:
            text = _call_llm(provider, facts)
        except Exception as exc:
            log.warning("LLM %s indisponible : %s", provider["name"], exc)
            continue
        full = " ".join([text["subject"], text["intro"], *text["paragraphs"]])
        if numbers_are_grounded(full, facts):
            text["source"] = provider["name"]
            return text
        log.warning("Texte de %s rejeté : chiffre non présent dans les données", provider["name"])
    return template_text(report)
