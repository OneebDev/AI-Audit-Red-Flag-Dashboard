"""Calendar heatmaps and date-level insights for the Calendar tab.

The builders are pure functions so they can be tested without Streamlit. They
also tolerate an empty or zero-flag ledger and any date range.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterable, Mapping

import pandas as pd
import plotly.graph_objects as go

from utils import (
    DEFAULT_WEEKEND_DAYS,
    financial_year_label,
    financial_year_months,
    financial_year_start,
    format_date,
)

WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTH_LABELS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _flagged_frame(checked: pd.DataFrame | None) -> pd.DataFrame:
    if checked is None or checked.empty or "flag_count" not in checked.columns:
        return pd.DataFrame(columns=list(checked.columns) if isinstance(checked, pd.DataFrame) else [])
    return checked[checked["flag_count"] > 0].copy()


def available_years(checked: pd.DataFrame | None) -> list[int]:
    """Return the years present in a checked ledger."""
    if checked is None or checked.empty or "Date" not in checked.columns:
        return [pd.Timestamp.today().year]
    dates = pd.to_datetime(checked["Date"], errors="coerce").dropna()
    if dates.empty:
        return [pd.Timestamp.today().year]
    return sorted({int(year) for year in dates.dt.year.unique()})


def financial_year_options(checked: pd.DataFrame | None, mode: str) -> list[int]:
    """Return every financial-year start year touched by the ledger."""
    if checked is None or checked.empty or "Date" not in checked.columns:
        return [financial_year_start(pd.Timestamp.today(), mode)]
    dates = pd.to_datetime(checked["Date"], errors="coerce").dropna()
    if dates.empty:
        return [financial_year_start(pd.Timestamp.today(), mode)]
    return sorted({financial_year_start(date, mode) for date in dates})


def default_financial_year(checked: pd.DataFrame | None, mode: str) -> int:
    """Pick the financial year containing the latest ledger date."""
    if checked is None or checked.empty or "Date" not in checked.columns:
        return financial_year_start(pd.Timestamp.today(), mode)
    dates = pd.to_datetime(checked["Date"], errors="coerce").dropna()
    if dates.empty:
        return financial_year_start(pd.Timestamp.today(), mode)
    return financial_year_start(dates.max(), mode)


def month_options(
    checked: pd.DataFrame | None,
    mode: str,
    start_year: int,
) -> list[tuple[int, int]]:
    """Return (year, month) pairs inside a financial year that overlap the data."""
    months = financial_year_months(start_year, mode)
    if checked is None or checked.empty or "Date" not in checked.columns:
        return months
    dates = pd.to_datetime(checked["Date"], errors="coerce").dropna()
    if dates.empty:
        return months
    first, last = dates.min(), dates.max()
    overlapping = [
        (year, month)
        for year, month in months
        if (pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)) >= first
        and pd.Timestamp(year, month, 1) <= last
    ]
    return overlapping or months


def month_label(year: int, month: int) -> str:
    """Return a readable month label."""
    return f"{MONTH_LABELS[month - 1]} {year}"


def holiday_name_map(holidays: object) -> dict[pd.Timestamp, str]:
    """Normalize holidays from a mapping or iterable into normalized timestamps."""
    result: dict[pd.Timestamp, str] = {}
    if holidays is None:
        return result
    if isinstance(holidays, Mapping):
        items = holidays.items()
    else:
        items = [(value, "Public holiday") for value in holidays]
    for value, name in items:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError):
            continue
        if pd.isna(timestamp):
            continue
        if not isinstance(name, str) or not name:
            name = "Public holiday"
        result[timestamp.normalize()] = name
    return result


def build_month_cells(
    checked: pd.DataFrame | None,
    year: int,
    month: int,
    holidays: Mapping[pd.Timestamp, str] | None = None,
    weekend_days: Iterable[int] = DEFAULT_WEEKEND_DAYS,
) -> list[dict[str, object]]:
    """Return one record per day of the month with flags, risk, and status."""
    holidays = holidays or {}
    weekend = tuple(int(day) for day in weekend_days)
    flagged = _flagged_frame(checked)

    counts = pd.Series(dtype="int64")
    risks = pd.Series(dtype="float")
    entries = pd.Series(dtype="int64")
    criticals = pd.Series(dtype="int64")
    if not flagged.empty:
        dates = pd.to_datetime(flagged["Date"], errors="coerce").dt.normalize()
        frame = pd.DataFrame(
            {
                "date": dates,
                "risk": pd.to_numeric(flagged.get("risk_score", 0), errors="coerce").fillna(0),
                "critical": (flagged.get("risk_level", pd.Series(index=flagged.index)) == "Critical").astype(int),
            }
        ).dropna(subset=["date"])
        counts = frame.groupby("date").size()
        risks = frame.groupby("date")["risk"].sum()
        criticals = frame.groupby("date")["critical"].sum()
    if checked is not None and not checked.empty and "Date" in checked.columns:
        all_dates = pd.to_datetime(checked["Date"], errors="coerce").dt.normalize().dropna()
        entries = all_dates.groupby(all_dates).size()

    first = pd.Timestamp(year, month, 1)
    offset = int(first.dayofweek)
    days_in_month = monthrange(year, month)[1]
    cells: list[dict[str, object]] = []
    for day in range(1, days_in_month + 1):
        date = pd.Timestamp(year, month, day)
        position = offset + day - 1
        cells.append(
            {
                "date": date,
                "day": day,
                "week": position // 7,
                "weekday": position % 7,
                "flagged": int(counts.get(date, 0)),
                "critical": int(criticals.get(date, 0)),
                "risk": float(risks.get(date, 0.0)),
                "entries": int(entries.get(date, 0)),
                "is_weekend": int(date.dayofweek) in weekend,
                "holiday": holidays.get(date),
            }
        )
    return cells


def _grid(cells: list[dict[str, object]], key: str, empty: object = None) -> list[list[object]]:
    grid: list[list[object]] = [[empty for _ in range(7)] for _ in range(6)]
    for cell in cells:
        grid[int(cell["week"])][int(cell["weekday"])] = cell[key]
    return grid


def month_heatmap(
    cells: list[dict[str, object]],
    title: str,
    weekend_days: Iterable[int] = DEFAULT_WEEKEND_DAYS,
) -> go.Figure:
    """Build a calendar-grid heatmap with weekend shading and holiday markers."""
    weekend = tuple(int(day) for day in weekend_days)
    flagged_grid = _grid(cells, "flagged", None)
    text_grid = _grid(cells, "day", "")
    hover = _grid(cells, "date", None)
    critical_grid = _grid(cells, "critical", 0)
    maximum = max([int(cell["flagged"]) for cell in cells] or [0])

    customdata = []
    for row_index in range(6):
        row = []
        for column_index in range(7):
            cell = next(
                (
                    item
                    for item in cells
                    if item["week"] == row_index and item["weekday"] == column_index
                ),
                None,
            )
            if cell is None:
                row.append(["", 0, 0, "", ""])
            else:
                row.append(
                    [
                        format_date(cell["date"]),
                        cell["flagged"],
                        cell["risk"],
                        cell["holiday"] or ("Weekend" if cell["is_weekend"] else ""),
                        cell["entries"],
                    ]
                )
        customdata.append(row)

    figure = go.Figure(
        go.Heatmap(
            z=flagged_grid,
            x=list(WEEKDAY_LABELS),
            y=[f"Week {index + 1}" for index in range(6)],
            text=text_grid,
            texttemplate="%{text}",
            textfont=dict(size=12, color="#f1f0ff"),
            customdata=customdata,
            colorscale=[
                [0.0, "rgba(52,211,153,0.10)"],
                [0.01, "rgba(34,211,238,0.38)"],
                [0.45, "rgba(251,191,36,0.65)"],
                [1.0, "rgba(248,113,113,0.90)"],
            ],
            zmin=0,
            zmax=max(1, maximum),
            showscale=False,
            xgap=3,
            ygap=3,
            hovertemplate=(
                "%{customdata[0]}<br>Flagged: %{customdata[1]} "
                "of %{customdata[4]} entries<br>Total risk: %{customdata[2]:.0f}"
                "<br>%{customdata[3]}<extra></extra>"
            ),
        )
    )

    for column in weekend:
        figure.add_shape(
            type="rect",
            x0=column - 0.5,
            x1=column + 0.5,
            y0=-0.5,
            y1=5.5,
            fillcolor="rgba(255,255,255,0.045)",
            line=dict(width=0),
            layer="below",
        )

    for row_index in range(6):
        for column_index in range(7):
            if int(critical_grid[row_index][column_index] or 0) > 0:
                figure.add_shape(
                    type="rect",
                    x0=column_index - 0.5,
                    x1=column_index + 0.5,
                    y0=row_index - 0.5,
                    y1=row_index + 0.5,
                    line=dict(color="#f87171", width=2.5),
                    fillcolor="rgba(0,0,0,0)",
                )

    holiday_cells = [cell for cell in cells if cell["holiday"]]
    if holiday_cells:
        figure.add_trace(
            go.Scatter(
                x=[WEEKDAY_LABELS[int(cell["weekday"])] for cell in holiday_cells],
                y=[f"Week {int(cell['week']) + 1}" for cell in holiday_cells],
                mode="markers",
                marker=dict(
                    symbol="star",
                    size=11,
                    color="#a78bfa",
                    line=dict(color="rgba(255,255,255,0.6)", width=1),
                ),
                text=[str(cell["holiday"]) for cell in holiday_cells],
                hovertemplate="%{text}<extra></extra>",
                showlegend=False,
            )
        )

    figure.update_layout(
        title=title,
        xaxis=dict(side="top", showgrid=False),
        yaxis=dict(autorange="reversed", showgrid=False),
        height=360,
        margin=dict(l=10, r=10, t=64, b=10),
    )
    return figure


def year_heatmap(
    checked: pd.DataFrame | None,
    year: int,
    title: str = "Flagged entries by day",
) -> go.Figure:
    """Build a GitHub-style contribution heatmap for one year."""
    flagged = _flagged_frame(checked)
    counts: dict[pd.Timestamp, int] = {}
    if not flagged.empty:
        dates = pd.to_datetime(flagged["Date"], errors="coerce").dt.normalize().dropna()
        dates = dates[dates.dt.year == year]
        counts = {date: int(count) for date, count in dates.groupby(dates).size().items()}

    start = pd.Timestamp(year, 1, 1)
    end = pd.Timestamp(year, 12, 31)
    weeks = int(((end - start).days + start.dayofweek) // 7) + 1
    z: list[list[object]] = [[None for _ in range(weeks)] for _ in range(7)]
    custom: list[list[list[object]]] = [[[] for _ in range(weeks)] for _ in range(7)]

    day = start
    while day <= end:
        week = int(((day - start).days + start.dayofweek) // 7)
        weekday = int(day.dayofweek)
        z[weekday][week] = counts.get(day, 0)
        custom[weekday][week] = [format_date(day), counts.get(day, 0)]
        day += pd.Timedelta(1, unit="D")

    maximum = max(counts.values(), default=0)
    figure = go.Figure(
        go.Heatmap(
            z=z,
            x=list(range(weeks)),
            y=list(WEEKDAY_LABELS),
            customdata=custom,
            colorscale=[
                [0.0, "rgba(255,255,255,0.04)"],
                [0.01, "rgba(34,211,238,0.35)"],
                [0.5, "rgba(251,191,36,0.65)"],
                [1.0, "rgba(248,113,113,0.90)"],
            ],
            zmin=0,
            zmax=max(1, maximum),
            showscale=False,
            xgap=2,
            ygap=2,
            hovertemplate="%{customdata[0]}: %{customdata[1]} flagged<extra></extra>",
        )
    )
    figure.update_layout(
        title=title,
        xaxis=dict(showgrid=False, showticklabels=False, title=""),
        yaxis=dict(showgrid=False, autorange="reversed", title=""),
        height=230,
        margin=dict(l=10, r=10, t=48, b=10),
    )
    return figure


def _last_working_days(
    year: int,
    month: int,
    holidays: set[pd.Timestamp],
    weekend_days: Iterable[int],
    count: int = 3,
) -> list[pd.Timestamp]:
    weekend = set(int(day) for day in weekend_days)
    day = pd.Timestamp(year, month, monthrange(year, month)[1])
    working: list[pd.Timestamp] = []
    while len(working) < count and day.month == month:
        if day.dayofweek not in weekend and day not in holidays:
            working.append(day)
        day -= pd.Timedelta(1, unit="D")
    return working


def calendar_insights(
    checked: pd.DataFrame | None,
    holidays: Mapping[pd.Timestamp, str] | None = None,
    weekend_days: Iterable[int] = DEFAULT_WEEKEND_DAYS,
) -> dict[str, object]:
    """Summarize weekend/holiday postings, busy days, month-end, and top month."""
    flagged = _flagged_frame(checked)
    holidays = holidays or {}
    empty = {
        "weekend_holiday_count": 0,
        "busiest_day": None,
        "busiest_count": 0,
        "month_end_count": 0,
        "month_rest_count": 0,
        "month_end_share": 0.0,
        "top_month": None,
        "top_month_risk": 0.0,
        "total_flagged": 0,
    }
    if flagged.empty:
        return empty

    weekend_holiday_count = int(flagged["flag_weekend"].sum()) if "flag_weekend" in flagged else 0

    dates = pd.to_datetime(flagged["Date"], errors="coerce").dt.normalize()
    valid = flagged.loc[dates.notna()].copy()
    valid["date"] = dates[dates.notna()]
    if valid.empty:
        return empty

    day_counts = valid.groupby("date").size().sort_values(ascending=False)
    busiest_day = pd.Timestamp(day_counts.index[0])
    busiest_count = int(day_counts.iloc[0])

    holiday_set = {pd.Timestamp(value).normalize() for value in holidays}
    last_working: set[pd.Timestamp] = set()
    for year, month in {(int(date.year), int(date.month)) for date in valid["date"]}:
        last_working.update(
            _last_working_days(year, month, holiday_set, weekend_days, count=3)
        )
    in_month_end = valid["date"].isin(last_working)
    month_end_count = int(in_month_end.sum())
    month_rest_count = int((~in_month_end).sum())
    total = month_end_count + month_rest_count
    month_end_share = month_end_count / total if total else 0.0

    valid["month"] = valid["date"].dt.to_period("M")
    risk = pd.to_numeric(valid.get("risk_score", 0), errors="coerce").fillna(0)
    month_risk = risk.groupby(valid["month"]).sum().sort_values(ascending=False)
    top_month = pd.Timestamp(month_risk.index[0].to_timestamp()) if len(month_risk) else None

    return {
        "weekend_holiday_count": weekend_holiday_count,
        "busiest_day": busiest_day,
        "busiest_count": busiest_count,
        "month_end_count": month_end_count,
        "month_rest_count": month_rest_count,
        "month_end_share": month_end_share,
        "top_month": top_month,
        "top_month_risk": float(month_risk.iloc[0]) if len(month_risk) else 0.0,
        "total_flagged": int(len(valid)),
    }


def day_entries(checked: pd.DataFrame | None, date: object) -> pd.DataFrame:
    """Return the entries posted on one date, highest risk first."""
    if checked is None or checked.empty or "Date" not in checked.columns:
        return pd.DataFrame()
    target = pd.Timestamp(date).normalize()
    dates = pd.to_datetime(checked["Date"], errors="coerce").dt.normalize()
    subset = checked.loc[dates == target].copy()
    if "risk_score" in subset.columns:
        subset = subset.sort_values("risk_score", ascending=False, kind="stable")
    return subset


def financial_year_title(start_year: int, mode: str) -> str:
    """Return a readable financial-year title for the sidebar caption."""
    return financial_year_label(start_year, mode)
