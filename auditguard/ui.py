"""AuditGuard's glassmorphism theme and reusable Streamlit UI helpers."""

from __future__ import annotations

import html
from collections.abc import Sequence

import plotly.graph_objects as go
import streamlit as st

ACCENTS = {
    "cyan": "#22d3ee",
    "green": "#34d399",
    "amber": "#fbbf24",
    "orange": "#fb923c",
    "red": "#f87171",
    "violet": "#a78bfa",
}

RISK_COLORS = {
    "Low": ACCENTS["green"],
    "Medium": ACCENTS["amber"],
    "High": ACCENTS["orange"],
    "Critical": ACCENTS["red"],
}

GLASS_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --ag-cyan: #22d3ee;
    --ag-green: #34d399;
    --ag-amber: #fbbf24;
    --ag-orange: #fb923c;
    --ag-red: #f87171;
    --ag-violet: #a78bfa;
    --ag-text: #f1f0ff;
    --ag-muted: #a9a6c9;
    --ag-glass: rgba(255, 255, 255, 0.08);
    --ag-border: rgba(255, 255, 255, 0.18);
    --ag-shadow: 0 20px 50px rgba(5, 3, 22, 0.45);
}

html, body, [class*="css"], .stApp { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
html, body, .stApp { min-width: 0; overflow-x: hidden; }

.stApp {
    background: linear-gradient(160deg, #0f0c29 0%, #302b63 52%, #24243e 100%);
    background-attachment: fixed;
    color: var(--ag-text);
}

.ag-orb {
    position: fixed;
    border-radius: 50%;
    filter: blur(90px);
    opacity: 0.42;
    pointer-events: none;
    z-index: 0;
    animation: agFloat 24s ease-in-out infinite alternate;
}
.ag-orb-cyan { width: 420px; height: 420px; top: -120px; left: -80px; background: #22d3ee; }
.ag-orb-magenta { width: 360px; height: 360px; top: 30%; right: -120px; background: #e879f9; animation-delay: -8s; }
.ag-orb-violet { width: 480px; height: 480px; bottom: -180px; left: 26%; background: #7c3aed; animation-delay: -16s; }
@keyframes agFloat {
    0% { transform: translate3d(0, 0, 0) scale(1); }
    50% { transform: translate3d(40px, -30px, 0) scale(1.08); }
    100% { transform: translate3d(-30px, 35px, 0) scale(0.96); }
}

header[data-testid="stHeader"] { visibility: hidden; height: 0; }
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] { visibility: hidden; height: 0; }
[data-testid="stExpandSidebarButton"] {
    visibility: visible !important;
    display: flex !important;
    position: fixed;
    top: 0.7rem;
    left: 0.7rem;
    z-index: 1000000;
    width: 2.2rem;
    height: 2.2rem;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--ag-border);
    border-radius: 12px;
    background: rgba(24, 19, 56, 0.82);
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
}
[data-testid="stExpandSidebarButton"]:hover { background: rgba(34, 211, 238, 0.22); }
[data-testid="stExpandSidebarButton"] svg { color: var(--ag-cyan); fill: var(--ag-cyan); }
.block-container { width: 100%; max-width: 1360px; min-width: 0; padding: 1.4rem 2rem 3rem; position: relative; z-index: 1; }
[data-testid="stHorizontalBlock"], [data-testid="stVerticalBlock"], [data-testid="stColumn"] { min-width: 0; max-width: 100%; }
[data-testid="stPlotlyChart"], [data-testid="stDataFrame"], [data-testid="stTable"] { width: 100%; max-width: 100%; min-width: 0; }

h1, h2, h3, h4, h5, h6, p, span, label, li { color: var(--ag-text); }
[data-testid="stMarkdownContainer"] p { color: #dcd9f2; }
a { color: var(--ag-cyan); }
hr { border-color: rgba(255, 255, 255, 0.12); }

[data-testid="stSidebar"] {
    width: min(24rem, 94vw) !important;
    min-width: min(24rem, 94vw) !important;
    background: rgba(18, 14, 45, 0.72);
    border-right: 1px solid var(--ag-border);
    backdrop-filter: blur(22px) saturate(140%);
    -webkit-backdrop-filter: blur(22px) saturate(140%);
}
[data-testid="stSidebar"] .block-container { padding: 1.4rem 1.1rem 2rem; }
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { letter-spacing: -0.02em; }
.ag-sidebar-brand {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    min-width: 0;
    padding: 0.1rem 0 0.2rem;
}
.ag-sidebar-mark {
    display: inline-flex;
    flex: 0 0 2.7rem;
    width: 2.7rem;
    height: 2.7rem;
    align-items: center;
    justify-content: center;
    border: 1px solid rgba(103, 232, 249, 0.45);
    border-radius: 14px;
    background: linear-gradient(145deg, rgba(34, 211, 238, 0.28), rgba(124, 58, 237, 0.55));
    color: #ffffff;
    font-size: 0.8rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    box-shadow: 0 8px 22px rgba(34, 211, 238, 0.18);
}
.ag-sidebar-logo {
    color: #ffffff;
    font-size: 1.22rem;
    font-weight: 800;
    letter-spacing: -0.035em;
    line-height: 1.1;
}
.ag-sidebar-tagline {
    margin-top: 0.28rem;
    color: #bdb9dc;
    font-size: 0.7rem;
    line-height: 1.35;
}

.ag-hero {
    position: relative;
    overflow: hidden;
    padding: 2.1rem 2.3rem;
    margin-bottom: 1.4rem;
    border: 1px solid var(--ag-border);
    border-radius: 24px;
    background:
        radial-gradient(circle at 82% 12%, rgba(34, 211, 238, 0.20), transparent 42%),
        radial-gradient(circle at 8% 90%, rgba(167, 139, 250, 0.24), transparent 46%),
        rgba(255, 255, 255, 0.06);
    box-shadow: var(--ag-shadow), inset 0 1px 0 rgba(255, 255, 255, 0.16);
    backdrop-filter: blur(18px) saturate(140%);
    -webkit-backdrop-filter: blur(18px) saturate(140%);
    animation: agFade 0.5s ease both;
}
.ag-hero-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.ag-logo {
    margin: 0;
    font-size: clamp(2.4rem, 5vw, 3.9rem);
    font-weight: 800;
    line-height: 1;
    letter-spacing: -0.05em;
    background: linear-gradient(100deg, #ffffff 3%, #67e8f9 45%, #c4b5fd 92%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}
.ag-tagline { margin: 0.55rem 0 0; color: #c9c6e8; font-size: 1.02rem; }
.ag-eyebrow {
    margin-bottom: 0.45rem;
    color: #8ee7f5;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.2em;
    text-transform: uppercase;
}
.ag-status {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.42rem 0.85rem;
    border: 1px solid var(--ag-border);
    border-radius: 999px;
    background: rgba(15, 12, 41, 0.45);
    color: #d9d6f5;
    font-size: 0.78rem;
    font-weight: 600;
    white-space: nowrap;
    backdrop-filter: blur(12px);
}
.ag-status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ag-green); box-shadow: 0 0 12px var(--ag-green); }
.ag-status.complete .ag-status-dot { background: var(--ag-cyan); box-shadow: 0 0 12px var(--ag-cyan); }
.ag-status.ready .ag-status-dot { animation: agPulse 1.8s ease-in-out infinite; }
@keyframes agPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }

.ag-card, .ag-kpi {
    border: 1px solid var(--ag-border);
    border-radius: 20px;
    background: var(--ag-glass);
    box-shadow: var(--ag-shadow), inset 0 1px 0 rgba(255, 255, 255, 0.10);
    backdrop-filter: blur(18px) saturate(140%);
    -webkit-backdrop-filter: blur(18px) saturate(140%);
    transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
}
.ag-card { padding: 1.15rem 1.25rem; margin: 0.3rem 0 1rem; animation: agFade 0.45s ease both; }
.ag-card:hover, .ag-kpi:hover {
    transform: translateY(-3px);
    border-color: rgba(34, 211, 238, 0.42);
    box-shadow: 0 26px 60px rgba(5, 3, 22, 0.55), 0 0 28px rgba(34, 211, 238, 0.13);
}
.ag-card-head { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.55rem; }
.ag-card-head h3 { margin: 0; font-size: 1rem; font-weight: 700; letter-spacing: -0.01em; }
.ag-card-icon { font-size: 1.05rem; }
.ag-card-body { color: #d9d6ef; font-size: 0.92rem; line-height: 1.65; }
.ag-card-body p:last-child { margin-bottom: 0; }

.ag-kpi { position: relative; padding: 1.05rem 1.1rem; border-top: 3px solid var(--kpi, var(--ag-cyan)); overflow: hidden; }
.ag-kpi::after {
    content: "";
    position: absolute;
    inset: auto -36px -46px auto;
    width: 120px;
    height: 120px;
    border-radius: 50%;
    background: var(--kpi, var(--ag-cyan));
    opacity: 0.10;
    filter: blur(20px);
}
.ag-kpi-top { display: flex; align-items: center; gap: 0.4rem; }
.ag-kpi-icon { font-size: 0.9rem; opacity: 0.9; }
.ag-kpi-label { color: var(--ag-muted); font-size: 0.68rem; font-weight: 700; letter-spacing: 0.13em; text-transform: uppercase; }
.ag-kpi-value { margin-top: 0.35rem; color: var(--kpi, var(--ag-cyan)); font-size: 1.65rem; font-weight: 800; letter-spacing: -0.04em; line-height: 1.1; }
.ag-kpi-sub { margin-top: 0.22rem; color: #a9a6c9; font-size: 0.74rem; min-height: 1rem; }

[class*="st-key-kpi_"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: 0.65rem; }
[class*="st-key-kpi_"] [data-testid="stColumn"] {
    flex: 1 1 190px !important;
    width: auto !important;
    min-width: 180px !important;
}

.ag-section { margin: 1.4rem 0 0.55rem; }
.ag-section h3 { margin: 0; font-size: 1.12rem; letter-spacing: -0.02em; }
.ag-section p { margin: 0.18rem 0 0; color: var(--ag-muted); font-size: 0.84rem; }

.ag-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.34rem;
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    border: 1px solid color-mix(in srgb, var(--badge) 55%, transparent);
    background: color-mix(in srgb, var(--badge) 16%, transparent);
    color: var(--badge);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.01em;
    white-space: nowrap;
}
.ag-badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--badge); }
.ag-badge-low { --badge: #34d399; }
.ag-badge-medium { --badge: #fbbf24; }
.ag-badge-high { --badge: #fb923c; }
.ag-badge-critical { --badge: #f87171; }

.ag-empty {
    padding: 3.4rem 1.6rem;
    border: 1px dashed rgba(255, 255, 255, 0.22);
    border-radius: 22px;
    background: rgba(255, 255, 255, 0.045);
    text-align: center;
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    animation: agFade 0.4s ease both;
}
.ag-empty-icon {
    display: inline-flex; align-items: center; justify-content: center;
    width: 3.4rem; height: 3.4rem; border-radius: 16px;
    border: 1px solid rgba(34, 211, 238, 0.35);
    background: linear-gradient(145deg, rgba(34, 211, 238, 0.18), rgba(167, 139, 250, 0.16));
    color: #e9f9ff; font-weight: 800; font-size: 0.95rem; letter-spacing: 0.08em;
}
.ag-empty h3 { margin: 0.8rem 0 0.35rem; font-size: 1.05rem; }
.ag-empty p { max-width: 560px; margin: 0 auto; color: var(--ag-muted); font-size: 0.9rem; line-height: 1.65; }

.ag-schema { margin-top: 0.6rem; }
.ag-tags { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.5rem; }
.ag-tag {
    padding: 0.24rem 0.52rem; border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.18);
    background: rgba(255, 255, 255, 0.07);
    color: #dcd9f2; font-family: ui-monospace, Consolas, monospace; font-size: 0.73rem;
}
.ag-tag.optional { border-style: dashed; color: #b8b4d8; }
.ag-note { color: var(--ag-muted); font-size: 0.8rem; line-height: 1.6; }
.ag-detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.65rem; margin: 0.7rem 0; }
.ag-detail { padding: 0.6rem 0.7rem; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 12px; background: rgba(15, 12, 41, 0.32); }
.ag-detail .k { color: var(--ag-muted); font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 700; }
.ag-detail .v { margin-top: 0.18rem; color: #f2f0ff; font-size: 0.9rem; word-break: break-word; }
.ag-reasons { margin: 0.45rem 0 0; padding-left: 1.1rem; }
.ag-reasons li { margin: 0.28rem 0; color: #e2dff7; }
.ag-footer { padding: 2.2rem 0 0.5rem; color: #8d89ae; font-size: 0.76rem; text-align: center; }

.stButton > button, .stDownloadButton > button {
    min-height: 2.65rem;
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 14px;
    background: linear-gradient(135deg, #22d3ee 0%, #7c3aed 100%);
    color: #ffffff;
    font-weight: 700;
    box-shadow: 0 12px 28px rgba(34, 211, 238, 0.20), 0 6px 18px rgba(124, 58, 237, 0.28);
    transition: transform 140ms ease, box-shadow 140ms ease, filter 140ms ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    transform: translateY(-2px);
    filter: brightness(1.08);
    box-shadow: 0 18px 36px rgba(34, 211, 238, 0.30), 0 10px 26px rgba(124, 58, 237, 0.36);
}
.stButton > button:focus, .stDownloadButton > button:focus { box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.35); }
.stButton > button, .stDownloadButton > button { width: 100%; min-width: 0; white-space: normal; }

[data-testid="stFileUploader"] {
    padding: 0.6rem;
    border: 1px solid var(--ag-border);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.05);
}
[data-testid="stFileUploader"] section { background: transparent; border-radius: 12px; }
[data-testid="stFileUploaderDropzone"] { background: rgba(15, 12, 41, 0.32); border: 1px dashed rgba(255, 255, 255, 0.22); border-radius: 12px; }

[data-baseweb="select"] > div,
[data-baseweb="input"] > div,
[data-baseweb="base-input"],
.stTextInput input, .stNumberInput input, .stDateInput input {
    background: rgba(15, 12, 41, 0.48) !important;
    border-color: rgba(255, 255, 255, 0.18) !important;
    color: var(--ag-text) !important;
    border-radius: 11px !important;
}
[data-baseweb="popover"] [data-baseweb="menu"] { background: #241f45 !important; border: 1px solid var(--ag-border); }
[data-baseweb="menu"] li { color: var(--ag-text) !important; }
[data-baseweb="slider"] { padding-top: 0.35rem; }
[data-testid="stFileUploader"], [data-testid="stTextInput"], [data-testid="stSelectbox"],
[data-testid="stMultiSelect"], [data-testid="stDateInput"], [data-testid="stNumberInput"] {
    min-width: 0;
    max-width: 100%;
}

[data-testid="stTabs"] [role="tablist"] {
    gap: 0.4rem;
    padding: 0.32rem;
    border: 1px solid var(--ag-border);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(16px);
    width: fit-content;
    max-width: 100%;
    flex-wrap: wrap;
    overflow: visible;
    height: auto;
}
[data-testid="stTabs"] [data-testid="stTab"] {
    border-radius: 999px;
    padding: 0.42rem 1rem;
    color: #bdb9dc;
    font-weight: 600;
    background: transparent;
    cursor: pointer;
}
[data-testid="stTabs"] [data-testid="stTab"]:hover { color: #ffffff; }
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] {
    color: #ffffff;
    background: linear-gradient(135deg, rgba(34, 211, 238, 0.32), rgba(124, 58, 237, 0.42));
    box-shadow: 0 6px 18px rgba(34, 211, 238, 0.14);
}
[data-testid="stTabs"] [data-testid="stTab"] p { color: inherit; font-weight: inherit; }
[data-testid="stTabs"] [data-testid="stTab"] { min-width: 0; white-space: normal; text-align: center; }
[data-testid="stTabs"] [data-testid="stTabsScrollLeft"],
[data-testid="stTabs"] [data-testid="stTabsScrollRight"],
[data-testid="stTabs"] .react-aria-SelectionIndicator { display: none; }

[data-testid="stDataFrame"] {
    overflow: hidden;
    border: 1px solid var(--ag-border);
    border-radius: 16px;
    background: rgba(15, 12, 41, 0.35);
}
[data-testid="stDataFrame"] * { font-family: 'Inter', sans-serif; }
[data-testid="stAlert"] {
    border: 1px solid var(--ag-border);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.06);
    backdrop-filter: blur(14px);
    color: var(--ag-text);
}
[data-testid="stExpander"] details {
    border: 1px solid var(--ag-border);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(14px);
}
[data-testid="stExpander"] summary { color: #e4e1fa; font-weight: 600; }
[data-testid="stMetric"] {
    padding: 0.9rem 1rem;
    border: 1px solid var(--ag-border);
    border-radius: 16px;
    background: var(--ag-glass);
    backdrop-filter: blur(16px);
}
[data-testid="stMetricValue"] { color: var(--ag-cyan); }

div[data-testid="stToast"] { background: #241f45; color: var(--ag-text); border: 1px solid var(--ag-border); }
.stSpinner > div { border-top-color: var(--ag-cyan) !important; }
.stProgress > div > div > div > div { background: linear-gradient(90deg, #22d3ee, #a78bfa); }

@keyframes agFade { from { opacity: 0; transform: translateY(7px); } to { opacity: 1; transform: translateY(0); } }

@media (max-width: 770px) {
    .block-container { padding: 0.9rem 0.75rem 2rem; }
    [data-testid="stSidebar"] {
        width: min(94vw, 24rem) !important;
        min-width: min(94vw, 24rem) !important;
    }
    [data-testid="stSidebar"] .block-container { padding: 1rem 0.8rem 1.5rem; }
    .ag-hero { padding: 1.4rem 1.1rem; border-radius: 20px; }
    .ag-hero-top { flex-direction: column; }
    .ag-kpi-value { font-size: 1.38rem; }
    .ag-kpi { padding: 0.9rem 0.95rem; }
    .ag-detail-grid { grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); }
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: 0.65rem; }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 1 1 100% !important;
        width: 100% !important;
        min-width: 100% !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        width: 100%;
        border-radius: 18px;
        gap: 0.25rem;
    }
    [data-testid="stTabs"] [data-testid="stTab"] {
        flex: 1 1 30%;
        padding: 0.4rem 0.55rem;
        font-size: 0.86rem;
    }
    [data-testid="stPlotlyChart"] { min-height: 0; }
    [data-testid="stDataFrame"] { overflow-x: auto; }
}

@media (max-width: 480px) {
    .block-container { padding: 0.7rem 0.55rem 1.5rem; }
    .ag-hero { padding: 1.1rem 0.85rem; }
    .ag-logo { font-size: clamp(2rem, 12vw, 2.7rem); }
    .ag-tagline { font-size: 0.9rem; }
    .ag-card { padding: 0.9rem; border-radius: 16px; }
    .ag-kpi { padding: 0.8rem; }
    .ag-kpi-value { font-size: 1.2rem; }
    .ag-detail-grid { grid-template-columns: 1fr; }
    .ag-sidebar-brand { gap: 0.6rem; }
    .ag-sidebar-mark { flex-basis: 2.4rem; width: 2.4rem; height: 2.4rem; }
    .ag-sidebar-logo { font-size: 1.08rem; }
    .ag-sidebar-tagline { font-size: 0.66rem; }
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        width: 100%;
        padding: 0.28rem;
        gap: 0.28rem;
        border-radius: 20px;
    }
    [data-testid="stTabs"] [data-testid="stTab"] {
        width: 100%;
        min-height: 2.45rem;
        padding: 0.42rem 0.35rem;
        font-size: 0.78rem;
        line-height: 1.15;
    }
    .stButton > button, .stDownloadButton > button { min-height: 2.5rem; }
}
</style>
"""

ORBS_HTML = """
<div class="ag-orb ag-orb-cyan"></div>
<div class="ag-orb ag-orb-magenta"></div>
<div class="ag-orb ag-orb-violet"></div>
"""


def inject_css() -> None:
    """Inject the global stylesheet and the three animated background orbs."""
    st.markdown(GLASS_CSS + ORBS_HTML, unsafe_allow_html=True)


def risk_color(level: object) -> str:
    """Return the accent color for a risk level."""
    return RISK_COLORS.get(str(level), ACCENTS["cyan"])


def risk_badge(level: object) -> str:
    """Return an HTML risk badge for Low, Medium, High, or Critical."""
    safe_level = str(level) if str(level) in RISK_COLORS else "Low"
    return (
        f'<span class="ag-badge ag-badge-{safe_level.lower()}">'
        f"{html.escape(safe_level)}</span>"
    )


def glass_card(title: str, body_html: str, icon: str = "") -> None:
    """Render a glass panel with an optional title and trusted HTML body."""
    icon_markup = (
        f'<span class="ag-card-icon">{html.escape(icon)}</span>' if icon else ""
    )
    st.markdown(
        f"""
        <div class="ag-card">
            <div class="ag-card-head">{icon_markup}<h3>{html.escape(title)}</h3></div>
            <div class="ag-card-body">{body_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(
    label: str,
    value: str,
    sublabel: str = "",
    color: str = ACCENTS["cyan"],
    icon: str = "",
    help_text: str = "",
) -> None:
    """Render one glass KPI card with an accent color and optional icon."""
    icon_markup = f'<span class="ag-kpi-icon">{html.escape(icon)}</span>' if icon else ""
    title_attr = f' title="{html.escape(help_text)}"' if help_text else ""
    st.markdown(
        f"""
        <div class="ag-kpi" style="--kpi:{html.escape(color)};"{title_attr}>
            <div class="ag-kpi-top">{icon_markup}<span class="ag-kpi-label">{html.escape(label)}</span></div>
            <div class="ag-kpi-value">{html.escape(value)}</div>
            <div class="ag-kpi-sub">{html.escape(sublabel)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(text: str, subtitle: str = "") -> None:
    """Render a section heading with an optional muted subtitle."""
    subtitle_markup = f"<p>{html.escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f'<div class="ag-section"><h3>{html.escape(text)}</h3>{subtitle_markup}</div>',
        unsafe_allow_html=True,
    )


def render_hero(status: str = "Ready", ready: bool = True) -> None:
    """Render the gradient AuditGuard logo, tagline, and status pill."""
    state_class = "ready" if ready else "complete"
    st.markdown(
        f"""
        <div class="ag-hero">
            <div class="ag-hero-top">
                <div>
                    <div class="ag-eyebrow">FinTech Expo · Audit Intelligence</div>
                    <h1 class="ag-logo">AuditGuard</h1>
                    <p class="ag-tagline">AI-powered audit red-flag detection · Karachi, Pakistan</p>
                </div>
                <div class="ag-status {state_class}">
                    <span class="ag-status-dot"></span>{html.escape(status)}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state(title: str, message: str, icon: str = "AG") -> None:
    """Render a friendly glass placeholder for a tab with no audit yet."""
    st.markdown(
        f"""
        <div class="ag-empty">
            <div class="ag-empty-icon">{html.escape(icon)}</div>
            <h3>{html.escape(title)}</h3>
            <p>{html.escape(message)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_schema_reference(
    required_columns: Sequence[str],
    optional_columns: Sequence[str] = (),
) -> None:
    """Render the exact input schema as monospace tags."""
    required = "".join(
        f'<span class="ag-tag">{html.escape(str(column))}</span>'
        for column in required_columns
    )
    optional = "".join(
        f'<span class="ag-tag optional">{html.escape(str(column))}</span>'
        for column in optional_columns
    )
    optional_block = (
        f'<p class="ag-note" style="margin:0.7rem 0 0;">Optional test-data column</p>'
        f'<div class="ag-tags">{optional}</div>'
        if optional
        else ""
    )
    st.markdown(
        f"""
        <div class="ag-schema">
            <p class="ag-note" style="margin:0;">Column names must match exactly.</p>
            <div class="ag-tags">{required}</div>
            {optional_block}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer() -> None:
    """Render the application footer."""
    st.markdown(
        '<div class="ag-footer">AuditGuard · AI-powered audit red-flag detection · '
        "Prepared in Karachi, Pakistan · Built for the FinTech Expo · "
        "Demo data is synthetic</div>",
        unsafe_allow_html=True,
    )


def style_fig(fig: go.Figure, height: int = 340) -> go.Figure:
    """Apply transparent, dark, readable styling to a Plotly figure."""
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#e7e4ff", size=12),
        title_font=dict(color="#f3f1ff", size=14),
        margin=dict(l=10, r=10, t=44, b=10),
        hoverlabel=dict(
            bgcolor="#241f45",
            bordercolor="rgba(255,255,255,0.2)",
            font=dict(color="#f3f1ff", family="Inter, sans-serif"),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color="#d7d3f0", size=11),
        ),
        colorway=[
            ACCENTS["cyan"],
            ACCENTS["violet"],
            ACCENTS["green"],
            ACCENTS["amber"],
            ACCENTS["orange"],
            ACCENTS["red"],
        ],
    )
    fig.update_xaxes(
        gridcolor="rgba(255,255,255,0.08)",
        zerolinecolor="rgba(255,255,255,0.10)",
        linecolor="rgba(255,255,255,0.14)",
        tickfont=dict(color="#b9b5d9"),
        title_font=dict(color="#cfcbf0"),
    )
    fig.update_yaxes(
        gridcolor="rgba(255,255,255,0.08)",
        zerolinecolor="rgba(255,255,255,0.10)",
        linecolor="rgba(255,255,255,0.14)",
        tickfont=dict(color="#b9b5d9"),
        title_font=dict(color="#cfcbf0"),
    )
    return fig
