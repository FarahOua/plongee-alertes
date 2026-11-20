"""API Flask : connexion, alertes (CRUD), aperçu, rapports web, désabonnement."""
import hmac
import json
import logging
import re
import secrets
from datetime import date

import click
from flask import Flask, abort, g, jsonify, request

from . import auth, config, openmeteo, pipeline
from .db import describe, get_db, init_db
from .mailer import send_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_subscription(data: dict, partial: bool = False) -> dict:
    """Contrôle les champs d'une alerte ; lève ValueError avec un message lisible."""
    out = {}
    if not partial or "name" in data:
        name = str(data.get("name", "")).strip()
        if not 1 <= len(name) <= 60:
            raise ValueError("Le nom du spot doit faire entre 1 et 60 caractères.")
        out["name"] = name
    if not partial or "lat" in data or "lon" in data:
        try:
            lat, lon = float(data["lat"]), float(data["lon"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Coordonnées invalides.")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Coordonnées hors limites.")
        out["lat"], out["lon"] = round(lat, 5), round(lon, 5)
    if not partial or "start_date" in data or "end_date" in data:
        try:
            start = date.fromisoformat(data["start_date"])
            end = date.fromisoformat(data["end_date"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Dates invalides (format AAAA-MM-JJ).")
        if end < start:
            raise ValueError("La date de fin doit être après la date de début.")
        if (end - start).days + 1 > config.MAX_PERIOD_DAYS:
            raise ValueError(f"Période limitée à {config.MAX_PERIOD_DAYS} jours.")
        if not partial and end < date.today():
            raise ValueError("La période est déjà passée.")
        out["start_date"], out["end_date"] = start.isoformat(), end.isoformat()
    if not partial or "send_time" in data:
        send_time = str(data.get("send_time", "06:30"))[:5]
        if not TIME_RE.match(send_time):
            raise ValueError("Heure d'envoi invalide (HH:MM).")
        out["send_time"] = send_time
    if partial and "status" in data:
        if data["status"] not in ("active", "paused"):
            raise ValueError("Statut possible : active ou paused.")
        out["status"] = data["status"]
    return out


def _owned_subscription(sub_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ? AND user_id = ?",
                           (sub_id, g.user["id"])).fetchone()
    if row is None:
        abort(404)
    return dict(row)


def _public(sub: dict) -> dict:
    return {k: sub[k] for k in ("id", "name", "lat", "lon", "start_date", "end_date", "send_time",
                                "timezone", "status", "last_sent_on")}


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False
    init_db()

    @app.errorhandler(ValueError)
    def bad_request(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="Introuvable."), 404

    @app.get("/health")
    def health():
        return {"ok": True}

    # --- Connexion -----------------------------------------------------------
    @app.post("/auth/request-code")
    def request_code():
        email = auth.normalize_email((request.get_json(silent=True) or {}).get("email"))
        code = auth.create_login_code(email)
        try:
            send_email(email, f"Ton code de connexion : {code}",
                       f"<p>Ton code de connexion aux alertes plongée : <strong>{code}</strong></p>"
                       "<p>Il est valable 15 minutes.</p>",
                       f"Ton code de connexion aux alertes plongée : {code}\nIl est valable 15 minutes.")
        except Exception as exc:
            logging.getLogger(__name__).exception("Envoi du code impossible")
            return jsonify(error=f"Envoi du mail impossible ({exc}). Vérifie BREVO_API_KEY et MAIL_FROM."), 502
        return {"sent": True}

    @app.post("/auth/verify")
    def verify():
        data = request.get_json(silent=True) or {}
        email = auth.normalize_email(data.get("email"))
        token = auth.verify_login_code(email, str(data.get("code", "")))
        return {"token": token, "email": email}

    @app.get("/me")
    @auth.login_required
    def me():
        return g.user

    # --- Alertes ---------------------------------------------------------------
    @app.get("/subscriptions")
    @auth.login_required
    def list_subscriptions():
        with get_db() as conn:
            rows = conn.execute(
                "SELECT s.*, (SELECT report_json FROM daily_reports r WHERE r.subscription_id = s.id "
                "ORDER BY report_date DESC LIMIT 1) AS last_report "
                "FROM subscriptions s WHERE user_id = ? ORDER BY status = 'ended', start_date",
                (g.user["id"],),
            ).fetchall()
        out = []
        for row in rows:
            item = _public(dict(row))
            last = json.loads(row["last_report"]) if row["last_report"] else None
            item["last_score"] = last["days"][0]["score"] if last else None
            item["report_url"] = (pipeline.links_for(dict(row), row["last_sent_on"])["report"]
                                  if row["last_sent_on"] else None)
            out.append(item)
        return jsonify(out)

    @app.post("/subscriptions")
    @auth.login_required
    def create_subscription():
        data = _validate_subscription(request.get_json(silent=True) or {})
        with get_db() as conn:
            active = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id = ? AND status = 'active'",
                                  (g.user["id"],)).fetchone()[0]
        if active >= config.MAX_ACTIVE_SUBSCRIPTIONS:
            raise ValueError(f"Maximum {config.MAX_ACTIVE_SUBSCRIPTIONS} alertes actives.")
        tz = openmeteo.resolve_timezone(data["lat"], data["lon"])
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO subscriptions (user_id, name, lat, lon, start_date, end_date, send_time, "
                "timezone, public_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (g.user["id"], data["name"], data["lat"], data["lon"], data["start_date"],
                 data["end_date"], data["send_time"], tz, secrets.token_urlsafe(24)),
            )
            sub_id = cur.fetchone()[0]
        return jsonify(_public(_owned_subscription(sub_id))), 201

    @app.patch("/subscriptions/<int:sub_id>")
    @auth.login_required
    def update_subscription(sub_id):
        sub = _owned_subscription(sub_id)
        payload = request.get_json(silent=True) or {}
        if ("start_date" in payload) != ("end_date" in payload):
            payload.setdefault("start_date", sub["start_date"])
            payload.setdefault("end_date", sub["end_date"])
        if ("lat" in payload) != ("lon" in payload):
            payload.setdefault("lat", sub["lat"])
            payload.setdefault("lon", sub["lon"])
        data = _validate_subscription(payload, partial=True)
        if "lat" in data:
            data["timezone"] = openmeteo.resolve_timezone(data["lat"], data["lon"])
        if data.get("status") == "active" and sub["status"] == "ended":
            raise ValueError("Alerte terminée : crée une nouvelle alerte.")
        # Si le planning change (heure, dates, lieu), l'alerte doit pouvoir repartir aujourd'hui :
        # on efface « déjà envoyé aujourd'hui ». Une valeur identique ou une simple pause ne compte pas.
        if any(k in data and data[k] != sub[k]
               for k in ("send_time", "start_date", "end_date", "lat", "lon")):
            data["last_sent_on"] = None
        if data:
            sets = ", ".join(f"{k} = ?" for k in data)
            with get_db() as conn:
                conn.execute(f"UPDATE subscriptions SET {sets} WHERE id = ?", (*data.values(), sub_id))
        return jsonify(_public(_owned_subscription(sub_id)))

    @app.delete("/subscriptions/<int:sub_id>")
    @auth.login_required
    def delete_subscription(sub_id):
        _owned_subscription(sub_id)
        with get_db() as conn:
            conn.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
        return {"deleted": sub_id}

    @app.post("/subscriptions/<int:sub_id>/send-now")
    @auth.login_required
    def send_now(sub_id):
        """Envoi immédiat d'un mail de test (n'empêche pas l'envoi programmé du jour)."""
        sub = _owned_subscription(sub_id)
        report = pipeline.make_report(sub["lat"], sub["lon"], sub["name"], sub["timezone"])
        text = pipeline.write_email_text(report)
        links = pipeline.links_for(sub, report["days"][0]["date"])
        html, plain = pipeline.render_email(report, text, links)
        try:
            send_email(g.user["email"], "[Test] " + text["subject"], html, plain, links["unsubscribe"])
        except Exception as exc:
            return jsonify(error=f"Envoi du mail impossible ({exc}). Vérifie BREVO_API_KEY et MAIL_FROM."), 502
        return {"sent": True, "text_source": text.get("source")}

    # --- Aperçu sans abonnement ----------------------------------------------------
    @app.get("/preview")
    def preview():
        try:
            lat, lon = float(request.args["lat"]), float(request.args["lon"])
        except (KeyError, ValueError):
            raise ValueError("Paramètres lat et lon requis.")
        try:
            report = pipeline.make_report(lat, lon, request.args.get("name", ""))
        except openmeteo.OpenMeteoError as exc:
            return jsonify(error=f"{exc} Le point est peut-être à terre : clique plus au large."), 422
        if not report["models"]["waves"]:
            report["warning"] = "Aucun modèle de vagues ici : le point est peut-être à terre."
        return jsonify(report)

    # --- Pages publiques (liens du mail) -------------------------------------------
    @app.get("/reports/<int:sub_id>/<report_date>")
    def report_page(sub_id, report_date):
        with get_db() as conn:
            row = conn.execute(
                "SELECT r.html, s.public_token FROM daily_reports r JOIN subscriptions s ON s.id = r.subscription_id "
                "WHERE r.subscription_id = ? AND r.report_date = ?", (sub_id, report_date)).fetchone()
        if row is None or not hmac.compare_digest(row["public_token"], request.args.get("t", "")):
            abort(404)
        return row["html"]

    @app.route("/unsubscribe/<token>", methods=["GET", "POST"])
    def unsubscribe(token):
        with get_db() as conn:
            cur = conn.execute("UPDATE subscriptions SET status = 'ended' WHERE public_token = ?", (token,))
        if cur.rowcount == 0:
            abort(404)
        return ("<html><body style='font-family:Arial;padding:24px'><h2>Alerte arrêtée</h2>"
                "<p>Tu ne recevras plus de mail pour cette alerte.</p></body></html>")

    # --- Traitement quotidien : commande `flask run-due`, lancée toutes les 15 min -------------
    @app.cli.command("run-due")
    def run_due_command():
        """Traite les alertes dues (à lancer toutes les 15 minutes par cron)."""
        for result in pipeline.run_due():
            print(result)

    @app.cli.command("test-mail")
    @click.argument("to")
    def test_mail_command(to):
        """Envoie un mail de test à l'adresse TO pour vérifier la configuration Brevo."""
        where = send_email(to, "Test alertes plongée", "<p>L'envoi de mails fonctionne.</p>",
                           "L'envoi de mails fonctionne.")
        print("Envoyé à", to, "→", where)

    @app.cli.command("init-db")
    def init_db_command():
        init_db()
        print("Base initialisée :", describe())

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
