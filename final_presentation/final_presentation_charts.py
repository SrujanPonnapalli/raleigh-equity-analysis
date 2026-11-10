"""
Final presentation charts for Raleigh 311 civic equity story.

Generates three billboard-readable visuals in ``final_presentation/output/``:
  1. service_gap_dumbbell.png   — wealth-segment wait-time gaps by service
  2. pattern_match_maps.png     — side-by-side income vs. service-wait choropleths
  3. tale_of_two_zips.png       — ZIP 27608 vs. 27610 grouped bar comparison
  4. standard_requests_by_tier.png — median wait across income tiers (all requests)

Usage::

    python final_presentation/final_presentation_charts.py
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import PatchCollection
from matplotlib.colors import Normalize
from matplotlib.patches import Polygon as MplPolygon

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_pipeline import (  # noqa: E402
    completed_requests,
    income_tiers,
    load_income,
    load_requests,
    wealth_segments,
)
from main import _resolve_requests_path  # noqa: E402
from viz_theme import (  # noqa: E402
    PALETTE,
    TYPE,
    add_caption,
    apply_chart_style,
    days_formatter,
    income_colormap,
    save_figure,
    style_legend,
    trim_spines,
    wait_time_colormap,
)
from zip_choropleth.build_viz import (  # noqa: E402
    _geometry_rings,
    fetch_nc_geojson,
    filter_geojson,
)

logger = logging.getLogger(__name__)

MODULE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = MODULE_DIR / "output"

WEALTHY_ZIP = "27608"
LOW_INCOME_ZIP = "27610"

DISPARITY_TASKS: tuple[tuple[str, str, str], ...] = (
    ("Street sign", "request_type", "Street sign"),
    ("Tree Service", "service", "Tree Service"),
    ("Sidewalk", "service", "Sidewalk Issues"),
)

TALE_TASKS: tuple[tuple[str, str, str], ...] = (
    ("Tree Service", "service", "Tree Service"),
    ("Street sign", "request_type", "Street sign"),
    ("Public Nuisance", "service", "Public Nuisance"),
)

INCOME_TIER_ORDER: tuple[str, ...] = ("Bottom 20%", "Middle 60%", "Top 20%")
TIER_COLORS: dict[str, str] = {
    "Bottom 20%": PALETTE["low_income"],
    "Middle 60%": "#7FBFB3",
    "Top 20%": PALETTE["wealthy"],
}


@dataclass(frozen=True)
class SegmentMedians:
    label: str
    wealthy_days: float
    low_income_days: float


def load_requests_with_tasks(path: Path) -> pd.DataFrame:
    """Load request records with service, request type, and resolution time."""
    return completed_requests(load_requests(path))


def _filter_task(df: pd.DataFrame, column: str, value: str) -> pd.DataFrame:
    return df.loc[df[column] == value].copy()


def _is_disparity_request(row: pd.Series) -> bool:
    service = row["service"]
    request_type = row["request_type"]
    if pd.notna(service) and service == "Tree Service":
        return True
    if pd.notna(service) and service == "Sidewalk Issues":
        return True
    return pd.notna(request_type) and request_type == "Street sign"


def compute_segment_medians(
    requests: pd.DataFrame,
    wealthy_zips: set[str],
    low_income_zips: set[str],
    tasks: tuple[tuple[str, str, str], ...],
) -> list[SegmentMedians]:
    """Median wait time per wealth segment for each named task."""
    results: list[SegmentMedians] = []
    for label, column, value in tasks:
        subset = _filter_task(requests, column, value)
        wealthy_med = subset.loc[
            subset["zip_code"].isin(wealthy_zips), "days_to_resolve"
        ].median()
        low_med = subset.loc[
            subset["zip_code"].isin(low_income_zips), "days_to_resolve"
        ].median()
        if pd.isna(wealthy_med) or pd.isna(low_med):
            raise ValueError(f"Insufficient data to compute medians for '{label}'.")
        results.append(
            SegmentMedians(
                label=label,
                wealthy_days=float(wealthy_med),
                low_income_days=float(low_med),
            )
        )
    return results


def _format_days(value: float) -> str:
    return f"{round(value)}d"


def plot_service_gap_dumbbell(
    segment_data: list[SegmentMedians],
    output_path: Path,
) -> Path:
    """Dumbbell chart comparing wealthy vs. low-income segment median wait times."""
    apply_chart_style()
    ordered = list(reversed(segment_data))
    labels = [item.label for item in ordered]
    y_pos = np.arange(len(labels))

    fig, ax = plt.subplots(figsize=(10, 5.5))
    wealthy_x = [item.wealthy_days for item in ordered]
    low_x = [item.low_income_days for item in ordered]

    for y, wealthy, low in zip(y_pos, wealthy_x, low_x):
        ax.hlines(y, wealthy, low, color=PALETTE["border"], linewidth=2.5, zorder=1)

    ax.scatter(
        wealthy_x,
        y_pos,
        s=160,
        color=PALETTE["wealthy"],
        edgecolors=PALETTE["point_edge"],
        linewidths=1.4,
        zorder=3,
        label="Top 20% Wealthiest ZIPs",
    )
    ax.scatter(
        low_x,
        y_pos,
        s=160,
        color=PALETTE["low_income"],
        edgecolors=PALETTE["point_edge"],
        linewidths=1.4,
        zorder=3,
        label="Bottom 20% Lowest-Income ZIPs",
    )

    x_pad = 0.8
    for y, wealthy, low in zip(y_pos, wealthy_x, low_x):
        wealthy_label = _format_days(wealthy)
        low_label = _format_days(low)
        wealthy_offset = 0.35 if wealthy >= low else -0.35
        low_offset = 0.35 if low >= wealthy else -0.35
        ax.text(
            wealthy + wealthy_offset,
            y,
            wealthy_label,
            ha="center",
            va="center",
            fontsize=TYPE["label_size"],
            fontweight=TYPE["title_weight"],
            color=PALETTE["wealthy"],
        )
        ax.text(
            low + low_offset,
            y,
            low_label,
            ha="center",
            va="center",
            fontsize=TYPE["label_size"],
            fontweight=TYPE["title_weight"],
            color=PALETTE["low_income"],
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Days to Resolve")
    ax.set_title("The Service Gap: Who Waits Longer?")
    ax.grid(False)
    ax.set_xlim(
        min(wealthy_x + low_x) - x_pad,
        max(wealthy_x + low_x) + x_pad,
    )
    trim_spines(ax)
    style_legend(ax, loc="lower right")

    return save_figure(fig, output_path)


def _build_polygon_layers(
    geojson: dict,
    metric_lookup: dict[str, dict],
    value_col: str,
    cmap,
    vmin: float,
    vmax: float,
    missing_fill: str,
) -> tuple[list[MplPolygon], list, tuple[float, float, float, float]]:
    """Collect matplotlib polygons and colors for a ZIP choropleth layer."""
    norm = Normalize(vmin=vmin, vmax=vmax)
    patches: list[MplPolygon] = []
    face_colors: list = []
    bounds = [np.inf, np.inf, -np.inf, -np.inf]

    for feature in geojson["features"]:
        zcta = str(feature["properties"].get("ZCTA5CE10", "")).zfill(5)
        row = metric_lookup.get(zcta)
        raw_value = row.get(value_col) if row else None
        has_value = raw_value is not None and pd.notna(raw_value)
        color = cmap(norm(float(raw_value))) if has_value else missing_fill

        for ring in _geometry_rings(feature["geometry"]):
            patches.append(MplPolygon(ring, closed=True))
            face_colors.append(color)
            xs = [pt[0] for pt in ring]
            ys = [pt[1] for pt in ring]
            bounds[0] = min(bounds[0], min(xs))
            bounds[1] = min(bounds[1], min(ys))
            bounds[2] = max(bounds[2], max(xs))
            bounds[3] = max(bounds[3], max(ys))

    return patches, face_colors, tuple(bounds)


def _add_choropleth_axis(
    ax: plt.Axes,
    patches: list[MplPolygon],
    face_colors: list,
    bounds: tuple[float, float, float, float],
    title: str,
    cmap,
    vmin: float,
    vmax: float,
    colorbar_label: str,
) -> None:
    """Draw one choropleth panel with a colorbar."""
    ax.add_collection(
        PatchCollection(
            patches,
            facecolor=face_colors,
            edgecolor=PALETTE["border"],
            linewidths=1.4,
            alpha=0.95,
        )
    )
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    ax.set_title(
        title,
        fontsize=TYPE["panel_title_size"],
        fontweight=TYPE["title_weight"],
        color=PALETTE["ink"],
        pad=10,
    )

    norm = Normalize(vmin=vmin, vmax=vmax)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, fraction=0.046, pad=0.02)
    cbar.set_label(
        colorbar_label,
        color=PALETTE["muted"],
        fontsize=TYPE["legend_size"],
        fontweight=TYPE["body_weight"],
    )
    cbar.ax.yaxis.set_tick_params(color=PALETTE["muted"])
    plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color=PALETTE["muted"])


def build_disparity_wait_metrics(requests: pd.DataFrame) -> pd.DataFrame:
    """ZIP-level median wait for Tree Service, Street Sign, and Sidewalk requests."""
    disparity = requests.loc[requests.apply(_is_disparity_request, axis=1)].copy()
    if disparity.empty:
        raise ValueError("No disparity-category requests found for the wait-time map.")

    grouped = (
        disparity.groupby("zip_code", as_index=False)
        .agg(median_days_to_resolve=("days_to_resolve", "median"))
    )
    return grouped


def plot_pattern_match_maps(
    income: pd.DataFrame,
    wait_metrics: pd.DataFrame,
    geojson: dict,
    output_path: Path,
) -> Path:
    """Side-by-side choropleth: neighborhood wealth vs. median service wait."""
    apply_chart_style()
    income_lookup = income.set_index("zip_code").to_dict("index")
    wait_lookup = wait_metrics.set_index("zip_code").to_dict("index")

    income_values = income["median_income"]
    wait_values = wait_metrics["median_days_to_resolve"].dropna()
    income_vmin, income_vmax = float(income_values.min()), float(income_values.max())
    wait_vmin, wait_vmax = float(wait_values.min()), float(wait_values.max())
    if income_vmin == income_vmax:
        income_vmax = income_vmin + 1.0
    if wait_vmin == wait_vmax:
        wait_vmax = wait_vmin + 1.0

    income_cmap = income_colormap()
    wait_cmap = wait_time_colormap()
    missing_fill = PALETTE["fill_subtle"]

    income_patches, income_colors, income_bounds = _build_polygon_layers(
        geojson,
        income_lookup,
        "median_income",
        income_cmap,
        income_vmin,
        income_vmax,
        missing_fill,
    )
    wait_patches, wait_colors, wait_bounds = _build_polygon_layers(
        geojson,
        wait_lookup,
        "median_days_to_resolve",
        wait_cmap,
        wait_vmin,
        wait_vmax,
        missing_fill,
    )
    shared_bounds = (
        min(income_bounds[0], wait_bounds[0]),
        min(income_bounds[1], wait_bounds[1]),
        max(income_bounds[2], wait_bounds[2]),
        max(income_bounds[3], wait_bounds[3]),
    )

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))
    _add_choropleth_axis(
        axes[0],
        income_patches,
        income_colors,
        shared_bounds,
        "Neighborhood Wealth",
        income_cmap,
        income_vmin,
        income_vmax,
        "Median Income ($)",
    )
    _add_choropleth_axis(
        axes[1],
        wait_patches,
        wait_colors,
        shared_bounds,
        "Median Service Wait",
        wait_cmap,
        wait_vmin,
        wait_vmax,
        "Median Days to Resolve",
    )

    fig.suptitle(
        "Pattern Match: Wealth and Wait Times Across Raleigh",
        fontsize=TYPE["title_size"],
        fontweight=TYPE["title_weight"],
        color=PALETTE["ink"],
        y=0.98,
    )
    fig.text(
        0.5,
        0.02,
        "Median days to resolve · Tree Service, Street Sign & Sidewalk requests combined",
        ha="center",
        fontsize=TYPE["caption_size"],
        fontweight=TYPE["body_weight"],
        color=PALETTE["muted"],
    )
    fig.subplots_adjust(left=0.03, right=0.97, top=0.9, bottom=0.1, wspace=0.18)

    return save_figure(fig, output_path)


def plot_tale_of_two_zips(
    requests: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Grouped horizontal bars comparing two ZIP codes across three services."""
    services = [task[0] for task in TALE_TASKS]
    zip_codes = [WEALTHY_ZIP, LOW_INCOME_ZIP]
    zip_labels = [f"ZIP {code}" for code in zip_codes]
    palette = {
        zip_labels[0]: PALETTE["wealthy"],
        zip_labels[1]: PALETTE["low_income"],
    }

    medians: dict[tuple[str, str], float] = {}
    for label, column, value in TALE_TASKS:
        subset = _filter_task(requests, column, value)
        for zip_code in zip_codes:
            zip_subset = subset.loc[subset["zip_code"] == zip_code, "days_to_resolve"]
            if zip_subset.empty:
                raise ValueError(f"No '{label}' requests for ZIP {zip_code}.")
            medians[(label, zip_code)] = float(zip_subset.median())

    apply_chart_style()
    fig, ax = plt.subplots(figsize=(10, 5.5))

    y_pos = np.arange(len(services))
    bar_height = 0.34
    offsets = [bar_height / 2, -bar_height / 2]

    for offset, zip_code, zip_label in zip(offsets, zip_codes, zip_labels):
        values = [medians[(service, zip_code)] for service in services]
        bars = ax.barh(
            y_pos + offset,
            values,
            height=bar_height,
            color=palette[zip_label],
            edgecolor=PALETTE["point_edge"],
            linewidth=0.8,
            label=zip_label,
        )
        for bar, value in zip(bars, values):
            label_x = max(value, 0.15) + 0.25
            ax.text(
                label_x,
                bar.get_y() + bar.get_height() / 2,
                _format_days(value),
                va="center",
                ha="left",
                fontsize=TYPE["label_size"],
                fontweight=TYPE["title_weight"],
                color=palette[zip_label],
            )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(services)
    ax.invert_yaxis()
    ax.set_title(f"A Tale of Two ZIPs: {WEALTHY_ZIP} vs. {LOW_INCOME_ZIP}")
    ax.set_xlabel("Median Days to Resolve")
    ax.grid(False)
    xmax = max(medians.values()) + 2.5
    ax.set_xlim(0, xmax)
    trim_spines(ax)
    style_legend(ax, loc="lower right")

    return save_figure(fig, output_path)


def _format_zip_list(zip_codes: set[str]) -> str:
    return ", ".join(sorted(zip_codes))


def plot_standard_requests_by_tier(
    requests: pd.DataFrame,
    low_income_zips: set[str],
    middle_zips: set[str],
    wealthy_zips: set[str],
    output_path: Path,
) -> Path:
    """
    Vertical bar chart of median wait time across three income tiers.

    Uses all matched 311 requests (the aggregate "standard" request stream).
    """
    tier_zips = {
        "Bottom 20%": low_income_zips,
        "Middle 60%": middle_zips,
        "Top 20%": wealthy_zips,
    }
    if not all(tier_zips.values()):
        raise ValueError("All three income tiers must contain at least one ZIP code.")

    medians: list[float] = []
    for tier in INCOME_TIER_ORDER:
        subset = requests.loc[requests["zip_code"].isin(tier_zips[tier]), "days_to_resolve"]
        if subset.empty:
            raise ValueError(f"No requests found for tier '{tier}'.")
        medians.append(float(subset.median()))

    colors = [TIER_COLORS[tier] for tier in INCOME_TIER_ORDER]

    apply_chart_style()
    fig, ax = plt.subplots(figsize=(10, 6.5))
    x_pos = np.arange(len(INCOME_TIER_ORDER))

    bars = ax.bar(
        x_pos,
        medians,
        color=colors,
        edgecolor=PALETTE["point_edge"],
        linewidth=0.8,
        width=0.62,
    )

    for bar, value in zip(bars, medians):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.12,
            _format_days(value),
            ha="center",
            va="bottom",
            fontsize=TYPE["label_size"],
            fontweight=TYPE["title_weight"],
            color=PALETTE["ink"],
        )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(INCOME_TIER_ORDER)
    ax.set_ylabel("Median Days to Resolve")
    ax.set_xlabel("")
    ax.set_title("For standard requests, wealth doesn't change your wait time.")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(days_formatter))
    ymax = max(medians) * 1.22 + 0.5
    ax.set_ylim(0, ymax)
    ax.grid(axis="y", color=PALETTE["border"], alpha=0.35, linestyle="--")
    ax.grid(axis="x", visible=False)
    trim_spines(ax)

    caption = (
        f"All 311 requests · Bottom 20% ZIPs: {_format_zip_list(low_income_zips)} · "
        f"Middle 60% ZIPs: {_format_zip_list(middle_zips)} · "
        f"Top 20% ZIPs: {_format_zip_list(wealthy_zips)}"
    )
    add_caption(fig, caption, y=0.01)

    return save_figure(fig, output_path)


def main() -> int:
    """Generate all final-presentation chart assets."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        requests_path = _resolve_requests_path(None)
        income_path = PROJECT_ROOT / "raleigh_income.csv"

        income = load_income(income_path)
        requests = load_requests_with_tasks(requests_path)
        requests = requests.loc[requests["zip_code"].isin(income["zip_code"])].copy()

        requests_with_income = requests.merge(income, on="zip_code", how="inner")
        wealthy_zips, low_income_zips = wealth_segments(requests_with_income)
        low_tier_zips, middle_tier_zips, top_tier_zips = income_tiers(requests_with_income)

        segment_data = compute_segment_medians(
            requests, wealthy_zips, low_income_zips, DISPARITY_TASKS
        )
        dumbbell_path = plot_service_gap_dumbbell(
            segment_data,
            OUTPUT_DIR / "service_gap_dumbbell.png",
        )

        wait_metrics = build_disparity_wait_metrics(requests)
        nc_geojson = fetch_nc_geojson()
        filtered_geojson = filter_geojson(nc_geojson, set(income["zip_code"]))
        maps_path = plot_pattern_match_maps(
            income,
            wait_metrics,
            filtered_geojson,
            OUTPUT_DIR / "pattern_match_maps.png",
        )

        bars_path = plot_tale_of_two_zips(
            requests,
            OUTPUT_DIR / "tale_of_two_zips.png",
        )
        tier_bars_path = plot_standard_requests_by_tier(
            requests,
            low_tier_zips,
            middle_tier_zips,
            top_tier_zips,
            OUTPUT_DIR / "standard_requests_by_tier.png",
        )

        print("\nFinal Presentation Charts")
        print(f"  Wealthy segment ZIPs:    {', '.join(sorted(wealthy_zips))}")
        print(f"  Low-income segment ZIPs: {', '.join(sorted(low_income_zips))}")
        print("\nService gap medians (wealthy vs. low-income):")
        for item in segment_data:
            print(
                f"  {item.label:14s}  "
                f"{_format_days(item.wealthy_days):>4s}  vs  {_format_days(item.low_income_days):>4s}"
            )
        print("\nOutputs:")
        print(f"  {dumbbell_path}")
        print(f"  {maps_path}")
        print(f"  {bars_path}")
        print(f"  {tier_bars_path}")
        return 0

    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Failed to build final presentation charts.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
