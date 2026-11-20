"""Frontend Streamlit : carte, conditions de la mer, création et gestion des alertes.

L'habillage (styles, coupe de mer, tableau des instituts) est dans ui.py.

Lancement : streamlit run frontend/streamlit_app.py
"""
import os
import uuid
from datetime import date, timedelta

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

import ui
from clock_picker import clock_picker
from om_fetch import om_fetch

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:5000").rstrip("/")
DEFAULT_POINT = (35.69, -5.30)  # au large de M'diq

st.set_page_config(page_title="Alertes plongée", page_icon="🤿", layout="wide",
                   initial_sidebar_state="collapsed",
                   menu_items={"Get help": None, "Report a bug": None, "About": None})
# Boutons Partager, favori, crayon et GitHub masqués ; indicateur de chargement et menu ⋮ (thème) conservés
st.markdown("<style>[data-testid='stToolbarActions'], [data-testid='stAppDeployButton'], "
            "[data-testid='stDeployButton'] {display: none !important;}</style>",
            unsafe_allow_html=True)
st.markdown(ui.css(), unsafe_allow_html=True)
state = st.session_state
state.setdefault("token", None)
state.setdefault("email", None)
state.setdefault("point", DEFAULT_POINT)
state.setdefault("preview", None)
state.setdefault("job", None)
state.setdefault("code_sent_to", None)


# --- Appels au backend --------------------------------------------------------
def api(method: str, path: str, **kwargs):
    headers = {"Authorization": f"Bearer {state.token}"} if state.token else {}
    try:
        resp = requests.request(method, f"{BACKEND_URL}{path}", headers=headers, timeout=90, **kwargs)
    except requests.RequestException:
        st.error(f"Backend injoignable ({BACKEND_URL}). Lance-le avec : flask --app backend.app run")
        return None
    if resp.status_code == 401:
        state.token = None
        st.query_params.pop("s", None)
        st.warning("Session expirée : reconnecte-toi.")
        return None
    if not resp.ok:
        try:
            st.error(resp.json().get("error", resp.text))
        except ValueError:
            st.error(resp.text)
        return None
    return resp.json()


# Recharger la page crée une nouvelle session Streamlit : la mémoire est vide. Le jeton de connexion
# est donc aussi gardé dans l'adresse de la page (?s=…) et relu ici. Ne partage pas cette adresse
# une fois connecté ; « Se déconnecter » la nettoie.
if not state.token and st.query_params.get("s"):
    state.token = st.query_params["s"]
    me = api("get", "/me")
    if me:
        state.email = me.get("email")
    elif state.token is None:       # jeton refusé (api() l'a déjà effacé)
        st.query_params.pop("s", None)


def server_preview(lat: float, lon: float):
    """Aperçu calculé par le serveur. Renvoie (rapport, bridé) ; bridé=True si Open-Meteo bloque le serveur."""
    try:
        resp = requests.get(f"{BACKEND_URL}/preview", params={"lat": lat, "lon": lon}, timeout=90)
    except requests.RequestException:
        st.error(f"Backend injoignable ({BACKEND_URL}). Lance-le avec : flask --app backend.app run")
        return None, False
    if resp.status_code == 503 and resp.json().get("code") == "rate_limited":
        return None, True
    if not resp.ok:
        try:
            st.error(resp.json().get("error", resp.text))
        except ValueError:
            st.error(resp.text)
        return None, False
    return resp.json(), False


def run_browser_job():
    """Quand Open-Meteo bloque le serveur : le navigateur du visiteur fait les appels, le serveur assemble."""
    job = state.get("job")
    if not job:
        return
    params = {"lat": job["lat"], "lon": job["lon"], **({"tz": job["tz"]} if job.get("tz") else {})}
    plan = api("get", "/preview/plan", params=params)
    if plan is None:
        state.job = None
        return
    result = om_fetch(plan["requests"], key=f"omf_{job['nonce']}_{plan['stage']}") if plan["requests"] else {"responses": {}}
    if result is None:
        st.info("Les modèles répondent, depuis ton navigateur…")
        return
    responses = result.get("responses", {})
    if plan["stage"] == "tz":
        data = next((v for v in responses.values() if v), None)
        if not data or not data.get("timezone"):
            st.error("Impossible de joindre Open-Meteo depuis ton navigateur. Réessaie dans un instant.")
            state.job = None
            return
        state.job = {**job, "tz": data["timezone"]}
        st.rerun()
    report = api("post", "/preview/build", json={"lat": job["lat"], "lon": job["lon"], "tz": plan["tz"],
                                                  "name": "", "responses": responses})
    state.job, state.preview = None, report
    st.rerun()


# --- Carte du fond marin ---------------------------------------------------------------------
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean"


def build_map(lat: float, lon: float) -> folium.Map:
    fmap = folium.Map(location=[lat, lon], zoom_start=10, tiles=None, control_scale=True)
    folium.TileLayer(f"{ESRI}/World_Ocean_Base/MapServer/tile/{{z}}/{{y}}/{{x}}", name="Fond marin",
                     attr="Fond de carte : Esri, GEBCO, NOAA, National Geographic, DeLorme, HERE, Geonames.org",
                     max_native_zoom=10, max_zoom=12).add_to(fmap)
    folium.TileLayer(f"{ESRI}/World_Ocean_Reference/MapServer/tile/{{z}}/{{y}}/{{x}}", name="Noms", overlay=True,
                     attr="Esri", max_native_zoom=10, max_zoom=12).add_to(fmap)
    folium.CircleMarker([lat, lon], radius=16, color="#0E7C86", weight=1, fill=True, fill_opacity=0.18).add_to(fmap)
    folium.CircleMarker([lat, lon], radius=6, color="#ffffff", weight=2, fill=True, fill_color="#0E7C86",
                        fill_opacity=1).add_to(fmap)
    return fmap


# --- Compte ----------------------------------------------------------------------------------------
subs = (api("get", "/subscriptions") or []) if state.token else None

st.markdown(ui.masthead(len(subs) if subs is not None else None), unsafe_allow_html=True)

if state.token:
    who, out = st.columns([3, 1], vertical_alignment="center")
    who.markdown(f'<p class="me">Connecté : {ui.esc(state.email or "ton compte")}</p>', unsafe_allow_html=True)
    if out.button("Se déconnecter", use_container_width=True):
        state.token = state.email = state.code_sent_to = None
        st.query_params.pop("s", None)
        st.rerun()
else:
    with st.expander("Se connecter pour programmer des alertes", expanded=bool(state.code_sent_to)):
        email = st.text_input("Adresse mail", value=state.code_sent_to or "")
        if st.button("Recevoir un code", disabled=not email):
            if api("post", "/auth/request-code", json={"email": email}):
                state.code_sent_to = email
                st.rerun()
        if state.code_sent_to:
            st.caption(f"Code envoyé à {state.code_sent_to}. Pense à regarder les spams.")
            code = st.text_input("Code reçu (6 chiffres)", max_chars=6)
            if st.button("Valider", type="primary", disabled=len(code) != 6):
                data = api("post", "/auth/verify", json={"email": state.code_sent_to, "code": code})
                if data:
                    state.token, state.email = data["token"], data["email"]
                    st.query_params["s"] = state.token
                    st.rerun()

left, right = st.columns([7, 4], gap="large")

# --- Carte et conditions ----------------------------------------------------------------------------
with left:
    st.markdown("## Choisis un spot")
    st.markdown('<p class="hint">Touche la carte, plutôt en mer que sur la côte.</p>', unsafe_allow_html=True)
    lat, lon = state.point
    clicked = st_folium(build_map(lat, lon), height=380, use_container_width=True, returned_objects=["last_clicked"])
    if clicked and clicked.get("last_clicked"):
        new_point = (round(clicked["last_clicked"]["lat"], 4), round(clicked["last_clicked"]["lng"], 4))
        if new_point != state.point:
            state.point, state.preview = new_point, None
            st.rerun()
    st.markdown(f'<p class="where">{ui.coords(*state.point)} <span>point choisi</span></p>', unsafe_allow_html=True)

    if st.button("Voir les conditions", type="primary", use_container_width=True):
        with st.spinner("Les modèles répondent…"):
            state.preview, limited = server_preview(state.point[0], state.point[1])
        if limited:   # Open-Meteo bloque l'adresse IP du serveur : le navigateur prend le relais
            state.job = {"lat": state.point[0], "lon": state.point[1], "tz": None, "nonce": uuid.uuid4().hex[:8]}
            state.preview = None

    run_browser_job()

    report = state.preview
    if report:
        if report.get("warning"):
            st.warning(report["warning"])
        st.markdown("## Les conditions")
        st.markdown(f'<p class="hint">Vagues : {ui.esc(", ".join(report["models"]["waves"]) or "aucun modèle")}. '
                    f'Vent : {ui.esc(", ".join(report["models"]["wind"]) or "aucun modèle")}.</p>',
                    unsafe_allow_html=True)
        st.markdown(ui.day_cards(report), unsafe_allow_html=True)
        first = next((d for d in report["days"] if d.get("per_model")), None)
        if first:
            st.markdown("### Ce que dit chaque institut")
            st.markdown(f'<p class="hint">{ui.esc(first["label"])} à {ui.esc(first["per_model"]["time"])}. '
                        "La barre compare les instituts entre eux.</p>", unsafe_allow_html=True)
            st.markdown(ui.institutes_table(first), unsafe_allow_html=True)

# --- Alertes -----------------------------------------------------------------------------------------
with right:
    st.markdown("## Programme l'alerte")
    st.markdown('<p class="hint">Chaque matin, le verdict de ta plongée arrive par mail.</p>', unsafe_allow_html=True)
    if not state.token:
        st.info("Connecte-toi, en haut de la page, pour recevoir les mails.")
    else:
        with st.form("new_alert", clear_on_submit=False):
            name = st.text_input("Nom du spot", value="M'diq" if state.point == DEFAULT_POINT else "")
            period = st.date_input("Période d'envoi",
                                   value=(date.today(), date.today() + timedelta(days=7)),
                                   min_value=date.today(), format="DD/MM/YYYY")
            send_time = clock_picker("Heure d'envoi (heure locale du spot)", "06:30", key="new_send_time")
            if st.form_submit_button("Créer l'alerte", type="primary", use_container_width=True):
                if not isinstance(period, (tuple, list)) or len(period) != 2:
                    st.error("Choisis une date de début et une date de fin.")
                elif api("post", "/subscriptions", json={
                    "name": name, "lat": state.point[0], "lon": state.point[1],
                    "start_date": period[0].isoformat(), "end_date": period[1].isoformat(),
                    "send_time": send_time,
                    # fuseau déjà trouvé par « Voir les conditions » (utile si Open-Meteo bloque le serveur)
                    "timezone": (state.preview or {}).get("timezone"),
                }):
                    st.success("Alerte créée.")
                    st.rerun()

    st.markdown('<div id="mes-alertes"></div>', unsafe_allow_html=True)
    st.markdown("## Mes alertes")
    if not state.token:
        st.markdown('<p class="hint">Connecte-toi pour voir et gérer tes alertes.</p>', unsafe_allow_html=True)
    elif not subs:
        st.markdown('<p class="hint">Aucune alerte pour l\'instant. Choisis un spot sur la carte, puis programme-la ici.</p>',
                    unsafe_allow_html=True)
    for sub in subs or []:
        with st.container(border=True):
            st.markdown(ui.ticket_head(sub, f"{date.fromisoformat(sub['start_date']):%d/%m/%Y}",
                                       f"{date.fromisoformat(sub['end_date']):%d/%m/%Y}"), unsafe_allow_html=True)
            if sub.get("report_url"):
                st.link_button("Voir le dernier mail", sub["report_url"], use_container_width=True)

            if sub["status"] != "ended":
                c1, c2, c3 = st.columns(3)
                if sub["status"] == "active" and c1.button("Pause", key=f"pause{sub['id']}", use_container_width=True):
                    api("patch", f"/subscriptions/{sub['id']}", json={"status": "paused"}) and st.rerun()
                if sub["status"] == "paused" and c1.button("Reprendre", key=f"resume{sub['id']}", use_container_width=True):
                    api("patch", f"/subscriptions/{sub['id']}", json={"status": "active"}) and st.rerun()
                if c2.button("Mail test", key=f"test{sub['id']}", use_container_width=True):
                    with st.spinner("Envoi…"):
                        if api("post", f"/subscriptions/{sub['id']}/send-now"):
                            st.toast("Mail de test envoyé")
                if c3.button("Supprimer", key=f"del{sub['id']}", use_container_width=True):
                    api("delete", f"/subscriptions/{sub['id']}") and st.rerun()

                with st.expander("Modifier"):
                    with st.form(f"edit{sub['id']}"):
                        new_name = st.text_input("Nom", value=sub["name"])
                        new_period = st.date_input(
                            "Période", format="DD/MM/YYYY",
                            value=(date.fromisoformat(sub["start_date"]), date.fromisoformat(sub["end_date"])))
                        new_time = clock_picker("Heure d'envoi (heure locale du spot)", sub["send_time"],
                                                key=f"send_time_{sub['id']}")
                        move = st.checkbox(f"Déplacer sur le point choisi ({ui.coords(*state.point)})")
                        if st.form_submit_button("Enregistrer", use_container_width=True):
                            payload = {"name": new_name, "send_time": new_time}
                            if isinstance(new_period, (tuple, list)) and len(new_period) == 2:
                                payload["start_date"] = new_period[0].isoformat()
                                payload["end_date"] = new_period[1].isoformat()
                            if move:
                                payload["lat"], payload["lon"] = state.point
                                payload["timezone"] = (state.preview or {}).get("timezone")
                            if api("patch", f"/subscriptions/{sub['id']}", json=payload):
                                st.rerun()
            else:
                if st.button("Supprimer", key=f"del{sub['id']}", use_container_width=True):
                    api("delete", f"/subscriptions/{sub['id']}") and st.rerun()

st.markdown('<p class="foot">Prévisions : Open-Meteo (Météo-France, ECMWF, NOAA, DWD) et Copernicus Marine. '
            "La visibilité est une estimation faite à partir de la couleur de l'eau, pas une mesure. "
            "Fond de carte : Esri.</p>", unsafe_allow_html=True)
