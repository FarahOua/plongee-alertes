"""Habillage du site : feuille de style et morceaux de HTML.

Idée : la page se lit comme un carnet de plongée posé sur une carte marine. Chaque journée est une
« coupe de mer » : la surface bouge avec la hauteur des vagues, la lumière descend jusqu'à la
visibilité estimée. Le reste reste sobre pour laisser cette coupe au premier plan.
"""
import html
import math

FONT_URL = ("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,300..800"
            "&display=swap")

# Profondeur (m) représentée pour chaque niveau de visibilité estimée
LEVEL_DEPTH = {"bonne": 15.0, "moyenne": 11.5, "faible": 5.0}

CSS = """
@import url('__FONT__');
:root {
  --abyss: #0B2B3B; --reef: #0E7C86; --kelp: #1E7F57; --amber: #F2B84B; --coral: #C23B22;
  --line: rgba(128,128,128,.30); --soft: rgba(128,128,128,.08);
}
/* Police : choisie élément par élément pour ne pas écraser les icônes de Streamlit */
html body .stApp :where(p, h1, h2, h3, h4, label, button, input, textarea, li, td, th, a, summary,
  [data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"]) {
  font-family: 'Bricolage Grotesque', system-ui, -apple-system, 'Segoe UI', sans-serif;
  font-optical-sizing: auto;
}
html body .stApp .block-container { max-width: 1180px; padding: 1.2rem 1rem 4rem; }
@media (min-width: 900px) { html body .stApp .block-container { padding: 2rem 2rem 4rem; } }

/* En-tête */
.mast { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: .6rem 1.5rem; margin: .4rem 0 1.2rem; }
.mast h1 { margin: 0; padding: 0; font-size: clamp(2rem, 6vw, 3.1rem); line-height: 1; font-weight: 750; letter-spacing: -.035em; }
.mast p { margin: .5rem 0 0; max-width: 34rem; font-size: 1.05rem; line-height: 1.4; opacity: .8; }
.jump { display: inline-flex; align-items: center; min-height: 44px; padding: 0 1rem; border-radius: 999px; border: 1px solid var(--line);
  font-weight: 600; text-decoration: none; color: inherit; }
.jump:hover { border-color: var(--reef); color: var(--reef); }

/* Titres de section */
html body .stApp h2 { font-size: 1.45rem; font-weight: 700; letter-spacing: -.02em; margin: 1.6rem 0 .2rem; padding: 0; }
.hint { margin: 0 0 .7rem; opacity: .72; font-size: .95rem; line-height: 1.4; }
.where { margin: .5rem 0 .2rem; font-variant-numeric: tabular-nums; font-weight: 600; }
.where span { opacity: .65; font-weight: 400; }

/* Boutons, champs, focus */
html body .stApp :is(.stButton > button, .stFormSubmitButton > button, [data-testid="stLinkButton"] a) {
  min-height: 44px; border-radius: 12px; border: 1px solid var(--line); font-weight: 600; transition: border-color .15s, background-color .15s;
}
html body .stApp :is(button[kind="primary"], button[data-testid="stBaseButton-primary"],
  button[data-testid="stBaseButton-primaryFormSubmit"]) { background: var(--reef); border-color: var(--reef); color: #fff; }
html body .stApp :is(button[kind="primary"], button[data-testid="stBaseButton-primary"],
  button[data-testid="stBaseButton-primaryFormSubmit"]):hover { background: #0B6770; border-color: #0B6770; color: #fff; }
html body .stApp :is(.stButton > button, .stFormSubmitButton > button, [data-testid="stLinkButton"] a):hover { border-color: var(--reef); }
html body .stApp :is(input, textarea, [data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="base-input"]) { border-radius: 10px; }
html body .stApp :is(button, input, textarea, a, summary):focus-visible { outline: 3px solid var(--amber); outline-offset: 2px; }
html body .stApp [data-testid="stVerticalBlockBorderWrapper"] { border-radius: 16px; }
html body .stApp [data-testid="stExpander"] { border-radius: 14px; }

/* Pastilles */
.pill { display: inline-flex; align-items: center; gap: .4rem; padding: .22rem .75rem; border-radius: 999px; font-weight: 650; font-size: .85rem; line-height: 1.3; white-space: nowrap; }
.t-good { background: var(--kelp); color: #fff; }
.t-mid { background: var(--amber); color: #2b1e00; }
.t-bad { background: var(--coral); color: #fff; }
.t-off { background: var(--soft); border: 1px solid var(--line); }

/* Journées : une coupe de mer par jour */
.days, .scroll { max-width: 100%; }
.days { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin: .6rem 0 1rem; }
.day { border: 1px solid var(--line); border-radius: 18px; overflow: hidden; display: flex; flex-direction: column; }
.day-head { display: flex; flex-direction: column; align-items: flex-start; gap: .55rem; padding: .9rem 1rem .8rem; }
.day-head b { display: block; font-size: 1.15rem; letter-spacing: -.01em; }
.day-head small { display: block; opacity: .7; font-size: .9rem; margin-top: .1rem; }
.sea { display: block; width: 100%; height: auto; }
.facts { margin: 0; padding: .55rem 1rem .2rem; }
.facts div { display: flex; justify-content: space-between; gap: 1rem; padding: .42rem 0; border-bottom: 1px solid var(--line); font-size: .95rem; }
.facts div:last-child { border-bottom: 0; }
.facts dt { opacity: .72; }
.facts dd { margin: 0; font-weight: 650; text-align: right; font-variant-numeric: tabular-nums; }
.why { margin: 0; padding: 0 1rem; font-size: .82rem; opacity: .65; line-height: 1.35; }
.trust { margin: 0; padding: .75rem 1rem 1rem; display: grid; grid-template-columns: auto 1fr; gap: 0 .6rem; align-items: baseline; font-size: .95rem; }
.trust small { grid-column: 2; opacity: .72; font-size: .88rem; }
.dot { width: .7rem; height: .7rem; border-radius: 50%; display: inline-block; transform: translateY(.05rem); }
.d-ok { background: var(--kelp); } .d-warn { background: var(--amber); } .d-bad { background: var(--coral); }
.empty { padding: 0 1rem 1.2rem; margin: 0; opacity: .75; }
.swipe { display: none; font-size: .85rem; opacity: .65; margin: 0 0 .6rem; }
@media (max-width: 720px) {
  .days { display: flex; overflow-x: auto; scroll-snap-type: x mandatory; margin: .6rem -1rem 1rem; padding: 0 1rem 8px; gap: 12px; -webkit-overflow-scrolling: touch; }
  .day { flex: 0 0 86%; scroll-snap-align: center; }
  .swipe { display: block; }
}

/* Tableau des instituts : la barre derrière le chiffre se lit d'un coup d'œil */
.scroll { overflow-x: auto; margin-bottom: .5rem; }
.inst { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; min-width: 400px; }
.inst th { text-align: left; font-weight: 600; font-size: .85rem; opacity: .7; padding: .4rem .6rem; border-bottom: 1px solid var(--line); }
.inst td { padding: .55rem .6rem; border-bottom: 1px solid var(--line); }
.inst td.who b { display: block; }
.inst td.who small { opacity: .65; }
.inst td.m { background: linear-gradient(90deg, rgba(14,124,134,.26) var(--w, 0%), transparent var(--w, 0%)); font-weight: 600; }

/* Alertes */
.tk-top { display: flex; justify-content: space-between; align-items: center; gap: .6rem; }
.tk-top b { font-size: 1.15rem; letter-spacing: -.01em; }
.tk-meta { margin: .35rem 0 .2rem; line-height: 1.45; font-size: .95rem; }
.tk-meta span { opacity: .7; }
.t-live { background: rgba(30,127,87,.16); color: var(--kelp); border: 1px solid rgba(30,127,87,.45); }
.t-hold { background: rgba(242,184,75,.22); border: 1px solid rgba(242,184,75,.7); }
.me { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; margin: 0 0 .4rem; font-weight: 600; }
.foot { opacity: .6; font-size: .82rem; margin-top: 2.5rem; line-height: 1.5; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; scroll-behavior: auto !important; } }
"""


def css() -> str:
    return "<style>" + CSS.replace("__FONT__", FONT_URL) + "</style>"


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def fr(value: float, digits: int = 1) -> str:
    """Nombre à la française : 0,6 et non 0.6."""
    return f"{value:.{digits}f}".replace(".", ",")


def coords(lat: float, lon: float) -> str:
    return (f"{fr(abs(lat), 2)}° {'N' if lat >= 0 else 'S'}, {fr(abs(lon), 2)}° {'E' if lon >= 0 else 'O'}")


def masthead(alert_count: int | None) -> str:
    link = ""
    if alert_count is not None:
        label = "Mes alertes" if not alert_count else f"Mes alertes ({alert_count})"
        link = f'<a class="jump" href="#mes-alertes">{label}</a>'
    return ('<div class="mast"><div><h1>Alertes plongée</h1>'
            "<p>Les prévisions de six instituts côte à côte, et le verdict de ta plongée par mail chaque matin.</p>"
            f"</div>{link}</div>")


# --- Verdict -------------------------------------------------------------------------------------
def verdict_of(day: dict) -> str | None:
    if day.get("verdict"):
        return day["verdict"]
    score = day.get("score")   # ancien rapport (backend pas encore relancé)
    if score is None:
        return None
    return "Bonnes conditions" if score >= 70 else "Conditions moyennes" if score >= 45 else "Conditions difficiles"


def verdict_tone(verdict: str | None) -> str:
    return {"Bonnes conditions": "good", "Conditions moyennes": "mid", "Conditions difficiles": "bad"}.get(verdict or "", "off")


RELIABILITY_FALLBACK = {
    "élevé": ("ok", "Les modèles sont d'accord", "Tu peux t'y fier."),
    "moyen": ("warn", "Les modèles divergent un peu", "Prévision à prendre avec une marge."),
    "faible": ("bad", "Les modèles ne sont pas d'accord", "Prévision incertaine : revérifie la veille et sur place."),
    "inconnu": ("warn", "Un seul modèle disponible", "Impossible de croiser les sources."),
}


def _reliability(day: dict) -> tuple[str, str, str]:
    r = day.get("reliability")
    if r:
        return r.get("tone", "warn"), r.get("headline", ""), r.get("advice", "")
    return RELIABILITY_FALLBACK.get(day.get("agreement"), RELIABILITY_FALLBACK["inconnu"])


# --- La coupe de mer -----------------------------------------------------------------------------
def sea_svg(day: dict, uid: int) -> str:
    s = day.get("summary") or {}
    hs = (s.get("wave_height") or {}).get("median")
    wind = (s.get("wind_speed") or {}).get("median")
    vis = day.get("visibility") or {}
    W, H, TOP, SCALE = 240, 176, 46, 6.0           # 20 m de profondeur = 120 px
    amp = 2.0 if hs is None else max(1.5, min(15.0, hs * 12))
    pts = [(x, TOP + amp * math.sin(2 * math.pi * x / 52 + 0.8)) for x in range(0, W + 1, 4)]
    water = f"M0,{pts[0][1]:.1f}" + "".join(f" L{x},{y:.1f}" for x, y in pts[1:]) + f" L{W},{H} L0,{H} Z"
    out = [f'<svg class="sea" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(_alt(hs, vis))}" style="font-family:inherit">']
    out.append(f'<defs><linearGradient id="sky{uid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#C9E3E6"/>'
               f'<stop offset="1" stop-color="#EAF4F3"/></linearGradient>'
               f'<linearGradient id="sea{uid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5CC0B6"/>'
               f'<stop offset=".35" stop-color="#1C7C96"/><stop offset="1" stop-color="#0B2B3B"/></linearGradient>'
               f'<linearGradient id="lux{uid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".42"/>'
               f'<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
               f'<clipPath id="clip{uid}"><path d="{water}"/></clipPath></defs>')
    out.append(f'<rect width="{W}" height="{H}" fill="url(#sky{uid})"/>')
    if wind is not None:   # le vent : plus il souffle, plus il y a de traits dans le ciel
        n = int(max(1, min(5, round(wind / 6))))
        for i in range(n):
            y, x = 10 + i * 6.5, 24 + i * 19
            out.append(f'<line x1="{x}" y1="{y}" x2="{x + 26 + wind * 0.9:.0f}" y2="{y}" stroke="#5B7C88" stroke-width="1.6" stroke-linecap="round" opacity=".7"/>')
    out.append(f'<path d="{water}" fill="url(#sea{uid})"/>')
    level = vis.get("level")
    if level in LEVEL_DEPTH:   # la lumière descend jusqu'à la visibilité estimée
        px = LEVEL_DEPTH[level] * SCALE
        out.append(f'<rect clip-path="url(#clip{uid})" x="0" y="{TOP - amp:.0f}" width="{W}" height="{px + amp:.0f}" fill="url(#lux{uid})"/>')
    for d in (5, 10, 15, 20):
        y = TOP + d * SCALE
        out.append(f'<line x1="0" y1="{y}" x2="8" y2="{y}" stroke="#fff" stroke-opacity=".55"/>'
                   f'<text x="13" y="{y}" fill="#fff" fill-opacity=".8" font-size="11" dominant-baseline="middle">{d} m</text>')
    if level in LEVEL_DEPTH:
        y = TOP + LEVEL_DEPTH[level] * SCALE
        out.append(f'<line x1="44" y1="{y}" x2="{W - 10}" y2="{y}" stroke="#fff" stroke-width="1.3" stroke-dasharray="3 3"/>'
                   f'<text x="{W - 10}" y="{y - 6}" fill="#fff" font-size="12" font-weight="600" text-anchor="end">'
                   f'Visibilité {esc(vis.get("range", ""))}</text>')
    out.append("</svg>")
    return "".join(out)


def _alt(hs, vis) -> str:
    parts = ["Coupe de la mer"]
    if hs is not None:
        parts.append(f"vagues de {fr(hs)} m")
    if vis.get("range"):
        parts.append(f"visibilité estimée {vis['range']}")
    return " : ".join(parts[:1]) + (" : " + ", ".join(parts[1:]) if len(parts) > 1 else "")


# --- Cartes des journées --------------------------------------------------------------------------
def _facts(day: dict) -> str:
    s = day.get("summary") or {}
    rows = []
    w = day.get("best_window")
    if w:
        rows.append(("Créneau", f"{w['start']} à {w['end']}"))
    wh = s.get("wave_height") or {}
    if wh.get("median") is not None:
        lo, hi = wh["min"], wh["max"]
        rows.append(("Vagues", f"{fr(lo)} m" if round(lo, 1) == round(hi, 1) else f"{fr(lo)} à {fr(hi)} m"))
    ws = s.get("wind_speed") or {}
    if ws.get("median") is not None:
        txt = f"{ws['min']:.0f} à {ws['max']:.0f} nœuds"
        if s.get("wind_from"):
            txt += f" {s['wind_from']}"
        rows.append(("Vent", txt))
    if day.get("water_temp") is not None:
        rows.append(("Eau", f"{fr(day['water_temp'])} °C"))
    vis = day.get("visibility") or {}
    if vis.get("range"):
        rows.append(("Visibilité", vis["level"]))
    elif day.get("visibility_pending"):
        rows.append(("Visibilité", "en cours de calcul…"))
    body = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in rows)
    why = vis.get("reasons")
    return f'<dl class="facts">{body}</dl>' + (f'<p class="why">{esc("; ".join(why))}</p>' if why else "")


def day_card(day: dict, uid: int) -> str:
    verdict = verdict_of(day)
    head = (f'<div class="day-head"><div><b>{esc(day["label"])}</b><small>{esc(day["date_fr"])}</small></div>'
            f'<span class="pill t-{verdict_tone(verdict)}">{esc(verdict or "Pas de verdict")}</span></div>')
    if day.get("score") is None:
        return f'<article class="day">{head}<p class="empty">{esc(day.get("note") or "Pas assez de données pour cette journée.")}</p></article>'
    tone, headline, advice = _reliability(day)
    trust = (f'<p class="trust"><span class="dot d-{tone}"></span><b>{esc(headline)}</b>'
             f'<small>{esc(advice)}</small></p>')
    return f'<article class="day">{head}{sea_svg(day, uid)}{_facts(day)}{trust}</article>'


def day_cards(report: dict) -> str:
    cards = "".join(day_card(d, i) for i, d in enumerate(report["days"]))
    return f'<p class="swipe">Fais glisser pour voir les autres jours.</p><div class="days">{cards}</div>'


# --- Détail par institut ------------------------------------------------------------------------
def institutes_table(day: dict) -> str:
    pm = day.get("per_model")
    if not pm:
        return ""
    rows = pm["rows"]

    def col(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return max(vals) if vals else 0

    top = {k: col(k) for k in ("wave_height", "wave_period", "wind_speed")}

    def cell(r, key, fmt):
        v = r.get(key)
        if v is None:
            return '<td class="m">—</td>'
        width = 0 if not top[key] else round(100 * v / top[key])
        return f'<td class="m" style="--w:{width}%">{fmt(v)}</td>'

    body = ""
    for r in rows:
        name = r.get("provider") or r.get("model", "?")
        body += (f'<tr><td class="who"><b>{esc(name)}</b><small>{esc(r.get("models", ""))}</small></td>'
                 + cell(r, "wave_height", lambda v: f"{fr(v)} m")
                 + cell(r, "wave_period", lambda v: f"{v:.0f} s")
                 + cell(r, "wind_speed", lambda v: f"{v:.0f} nœuds") + "</tr>")
    return ('<div class="scroll"><table class="inst"><thead><tr><th>Institut</th><th>Vagues</th><th>Période</th>'
            f"<th>Vent</th></tr></thead><tbody>{body}</tbody></table></div>")


# --- Alertes -----------------------------------------------------------------------------------------
STATUS = {"active": ("Active", "t-live"), "paused": ("En pause", "t-hold"), "ended": ("Terminée", "t-off")}


def ticket_head(sub: dict, d1: str, d2: str) -> str:
    label, tone = STATUS.get(sub["status"], (sub["status"], "t-off"))
    city = str(sub.get("timezone", "")).split("/")[-1].replace("_", " ")
    return (f'<div class="tk-top"><b>{esc(sub["name"])}</b><span class="pill {tone}">{label}</span></div>'
            f'<p class="tk-meta">Du {d1} au {d2}<br>Envoi à {esc(sub["send_time"])}, heure de {esc(city)}<br>'
            f'<span>{coords(sub["lat"], sub["lon"])}</span></p>')
