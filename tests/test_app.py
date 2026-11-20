from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from conftest import TZ


# --- Comparaison et score --------------------------------------------------------
def full_day_report():
    """Rapport sur des journées complètes, quelle que soit l'heure du test."""
    from backend import openmeteo
    from backend.compare import build_report
    from backend.pipeline import local_now
    bundle = openmeteo.fetch_all(35.69, -5.30)
    return build_report(bundle, local_now(TZ).date(), "M'diq")


def test_report_compares_models_and_skips_uncovered():
    report = full_day_report()
    assert report["timezone"] == TZ
    assert "GFS Wave (NOAA)" not in report["models"]["waves"]       # que des nulls : ignoré
    assert len(report["models"]["waves"]) == 3 and len(report["models"]["wind"]) == 4
    today, tomorrow = report["days"][0], report["days"][1]
    assert today["agreement"] == "élevé" and today["score"] >= 70
    assert today["reliability"]["headline"] == "Les modèles sont d'accord" and today["verdict"] == "Bonnes conditions"
    assert today["summary"]["wave_height"] == {"median": 0.5, "min": 0.4, "max": 0.5}
    assert today["summary"]["wind_from"] == "d'ouest"
    assert today["water_temp"] == 18.2 and today["current_kn"] == 0.3
    assert tomorrow["agreement"] == "faible" and tomorrow["score"] <= 60  # plafonné
    rows = {r["provider"]: r for r in today["per_model"]["rows"]}
    assert rows["Météo-France"]["models"] == "MFWAM + ARPEGE"
    assert rows["Météo-France"]["wave_height"] == 0.4 and rows["Météo-France"]["wind_speed"] == 8
    assert rows["NOAA"]["models"] == "GFS" and rows["NOAA"]["wave_height"] is None  # GFS Wave absent ici


# --- Garde-fou sur les chiffres du LLM ------------------------------------------------
def test_llm_text_with_invented_number_falls_back(monkeypatch):
    from backend import config, writer
    report = full_day_report()
    monkeypatch.setattr(config, "LLM_PROVIDERS", [{"name": "gemini", "base_url": "x", "api_key": "k", "model": "m"}])

    invented = {"subject": "M'diq : top", "intro": "Vagues de 2,7 m aujourd'hui.", "paragraphs": ["Super."]}
    monkeypatch.setattr(writer, "_call_llm", lambda p, f: dict(invented))
    assert writer.write_email_text(report)["source"] == "gabarit"

    d0 = report["days"][0]
    grounded = {"subject": "M'diq : bonnes conditions, modèles d'accord",
                "intro": f"Vagues entre {d0['summary']['wave_height']['min']} et "
                         f"{d0['summary']['wave_height']['max']} m.".replace(".", ",", 2),
                "paragraphs": ["Demain les modèles divergent."]}
    monkeypatch.setattr(writer, "_call_llm", lambda p, f: dict(grounded))
    assert writer.write_email_text(report)["source"] == "gemini"


# --- Parcours complet par l'API ----------------------------------------------------------
def _login(client, monkeypatch, email="plongeur@example.com"):
    from backend import app as app_module
    sent = {}
    monkeypatch.setattr(app_module, "send_email", lambda to, subject, html, text, *a: sent.update(text=text))
    assert client.post("/auth/request-code", json={"email": email}).status_code == 200
    code = sent["text"].split(": ")[1][:6]
    assert client.post("/auth/verify", json={"email": email, "code": "000000" if code != "000000" else "111111"}).status_code == 400
    resp = client.post("/auth/verify", json={"email": email, "code": code})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.get_json()['token']}"}


def test_full_flow(client, monkeypatch):
    from backend.pipeline import run_due
    headers = _login(client, monkeypatch)
    assert client.get("/subscriptions").status_code == 401

    local_today = datetime.now(timezone.utc).astimezone(ZoneInfo(TZ)).date()
    body = {"name": "M'diq", "lat": 35.69, "lon": -5.30, "start_date": local_today.isoformat(),
            "end_date": (local_today + timedelta(days=3)).isoformat(), "send_time": "00:00"}
    resp = client.post("/subscriptions", json=body, headers=headers)
    assert resp.status_code == 201, resp.get_json()
    sub = resp.get_json()
    assert sub["timezone"] == TZ and sub["status"] == "active"

    # Validation
    bad = {**body, "end_date": (local_today - timedelta(days=5)).isoformat()}
    assert client.post("/subscriptions", json=bad, headers=headers).status_code == 400

    # Pause / reprise / modification
    assert client.patch(f"/subscriptions/{sub['id']}", json={"status": "paused"}, headers=headers).get_json()["status"] == "paused"
    assert run_due() == []                                   # en pause : rien
    client.patch(f"/subscriptions/{sub['id']}", json={"status": "active", "send_time": "00:00"}, headers=headers)

    # Changer le planning efface « déjà envoyé » ; une valeur identique ne le fait pas
    with __import__("backend.db", fromlist=["get_db"]).get_db() as conn:
        conn.execute("UPDATE subscriptions SET last_sent_on = ? WHERE id = ?", (local_today.isoformat(), sub["id"]))
    same = client.patch(f"/subscriptions/{sub['id']}", json={"send_time": "00:00"}, headers=headers).get_json()
    assert same["last_sent_on"] == local_today.isoformat()
    changed = client.patch(f"/subscriptions/{sub['id']}", json={"send_time": "00:01"}, headers=headers).get_json()
    assert changed["last_sent_on"] is None
    client.patch(f"/subscriptions/{sub['id']}", json={"send_time": "00:00"}, headers=headers)

    # Envoi programmé : une seule fois par jour
    results = run_due()
    assert [r["status"] for r in results] == ["sent"]
    assert results[0]["text_source"] == "gabarit"
    assert run_due() == []
    outbox = list(Path(__import__("os").environ["OUTBOX_DIR"]).glob("*.html"))
    html = outbox[-1].read_text(encoding="utf-8")
    assert "M&#39;diq" in html or "M'diq" in html
    assert "MFWAM + ARPEGE" in html and "Arrêter cette alerte" in html
    # Mail lisible : fiabilité en toutes lettres, aucune note chiffrée
    assert "/100" not in html and "Score" not in html
    assert "D'accord" in html and "Pas d'accord" in html
    assert "Ce que dit chaque institut" in html

    # Liste avec dernier score et lien du rapport
    item = client.get("/subscriptions", headers=headers).get_json()[0]
    assert item["last_score"] is not None and item["report_url"]
    path = item["report_url"].split("5000", 1)[1]
    assert client.get(path).status_code == 200
    assert client.get(path.split("?")[0]).status_code == 404          # sans jeton

    # Aperçu public
    preview = client.get("/preview?lat=35.69&lon=-5.30").get_json()
    assert any(d["score"] is not None for d in preview["days"])

    # Désabonnement en un clic puis suppression
    with __import__("backend.db", fromlist=["get_db"]).get_db() as conn:
        token = conn.execute("SELECT public_token FROM subscriptions WHERE id = ?", (sub["id"],)).fetchone()[0]
    assert client.get(f"/unsubscribe/{token}").status_code == 200
    assert client.get("/subscriptions", headers=headers).get_json()[0]["status"] == "ended"
    assert client.delete(f"/subscriptions/{sub['id']}", headers=headers).status_code == 200
    assert client.get("/subscriptions", headers=headers).get_json() == []


def test_active_limit_and_ownership(client, monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "MAX_ACTIVE_SUBSCRIPTIONS", 1)
    a = _login(client, monkeypatch, "a@example.com")
    b = _login(client, monkeypatch, "b@example.com")
    today = datetime.now(timezone.utc).date()
    body = {"name": "Spot", "lat": 35.69, "lon": -5.30, "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=2)).isoformat(), "send_time": "06:30"}
    sub = client.post("/subscriptions", json=body, headers=a).get_json()
    assert client.post("/subscriptions", json=body, headers=a).status_code == 400   # limite
    assert client.delete(f"/subscriptions/{sub['id']}", headers=b).status_code == 404  # pas à lui
    assert client.post("/admin/run-due").status_code == 404                 # route supprimée


def test_fill_gaps_and_past_hours():
    from backend import openmeteo
    from backend.compare import build_report
    from backend.pipeline import local_now
    assert openmeteo.fill_gaps([1.0, None, None, 4.0, None]) == [1.0, 2.0, 3.0, 4.0, None]
    assert openmeteo.fill_gaps([350.0, None, 10.0], circular=True) == [350.0, 350.0, 10.0]
    bundle = openmeteo.fetch_all(35.69, -5.30)
    late = build_report(bundle, local_now(TZ).date(), "M'diq", now_hour=22)
    assert late["days"][0]["score"] is None and late["days"][0]["note"] == "Journée de plongée terminée."
    assert late["days"][1]["score"] is not None


def test_all_calls_share_the_spot_timezone(monkeypatch):
    """Bug M'diq : chaque API prenait le fuseau de sa maille (Ceuta / Maroc), dates décalées."""
    import conftest
    from backend import openmeteo
    seen = []

    def spy(url, params, retries=3):
        seen.append(params["timezone"])
        return conftest.fake_http_get(url, params, retries)

    monkeypatch.setattr(openmeteo, "_http_get", spy)
    bundle = openmeteo.fetch_all(35.85, -5.35)
    assert bundle["timezone"] == TZ
    assert seen[0] == "auto"                      # seul l'appel qui trouve le fuseau
    assert set(seen[1:]) == {TZ} and len(seen) == 5   # fuseau + vagues + vent + courant + SST


def test_brevo_api_is_used_when_key_set(monkeypatch):
    from backend import config, mailer
    posted = {}

    class Resp:
        status_code = 201
        def json(self): return {"messageId": "<abc@brevo>"}

    def fake_post(url, json, timeout, headers):
        posted.update(url=url, json=json, headers=headers)
        return Resp()

    monkeypatch.setattr(mailer.requests, "post", fake_post)
    monkeypatch.setattr(config, "BREVO_API_KEY", "xkeysib-test")
    monkeypatch.setattr(config, "MAIL_FROM", "Alertes Plongée <moi@gmail.com>")
    assert mailer.send_email("a@b.fr", "Sujet", "<p>h</p>", "t", "http://x/unsub") == "<abc@brevo>"
    assert posted["url"].endswith("/v3/smtp/email") and posted["headers"]["api-key"] == "xkeysib-test"
    assert posted["json"]["sender"] == {"name": "Alertes Plongée", "email": "moi@gmail.com"}
    assert posted["json"]["to"] == [{"email": "a@b.fr"}]


# --- Visibilité estimée ----------------------------------------------------------
def test_visibility_levels_and_malus():
    from backend.visibility import estimate
    kd = {"2026-11-19": 0.05, "2026-11-20": 0.05, "2026-11-21": 0.2}
    sat = {"date": "2026-11-18", "zsd": 14.2, "kd490": 0.06}
    clear = estimate("2026-11-19", kd, sat, swell_m=0.4, rain={})
    assert clear["level"] == "bonne" and clear["range"] == "15 m et plus" and clear["secchi_m"] == 14.2
    rough = estimate("2026-11-20", kd, sat, swell_m=1.3, rain={"2026-11-19": 8, "2026-11-18": 5})
    assert rough["level"] == "faible" and len(rough["reasons"]) == 3     # houle + pluie : -2 niveaux
    assert estimate("2026-11-21", kd, None, None, None)["level"] == "faible"
    fallback = estimate("2026-11-25", kd, sat, None, None)               # pas de prévision : satellite
    assert fallback["level"] == "bonne" and "satellite" in fallback["reasons"][0]
    assert estimate("2026-11-25", {}, None, None, None)["level"] == "inconnue"


def test_nearest_valid_skips_land_cells():
    import numpy as np
    from backend.visibility import _nearest_valid

    class Coord:
        def __init__(self, v): self.values = np.array(v)

    class FakeDA:
        values = np.array([[np.nan, 0.08], [0.2, 0.3]])   # [lat, lon] ; la maille la plus proche est à terre
        def __getitem__(self, k): return Coord([35.6, 35.7] if k == "latitude" else [-5.4, -5.3])

    assert _nearest_valid(FakeDA(), 35.61, -5.39) == 0.08   # voisine de mer la plus proche (est), pas la terre


def test_visibility_in_report_email_and_llm(monkeypatch):
    from backend import visibility, writer
    from backend.compare import build_report
    from backend.openmeteo import fetch_all
    from backend.pipeline import links_for, local_now, render_email
    monkeypatch.setattr(visibility, "is_configured", lambda: True)
    monkeypatch.setattr(visibility, "fetch_kd490_forecast",
                        lambda lat, lon, start, n: {(start + __import__("datetime").timedelta(days=i)).isoformat(): 0.05
                                                    for i in range(n)})
    monkeypatch.setattr(visibility, "fetch_satellite", lambda lat, lon, d: {"date": "2026-11-18", "zsd": 14.2, "kd490": 0.06})
    monkeypatch.setattr(visibility, "fetch_recent_rain", lambda lat, lon, tz: {})
    b = fetch_all(35.69, -5.30)
    report = visibility.enrich_report(build_report(b, local_now(TZ).date(), "M'diq"), 35.69, -5.30)
    assert report["days"][0]["visibility"]["level"] == "bonne"
    facts = writer.build_facts(report)
    assert facts["jours"][0]["visibilite_estimee"] == "bonne (15 m et plus)"
    assert writer.numbers_are_grounded("Visibilité estimée bonne, 15 m et plus.", facts)
    text = writer.template_text(report)
    assert "Visibilité estimée bonne" in text["paragraphs"][0]
    html, _ = render_email(report, text, links_for({"id": 1, "public_token": "x"}, report["days"][0]["date"]))
    assert "Visibilité" in html and "15 m et plus" in html


def test_visibility_absent_without_credentials(monkeypatch):
    from backend import config, visibility
    monkeypatch.setattr(config, "COPERNICUS_USERNAME", "")
    report = {"days": [{"date": "2026-11-19"}], "timezone": TZ}
    assert visibility.enrich_report(report, 35.69, -5.30) == {"days": [{"date": "2026-11-19"}], "timezone": TZ}
