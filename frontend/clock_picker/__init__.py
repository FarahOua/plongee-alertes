"""Sélecteur d'heure en forme d'horloge (composant Streamlit sans étape de build).

Usage : heure = clock_picker("Heure d'envoi", "06:30", key="mon_cle")  ->  "HH:MM"
Cliquer sur l'heure (couronne extérieure 1-12, intérieure 13-00), puis sur les minutes (pas de 5).
"""
from pathlib import Path

import streamlit.components.v1 as components

_component = components.declare_component("clock_picker", path=str(Path(__file__).parent))


def clock_picker(label: str, value: str = "06:30", key: str | None = None) -> str:
    result = _component(label=label, value=value, key=key, default=value)
    return result or value
