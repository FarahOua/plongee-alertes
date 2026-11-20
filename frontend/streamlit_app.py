"""Frontend Streamlit : carte, aperçu des modèles, création et gestion des alertes.

Lancement : streamlit run frontend/streamlit_app.py
"""
import os
from datetime import date, timedelta

import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

from clock_picker import clock_picker

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:5000").rstrip("/")
DEFAULT_POINT = (35.69, -5.30)  # au large de M'diq
STATUS_LABELS = {"active": "Active", "paused": "En pause", "ended": "Terminée"}
AGREEMENT_ICONS = {"élevé": "🟢", "moyen": "🟠", "faible": "🔴", "inconnu": "⚪"}

st.set_page_config(page_title="Alertes plongée", page_icon="🤿", layout="wide")
state = st.session_state
state.setdefault("token", None)
state.setdefault("email", None)
state.setdefault("point", DEFAULT_POINT)
state.setdefault("preview", None)
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
        st.warning("Session expirée : reconnecte-toi.")
        return None
    if not resp.ok:
        try:
            st.error(resp.json().get("error", resp.text))
        except ValueError:
            st.error(resp.text)
        return None
    return resp.json()


# --- Connexion (barre latérale) ----------------------------------------------------
with st.sidebar:
    st.header("Mon compte")
    if state.token:
        st.success(f"Connecté : {state.email}")
        if st.button("Se déconnecter"):
            state.token = state.email = state.code_sent_to = None
            st.rerun()
    else:
        email = st.text_input("Adresse mail", value=state.code_sent_to or "")
        if st.button("Recevoir un code", disabled=not email):
            if api("post", "/auth/request-code", json={"email": email}):
                state.code_sent_to = email
        if state.code_sent_to:
            code = st.text_input("Code reçu (6 chiffres)", max_chars=6)
            if st.button("Valider", disabled=len(code) != 6):
                data = api("post", "/auth/verify", json={"email": state.code_sent_to, "code": code})
                if data:
                    state.token, state.email = data["token"], data["email"]
                    st.rerun()
    st.divider()
    st.caption("Prévisions : Open-Meteo, Météo-France, ECMWF, NOAA, DWD, Copernicus Marine. ")

st.title("Alertes plongée : comparaison des modèles de mer")
left, right = st.columns([3, 2], gap="large")

# --- Carte et aperçu -------------------------------------------------------------
with left:
    st.subheader("1. Choisis ton spot sur la carte")
    lat, lon = state.point
    fmap = folium.Map(location=[lat, lon], zoom_start=10, control_scale=True)
    folium.Marker([lat, lon], tooltip="Point sélectionné", icon=folium.Icon(color="blue", icon="tint")).add_to(fmap)
    clicked = st_folium(fmap, height=420, use_container_width=True, returned_objects=["last_clicked"])
    if clicked and clicked.get("last_clicked"):
        new_point = (round(clicked["last_clicked"]["lat"], 4), round(clicked["last_clicked"]["lng"], 4))
        if new_point != state.point:
            state.point, state.preview = new_point, None
            st.rerun()
    st.caption(f"Point : {state.point[0]}, {state.point[1]} — clique en mer, pas sur la côte.")

    if st.button("Comparer les modèles sur ce point"):
        with st.spinner("Interrogation des modèles…"):
            state.preview = api("get", "/preview", params={"lat": state.point[0], "lon": state.point[1]})

    report = state.preview
    if report:
        if report.get("warning"):
            st.warning(report["warning"])
        st.caption(f"Vagues : {', '.join(report['models']['waves']) or 'aucun'} · "
                   f"Vent : {', '.join(report['models']['wind']) or 'aucun'}")
        cols = st.columns(len(report["days"]))
        for col, day in zip(cols, report["days"]):
            with col:
                st.markdown(f"**{day['label']}**  \n{day['date_fr']}")
                if day["score"] is None:
                    st.write(day.get("note") or "Pas assez de données")
                    continue
                st.metric("Score", f"{day['score']}/100")
                st.write(f"{AGREEMENT_ICONS[day['agreement']]} Accord {day['agreement']}")
                w, s = day["best_window"], day["summary"]
                st.write(f"Créneau {w['start']}–{w['end']}")
                if s["wave_height"]["median"] is not None:
                    st.write(f"Vagues {s['wave_height']['min']}–{s['wave_height']['max']} m")
                if s["wind_speed"]["median"] is not None:
                    st.write(f"Vent {s['wind_speed']['min']:.0f}–{s['wind_speed']['max']:.0f} nœuds"
                             + (f" {s['wind_from']}" if s["wind_from"] else ""))
                if day.get("water_temp") is not None:
                    st.write(f"Eau {day['water_temp']} °C")
                vis = day.get("visibility")
                if vis and vis.get("range"):
                    st.write(f"Visibilité estimée : {vis['level']} ({vis['range']})")
                    if vis.get("reasons"):
                        st.caption(" · ".join(vis["reasons"]))
        first = next((d for d in report["days"] if d.get("per_model")), None)
        if first:
            st.markdown(f"**Détail par institut, {first['label'].lower()} {first['per_model']['time']}**")
            rows = [{
                # .get : tolère un ancien rapport (backend pas encore relancé, aperçu gardé en mémoire)
                "Institut": r.get("provider") or r.get("model", "?"),
                "Modèles": r.get("models", ""),
                "Vagues (m)": "—" if r["wave_height"] is None else f"{r['wave_height']:g}",
                "Période (s)": "—" if r["wave_period"] is None else f"{r['wave_period']:.0f}",
                "Vent (nœuds)": "—" if r["wind_speed"] is None else f"{r['wind_speed']:.0f}",
            } for r in first["per_model"]["rows"]]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


    st.subheader("2. Programme une alerte")
    if not state.token:
        st.info("Connecte-toi (barre latérale) pour recevoir les mails.")
    else:
        with st.form("new_alert", clear_on_submit=False):
            name = st.text_input("Nom du spot", value="M'diq" if state.point == DEFAULT_POINT else "")
            period = st.date_input("Période d'envoi (du … au …)",
                                   value=(date.today(), date.today() + timedelta(days=7)),
                                   min_value=date.today(), format="DD/MM/YYYY")
            send_time = clock_picker("Heure d'envoi (heure locale du spot)", "06:30", key="new_send_time")
            if st.form_submit_button("Créer l'alerte", type="primary"):
                if not isinstance(period, (tuple, list)) or len(period) != 2:
                    st.error("Choisis une date de début et une date de fin.")
                elif api("post", "/subscriptions", json={
                    "name": name, "lat": state.point[0], "lon": state.point[1],
                    "start_date": period[0].isoformat(), "end_date": period[1].isoformat(),
                    "send_time": send_time,
                }):
                    st.success("Alerte créée.")
                    st.rerun()

# --- Mes alertes -------------------------------------------------------------------
with right:
    st.subheader("Mes alertes")
    if not state.token:
        st.write("Connecte-toi pour voir et gérer tes alertes.")
    else:
        subs = api("get", "/subscriptions") or []
        if not subs:
            st.write("Aucune alerte pour l'instant.")
        for sub in subs:
            with st.container(border=True):
                st.markdown(f"**{sub['name']}** · {STATUS_LABELS[sub['status']]}")
                st.caption(f"Du {date.fromisoformat(sub['start_date']):%d/%m/%Y} au "
                           f"{date.fromisoformat(sub['end_date']):%d/%m/%Y} · envoi à {sub['send_time']} "
                           f"({sub['timezone']}) · point {sub['lat']}, {sub['lon']}")
                if sub.get("last_score") is not None:
                    st.write(f"Dernier score : {sub['last_score']}/100")
                if sub.get("report_url"):
                    st.link_button("Voir le dernier mail", sub["report_url"])

                if sub["status"] != "ended":
                    c1, c2, c3 = st.columns(3)
                    if sub["status"] == "active" and c1.button("Pause", key=f"pause{sub['id']}"):
                        api("patch", f"/subscriptions/{sub['id']}", json={"status": "paused"}) and st.rerun()
                    if sub["status"] == "paused" and c1.button("Reprendre", key=f"resume{sub['id']}"):
                        api("patch", f"/subscriptions/{sub['id']}", json={"status": "active"}) and st.rerun()
                    if c2.button("Mail test", key=f"test{sub['id']}"):
                        with st.spinner("Envoi…"):
                            if api("post", f"/subscriptions/{sub['id']}/send-now"):
                                st.toast("Mail de test envoyé")
                    if c3.button("Supprimer", key=f"del{sub['id']}"):
                        api("delete", f"/subscriptions/{sub['id']}") and st.rerun()

                    with st.expander("Modifier"):
                        with st.form(f"edit{sub['id']}"):
                            new_name = st.text_input("Nom", value=sub["name"])
                            new_period = st.date_input(
                                "Période", format="DD/MM/YYYY",
                                value=(date.fromisoformat(sub["start_date"]), date.fromisoformat(sub["end_date"])))
                            new_time = clock_picker("Heure d'envoi (heure locale du spot)", sub["send_time"],
                                                    key=f"send_time_{sub['id']}")
                            move = st.checkbox(f"Déplacer sur le point sélectionné ({state.point[0]}, {state.point[1]})")
                            if st.form_submit_button("Enregistrer"):
                                payload = {"name": new_name, "send_time": new_time}
                                if isinstance(new_period, (tuple, list)) and len(new_period) == 2:
                                    payload["start_date"] = new_period[0].isoformat()
                                    payload["end_date"] = new_period[1].isoformat()
                                if move:
                                    payload["lat"], payload["lon"] = state.point
                                if api("patch", f"/subscriptions/{sub['id']}", json=payload):
                                    st.rerun()
                else:
                    if st.button("Supprimer", key=f"del{sub['id']}"):
                        api("delete", f"/subscriptions/{sub['id']}") and st.rerun()
