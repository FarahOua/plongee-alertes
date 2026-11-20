"""Composant Streamlit invisible : appelle Open-Meteo depuis le navigateur du visiteur.

Usage : result = om_fetch(requests, key="...")  ->  None tant que ce n'est pas fini, puis {"responses": {id: json|None}}
"""
from pathlib import Path

import streamlit.components.v1 as components

_component = components.declare_component("om_fetch", path=str(Path(__file__).parent))


def om_fetch(requests: list, key: str):
    return _component(requests=requests, key=key, default=None)
