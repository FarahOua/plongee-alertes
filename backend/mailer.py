"""Envoi des mails par l'API HTTPS de Brevo ; sans clé (mode dev), écriture dans outbox/."""
import logging
import re
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from pathlib import Path

import requests

from . import config

log = logging.getLogger(__name__)

UNSUBSCRIBE_POST = "List-Unsubscribe=One-Click"


def send_email(to: str, subject: str, html: str, text: str, unsubscribe_url: str | None = None) -> str:
    """Envoie le mail et renvoie un identifiant (messageId Brevo, ou chemin du fichier en dev)."""
    if config.BREVO_API_KEY:
        return _send_brevo_api(to, subject, html, text, unsubscribe_url)
    return _write_to_outbox(to, subject, html, text, unsubscribe_url)


def _write_to_outbox(to: str, subject: str, html: str, text: str, unsubscribe_url: str | None) -> str:
    msg = EmailMessage()
    msg["From"] = config.MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="alertes-plongee")
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    outbox = Path(config.OUTBOX_DIR)
    outbox.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", to)
    path = outbox / f"{datetime.now():%Y%m%d-%H%M%S}-{safe}.eml"
    path.write_bytes(bytes(msg))
    path.with_suffix(".html").write_text(html, encoding="utf-8")
    log.info("BREVO_API_KEY absent : mail écrit dans %s", path)
    return str(path)


def _send_brevo_api(to: str, subject: str, html: str, text: str, unsubscribe_url: str | None) -> str:
    if config.BREVO_API_KEY.startswith("xsmtpsib-"):
        raise RuntimeError(
            "BREVO_API_KEY contient une clé SMTP (xsmtpsib-…). Il faut une clé API (xkeysib-…) : "
            "app.brevo.com → Paramètres → SMTP & API → onglet « Clés API » → Générer une nouvelle clé."
        )
    name, address = parseaddr(config.MAIL_FROM)
    payload = {
        "sender": {"name": name or "Alertes Plongée", "email": address},
        "to": [{"email": to}],
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }
    if unsubscribe_url:  # désabonnement en un clic reconnu par Gmail / Outlook
        payload["headers"] = {"List-Unsubscribe": f"<{unsubscribe_url}>",
                              "List-Unsubscribe-Post": UNSUBSCRIBE_POST}
    resp = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, timeout=30,
                         headers={"api-key": config.BREVO_API_KEY, "accept": "application/json"})
    if resp.status_code >= 400:
        raise RuntimeError(f"Brevo a refusé l'envoi ({resp.status_code}) : {resp.text[:300]}")
    return resp.json().get("messageId", "brevo")
