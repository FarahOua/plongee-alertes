"""Bouton qui se grise dès le clic, dans le navigateur (composant Streamlit sans étape de build).

Un bouton Streamlit ordinaire reste cliquable pendant le calcul : un deuxième clic relance la page.
Ici, le bouton se désactive tout de suite et ne se réactive que lorsque `token` change.

Usage :
    clicked = busy_button("Voir les conditions", token=state.btn_token, key="see")
    if clicked:                      # True une seule fois par clic
        ...calcul...
        state.btn_token += 1         # puis st.rerun() : le bouton se réactive
"""
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_component = components.declare_component("busy_button", path=str(Path(__file__).parent))


def busy_button(label: str, token: int, key: str) -> bool:
    last_key = f"_busy_last_{key}"
    value = _component(label=label, token=token, key=key, default=None)
    if value and value != st.session_state.get(last_key):
        st.session_state[last_key] = value
        return True
    return False
