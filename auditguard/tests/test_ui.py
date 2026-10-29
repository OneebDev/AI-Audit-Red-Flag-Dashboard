"""Tests for the glassmorphism theme and reusable UI helpers."""

from __future__ import annotations

import plotly.graph_objects as go

import ui


def _capture(monkeypatch):
    captured: list[tuple[str, dict[str, object]]] = []

    def fake_markdown(body: str, **kwargs: object) -> None:
        captured.append((body, kwargs))

    monkeypatch.setattr(ui.st, "markdown", fake_markdown)
    return captured


def test_stylesheet_contains_required_glass_tokens() -> None:
    css = ui.GLASS_CSS

    assert "linear-gradient(160deg, #0f0c29 0%, #302b63 52%, #24243e 100%)" in css
    assert "rgba(255, 255, 255, 0.08)" in css
    assert "backdrop-filter: blur(18px) saturate(140%)" in css
    assert "@keyframes agFloat" in css
    assert "@keyframes agPulse" in css
    assert "@keyframes agFade" in css
    assert "font-family: 'Inter'" in css
    assert ".ag-badge-critical" in css
    assert ".ag-orb-cyan" in css
    assert ".ag-orb-magenta" in css
    assert ".ag-orb-violet" in css


def test_stylesheet_stacks_columns_at_the_770px_breakpoint() -> None:
    css = ui.GLASS_CSS

    assert "@media (max-width: 770px)" in css
    assert "@media (max-width: 760px)" not in css
    responsive = css.split("@media (max-width: 770px)")[1]
    assert "flex-wrap: wrap" in responsive
    assert "flex: 1 1 100% !important" in responsive
    assert "width: 100% !important" in responsive


def test_stylesheet_constrains_wide_content_and_mobile_controls() -> None:
    css = ui.GLASS_CSS

    assert "overflow-x: hidden" in css
    assert '[data-testid="stPlotlyChart"]' in css
    assert '[data-testid="stDataFrame"]' in css
    assert ".stButton > button, .stDownloadButton > button" in css
    assert "white-space: normal" in css
    assert "@media (max-width: 480px)" in css
    narrow = css.split("@media (max-width: 480px)")[1]
    assert "grid-template-columns: 1fr" in narrow
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in narrow
    assert "min-height: 2.45rem" in narrow
    assert '[data-testid="stTabs"] [role="tablist"]' in narrow


def test_sidebar_and_form_controls_have_narrow_width_rules() -> None:
    css = ui.GLASS_CSS

    assert 'width: min(24rem, 94vw) !important' in css
    assert ".ag-sidebar-brand" in css
    assert ".ag-sidebar-logo" in css
    assert "min-width: min(94vw, 24rem) !important" in css
    assert '[data-testid="stSidebar"] > div:first-child' in css
    assert '[data-testid="stSelectbox"]' in css
    assert "max-width: 100%" in css


def test_collapsed_sidebar_reopen_control_stays_visible() -> None:
    css = ui.GLASS_CSS

    assert '[data-testid="stExpandSidebarButton"]' in css
    rule = css.split('[data-testid="stExpandSidebarButton"] {', 1)[1].split("}", 1)[0]
    assert "visibility: visible !important" in rule
    assert "position: fixed" in rule


def test_kpi_rows_wrap_before_values_clip() -> None:
    css = ui.GLASS_CSS

    assert '[class*="st-key-kpi_"] [data-testid="stColumn"]' in css
    rule = css.split('[class*="st-key-kpi_"] [data-testid="stColumn"] {', 1)[1].split(
        "}", 1
    )[0]
    assert "flex: 1 1 190px !important" in rule
    assert "min-width: 180px !important" in rule


def test_tab_bar_wraps_instead_of_scrolling_labels_away() -> None:
    css = ui.GLASS_CSS

    assert '[data-testid="stTabs"] [role="tablist"]' in css
    assert '[data-testid="stTabs"] [data-testid="stTab"]' in css
    assert '[data-testid="stTabsScrollRight"]' in css
    rule = css.split('[data-testid="stTabs"] [role="tablist"] {', 1)[1].split("}", 1)[0]
    assert "flex-wrap: wrap" in rule
    assert "overflow: visible" in rule


def test_inject_css_adds_the_three_orbs(monkeypatch) -> None:
    captured = _capture(monkeypatch)

    ui.inject_css()

    assert len(captured) == 1
    body, kwargs = captured[0]
    assert "<style>" in body
    assert kwargs.get("unsafe_allow_html") is True
    assert body.count('class="ag-orb ') == 3


def test_risk_colors_and_badges() -> None:
    assert ui.risk_color("Low") == "#34d399"
    assert ui.risk_color("Medium") == "#fbbf24"
    assert ui.risk_color("High") == "#fb923c"
    assert ui.risk_color("Critical") == "#f87171"
    assert ui.risk_color("Unknown") == "#22d3ee"

    assert ui.risk_badge("Critical") == (
        '<span class="ag-badge ag-badge-critical">Critical</span>'
    )
    assert 'ag-badge-low">Low<' in ui.risk_badge("Unknown")
    assert "script" not in ui.risk_badge("<script>")


def test_kpi_card_escapes_text_and_applies_accent(monkeypatch) -> None:
    captured = _capture(monkeypatch)

    ui.kpi_card(
        label="<b>Risk</b>",
        value="<script>alert(1)</script>",
        sublabel="42 entries",
        color="#f87171",
        icon="!",
        help_text='quoted "help"',
    )

    body, _ = captured[0]
    assert "&lt;b&gt;Risk&lt;/b&gt;" in body
    assert "&lt;script&gt;" in body
    assert "--kpi:#f87171" in body
    assert 'title="quoted &quot;help&quot;"' in body
    assert "42 entries" in body


def test_glass_card_escapes_title_but_allows_trusted_body(monkeypatch) -> None:
    captured = _capture(monkeypatch)

    ui.glass_card("<Title>", "<p><strong>Body</strong></p>", icon="AI")

    body, kwargs = captured[0]
    assert "&lt;Title&gt;" in body
    assert "<p><strong>Body</strong></p>" in body
    assert "ag-card-icon" in body
    assert kwargs.get("unsafe_allow_html") is True


def test_section_title_escapes_text(monkeypatch) -> None:
    captured = _capture(monkeypatch)

    ui.section_title("A & B", "Use <carefully>")

    body, _ = captured[0]
    assert "A &amp; B" in body
    assert "Use &lt;carefully&gt;" in body


def test_hero_empty_state_schema_and_footer(monkeypatch) -> None:
    captured = _capture(monkeypatch)

    ui.render_hero("Audit complete", ready=False)
    ui.render_hero("Ready")
    ui.render_empty_state("Nothing here", "Run the audit", icon="OK")
    ui.render_schema_reference(("EntryID", "Date"), ("GroundTruth",))
    ui.render_footer()

    hero, ready_hero, empty, schema, footer = captured

    assert "Audit complete" in hero[0]
    assert "ag-status complete" in hero[0]
    assert "Karachi, Pakistan" in hero[0]
    assert "ag-status ready" in ready_hero[0]
    assert "Nothing here" in empty[0]
    assert ">OK<" in empty[0]
    assert "EntryID" in schema[0] and "Date" in schema[0]
    assert "ag-tag optional" in schema[0] and "GroundTruth" in schema[0]
    assert "AuditGuard" in footer[0]
    assert "Prepared in Karachi, Pakistan" in footer[0]


def test_style_fig_returns_transparent_themed_figure() -> None:
    fig = go.Figure(go.Bar(x=["A"], y=[1]))

    styled = ui.style_fig(fig, height=300)

    assert styled is fig
    assert fig.layout.height == 300
    assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)"
    assert fig.layout.plot_bgcolor == "rgba(0,0,0,0)"
    assert "Inter" in fig.layout.font.family
