"""Traitement quotidien : sélection des alertes dues, prévisions, rédaction, envoi."""
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config, openmeteo, visibility
from .compare import build_report
from .db import get_db
from .mailer import send_email
from .writer import write_email_text

log = logging.getLogger(__name__)

_jinja = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def local_now(tz_name: str, now_utc: datetime | None = None) -> datetime:
    now_utc = now_utc or datetime.now(timezone.utc)
    try:
        return now_utc.astimezone(ZoneInfo(tz_name))
    except Exception:
        return now_utc


def links_for(sub: dict, report_date: str) -> dict:
    base = config.PUBLIC_BACKEND_URL.rstrip("/")
    return {
        "report": f"{base}/reports/{sub['id']}/{report_date}?t={sub['public_token']}",
        "unsubscribe": f"{base}/unsubscribe/{sub['public_token']}",
        "manage": config.FRONTEND_URL,
    }


def render_email(report: dict, text: dict, links: dict) -> tuple[str, str]:
    html = _jinja.get_template("email.html").render(report=report, text=text, links=links)
    plain = "\n\n".join([text["intro"], *text["paragraphs"],
                         f"Voir sur le site : {links['report']}",
                         f"Arrêter cette alerte : {links['unsubscribe']}",
                         "Données : Open-Meteo.com, Météo-France, ECMWF, NOAA, DWD, Copernicus Marine."])
    return html, plain


def make_report(lat: float, lon: float, spot_name: str, tz_name: str | None = None,
                with_visibility: bool = True) -> dict:
    """Rapport complet. with_visibility=False : sans Copernicus (lent), la visibilité est demandée ensuite à part."""
    bundle = openmeteo.fetch_all(lat, lon, tz_name)
    now = local_now(bundle["timezone"])
    report = build_report(bundle, now.date(), spot_name, now_hour=now.hour)
    return visibility.enrich_report(report, lat, lon) if with_visibility else report


def process_subscription(sub: dict, email: str, report_date: date) -> dict:
    """Construit et envoie le mail d'une alerte pour une date locale donnée."""
    day = report_date.isoformat()
    bundle = openmeteo.fetch_all(sub["lat"], sub["lon"], sub["timezone"])
    report = visibility.enrich_report(build_report(bundle, report_date, sub["name"]), sub["lat"], sub["lon"])
    text = write_email_text(report)
    links = links_for(sub, day)
    html, plain = render_email(report, text, links)

    with get_db() as conn:
        # Réservation de la journée : la contrainte UNIQUE empêche un double envoi
        cur = conn.execute(
            "INSERT INTO email_log (subscription_id, report_date, status) VALUES (?, ?, 'pending') "
            "ON CONFLICT(subscription_id, report_date) DO NOTHING",
            (sub["id"], day),
        )
        if cur.rowcount == 0:
            return {"status": "already_sent", "subscription_id": sub["id"]}
        conn.execute(
            "INSERT INTO daily_reports (subscription_id, report_date, report_json, text_json, html) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(subscription_id, report_date) DO UPDATE SET "
            "report_json=excluded.report_json, text_json=excluded.text_json, html=excluded.html",
            (sub["id"], day, json.dumps(report, ensure_ascii=False), json.dumps(text, ensure_ascii=False), html),
        )

    try:
        provider_id = send_email(email, text["subject"], html, plain, links["unsubscribe"])
        status, detail = "sent", provider_id
    except Exception as exc:  # l'envoi sera retenté au prochain passage
        log.exception("Échec d'envoi pour l'alerte %s", sub["id"])
        with get_db() as conn:
            conn.execute("DELETE FROM email_log WHERE subscription_id = ? AND report_date = ?", (sub["id"], day))
        return {"status": "error", "subscription_id": sub["id"], "detail": str(exc)}

    with get_db() as conn:
        conn.execute("UPDATE email_log SET status = ?, detail = ? WHERE subscription_id = ? AND report_date = ?",
                     (status, detail, sub["id"], day))
        conn.execute("UPDATE subscriptions SET last_sent_on = ? WHERE id = ?", (day, sub["id"]))
    return {"status": status, "subscription_id": sub["id"], "text_source": text.get("source")}


def run_due(now_utc: datetime | None = None) -> list[dict]:
    """À lancer toutes les 15 minutes (GitHub Actions, cron ou planificateur local)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT s.*, u.email FROM subscriptions s JOIN users u ON u.id = s.user_id WHERE s.status = 'active'"
        ).fetchall()
    results = []
    for row in rows:
        sub = dict(row)
        now_local = local_now(sub["timezone"], now_utc)
        today = now_local.date().isoformat()
        if today > sub["end_date"]:
            with get_db() as conn:
                conn.execute("UPDATE subscriptions SET status = 'ended' WHERE id = ?", (sub["id"],))
            results.append({"status": "ended", "subscription_id": sub["id"]})
            continue
        if today < sub["start_date"] or now_local.strftime("%H:%M") < sub["send_time"]:
            continue
        if sub["last_sent_on"] == today:
            continue
        try:
            results.append(process_subscription(sub, sub["email"], now_local.date()))
        except Exception as exc:
            log.exception("Alerte %s non traitée", sub["id"])
            results.append({"status": "error", "subscription_id": sub["id"], "detail": str(exc)})
    return results
