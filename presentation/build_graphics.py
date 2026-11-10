"""
Presentation graphics for the Raleigh 311 equity story.

Generates:
  - request_breakdown illustration (SVG + PNG)
  - map_median_income (ZIP choropleth, dark green = wealthy)
  - map_*_wait (ZIP choropleths for high-disparity service categories)
  - service_disparity (grouped bar chart by wealth segment)
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.colors import Normalize
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon as MplPolygon
import numpy as np
import pandas as pd
import seaborn as sns

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_pipeline import load_income, merge_datasets, wealth_segments  # noqa: E402
from main import _resolve_requests_path  # noqa: E402
from viz_theme import (  # noqa: E402
    PALETTE,
    TYPE,
    add_caption,
    apply_chart_style,
    days_formatter,
    income_colormap,
    resolve_font_family,
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

HOURS_PER_DAY = 24.0
MIN_TASK_REQUESTS = 40
MIN_ZIPS_WITH_DATA = 5

TREE_SERVICE_LABEL = "Tree Service"


@dataclass(frozen=True)
class ServiceMapTask:
    """A service or request type to render as a ZIP-level wait-time choropleth."""

    slug: str
    filter_column: str
    filter_value: str
    display_label: str


# Categories where lower-income ZIPs wait longer and geographic patterns are visible.
SERVICE_WAIT_MAPS: tuple[ServiceMapTask, ...] = (
    ServiceMapTask("tree_service", "service", "Tree Service", "Tree Service"),
    ServiceMapTask(
        "transportation_improvement",
        "service",
        "Transportation Improvement Request",
        "Transportation Improvement",
    ),
    ServiceMapTask("bus_stop", "service", "Bus Stop Service", "Bus Stop Service"),
    ServiceMapTask("sidewalk_issues", "service", "Sidewalk Issues", "Sidewalk Issues"),
    ServiceMapTask(
        "debris_blocking_sidewalk",
        "request_type",
        "Debris blocking sidewalk",
        "Debris Blocking Sidewalk",
    ),
)


def _normalize_zip(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(5)
    )


def load_requests_with_service(path: Path) -> pd.DataFrame:
    """Load requests with service, request type, and resolution time."""
    df = pd.read_csv(path)
    required = ["ZIP Code", "Hours to Resolve", "Service", "Request Type"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Requests CSV missing columns: {missing}")

    out = df.copy()
    out["zip_code"] = _normalize_zip(out["ZIP Code"])
    out["days_to_resolve"] = pd.to_numeric(out["Hours to Resolve"], errors="coerce") / HOURS_PER_DAY
    out["service"] = out["Service"].astype("string").str.strip()
    out["request_type"] = out["Request Type"].astype("string").str.strip()
    return out.dropna(subset=["zip_code", "days_to_resolve"]).reset_index(drop=True)


def _filter_task_requests(requests: pd.DataFrame, task: ServiceMapTask) -> pd.DataFrame:
    """Return request rows matching a map task filter."""
    if task.filter_column == "service":
        mask = requests["service"] == task.filter_value
    elif task.filter_column == "request_type":
        mask = requests["request_type"] == task.filter_value
    else:
        raise ValueError(f"Unsupported filter column: {task.filter_column}")

    return requests.loc[mask].copy()


def build_task_wait_metrics(
    requests: pd.DataFrame,
    income: pd.DataFrame,
    task: ServiceMapTask,
) -> pd.DataFrame:
    """Average wait time per ZIP for a single service or request type."""
    subset = _filter_task_requests(requests, task)
    if subset.empty:
        raise ValueError(f"No '{task.filter_value}' requests found for {task.display_label}.")

    grouped = (
        subset.groupby("zip_code", as_index=False)
        .agg(
            avg_days=("days_to_resolve", "mean"),
            median_days=("days_to_resolve", "median"),
            request_count=("days_to_resolve", "size"),
        )
    )
    return income.merge(grouped, on="zip_code", how="left")


def build_tree_service_metrics(requests: pd.DataFrame, income: pd.DataFrame) -> pd.DataFrame:
    """Average Tree Service wait time per ZIP, scoped to income ZIPs."""
    return build_task_wait_metrics(
        requests,
        income,
        ServiceMapTask("tree_service", "service", TREE_SERVICE_LABEL, "Tree Service"),
    )


def rank_disparity_tasks(
    requests: pd.DataFrame,
    income: pd.DataFrame,
    top_n: int = 3,
) -> list[ServiceMapTask]:
    """
    Rank services/request types where low-income ZIPs wait longest.

    Returns map tasks for the top ``top_n`` categories with enough data.
    """
    requests = requests.loc[requests["zip_code"].isin(income["zip_code"])].copy()
    merged = requests.merge(income, on="zip_code", how="inner")
    wealthy_zips, low_income_zips = wealth_segments(merged)

    candidates: list[tuple[float, int, ServiceMapTask]] = []

    for column, values in (
        ("service", requests["service"].dropna().unique()),
        ("request_type", requests["request_type"].dropna().unique()),
    ):
        for value in values:
            if pd.isna(value) or str(value).strip().lower() == "nan":
                continue

            value = str(value).strip()
            subset = requests.loc[requests[column] == value]
            if len(subset) < MIN_TASK_REQUESTS:
                continue

            zip_medians = subset.groupby("zip_code")["days_to_resolve"].median()
            if len(zip_medians) < MIN_ZIPS_WITH_DATA:
                continue

            wealthy_med = subset.loc[
                subset["zip_code"].isin(wealthy_zips), "days_to_resolve"
            ].median()
            low_med = subset.loc[
                subset["zip_code"].isin(low_income_zips), "days_to_resolve"
            ].median()
            if pd.isna(wealthy_med) or pd.isna(low_med):
                continue

            gap = float(low_med - wealthy_med)
            if gap <= 0:
                continue

            slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
            display = value if column == "service" else value.title()
            task = ServiceMapTask(slug, column, value, display)
            candidates.append((gap, len(subset), task))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

    seen_slugs: set[str] = set()
    ranked: list[ServiceMapTask] = []
    for _, _, task in candidates:
        if task.slug in seen_slugs:
            continue
        seen_slugs.add(task.slug)
        ranked.append(task)
        if len(ranked) >= top_n:
            break

    return ranked


def _draw_bucket(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolor: str,
    label: str,
    subtitle: str | None = None,
) -> None:
    """Draw a flat vector-style bucket (rounded rectangle + base lip)."""
    body = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        facecolor=facecolor,
        edgecolor=PALETTE["ink"],
        linewidth=2.0,
        mutation_aspect=1.2,
    )
    ax.add_patch(body)

    lip = FancyBboxPatch(
        (x - width * 0.04, y + height),
        width * 1.08,
        height * 0.08,
        boxstyle="round,pad=0.01,rounding_size=0.04",
        facecolor=facecolor,
        edgecolor=PALETTE["ink"],
        linewidth=2.0,
    )
    ax.add_patch(lip)

    ax.text(
        x + width / 2,
        y + height / 2 + (0.04 if subtitle else 0),
        label,
        ha="center",
        va="center",
        fontsize=TYPE["panel_title_size"] if len(label) < 20 else TYPE["label_size"],
        fontweight=TYPE["title_weight"],
        color=PALETTE["ink"],
    )
    if subtitle:
        ax.text(
            x + width / 2,
            y + height / 2 - 0.22,
            subtitle,
            ha="center",
            va="center",
            fontsize=TYPE["caption_size"],
            fontweight=TYPE["body_weight"],
            color=PALETTE["muted"],
        )


def build_request_breakdown_illustration(output_dir: Path) -> tuple[Path, Path]:
    """
    Vector-style funnel: one aggregate bucket splitting into three task types.

    Explains why broad aggregation hides real patterns without statistical jargon.
    """
    apply_chart_style()
    fig, ax = plt.subplots(figsize=(11, 7))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7)
    ax.axis("off")

    # Main bucket
    _draw_bucket(
        ax, x=2.8, y=4.35, width=4.4, height=1.85,
        facecolor=PALETTE["fill_subtle"],
        label="All 311 Requests",
        subtitle="Mixed tasks, mixed wait times",
    )

    # Split arrows
    arrow_style = dict(
        arrowstyle="-|>",
        color=PALETTE["muted"],
        lw=2.2,
        mutation_scale=14,
        shrinkA=4,
        shrinkB=4,
    )
    splits = [
        (3.0, 4.35, 1.6, 2.55),
        (5.0, 4.35, 5.0, 2.55),
        (7.0, 4.35, 8.4, 2.55),
    ]
    for x0, y0, x1, y1 in splits:
        ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), **arrow_style))

    # Child buckets
    child_specs = [
        (0.55, 0.85, 2.1, 1.55, "#E8F0F8", "Potholes", "Fast, uniform"),
        (3.95, 0.85, 2.1, 1.55, "#D4EDE6", "Parks", "Mixed workload"),
        (7.35, 0.85, 2.1, 1.55, "#FCE8E6", "Trees", "Highly variable"),
    ]
    for x, y, w, h, color, label, sub in child_specs:
        _draw_bucket(ax, x, y, w, h, facecolor=color, label=label, subtitle=sub)

    ax.text(
        5.0,
        6.55,
        "Why We Break the Data Apart",
        ha="center",
        fontsize=TYPE["title_size"],
        fontweight=TYPE["title_weight"],
        color=PALETTE["ink"],
    )
    ax.text(
        5.0,
        0.25,
        "One average hides three very different citizen experiences",
        ha="center",
        fontsize=TYPE["caption_size"],
        fontweight=TYPE["body_weight"],
        color=PALETTE["muted"],
    )

    png_path = output_dir / "request_breakdown.png"
    save_figure(fig, png_path)

    svg_path = output_dir / "request_breakdown.svg"
    _write_breakdown_svg(svg_path)
    return svg_path, png_path


def _write_breakdown_svg(path: Path) -> None:
    """Write a true vector SVG matching the bucket illustration layout."""
    font = resolve_font_family()
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="700" viewBox="0 0 1100 700">
  <rect width="1100" height="700" fill="none"/>
  <text x="550" y="58" text-anchor="middle" font-family="{font}, sans-serif"
        font-size="22" font-weight="600" fill="{PALETTE['ink']}">Why We Break the Data Apart</text>

  <!-- Main bucket -->
  <rect x="280" y="145" width="440" height="185" rx="18" fill="{PALETTE['fill_subtle']}" stroke="{PALETTE['ink']}" stroke-width="2.5"/>
  <rect x="262" y="125" width="476" height="28" rx="10" fill="{PALETTE['fill_subtle']}" stroke="{PALETTE['ink']}" stroke-width="2.5"/>
  <text x="500" y="225" text-anchor="middle" font-family="{font}, sans-serif" font-size="18" font-weight="600" fill="{PALETTE['ink']}">All 311 Requests</text>
  <text x="500" y="252" text-anchor="middle" font-family="{font}, sans-serif" font-size="13" font-weight="400" fill="{PALETTE['muted']}">Mixed tasks, mixed wait times</text>

  <!-- Arrows -->
  <line x1="330" y1="330" x2="190" y2="410" stroke="{PALETTE['muted']}" stroke-width="2.5" marker-end="url(#arrow)"/>
  <line x1="500" y1="330" x2="500" y2="410" stroke="{PALETTE['muted']}" stroke-width="2.5" marker-end="url(#arrow)"/>
  <line x1="670" y1="330" x2="810" y2="410" stroke="{PALETTE['muted']}" stroke-width="2.5" marker-end="url(#arrow)"/>
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">
      <path d="M0,0 L8,3 L0,6 Z" fill="{PALETTE['muted']}"/>
    </marker>
  </defs>

  <!-- Child buckets -->
  <g>
    <rect x="75" y="430" width="210" height="155" rx="14" fill="#E8F0F8" stroke="{PALETTE['ink']}" stroke-width="2.5"/>
    <rect x="62" y="412" width="236" height="24" rx="8" fill="#E8F0F8" stroke="{PALETTE['ink']}" stroke-width="2.5"/>
    <text x="180" y="495" text-anchor="middle" font-family="{font}, sans-serif" font-size="17" font-weight="600" fill="{PALETTE['ink']}">Potholes</text>
    <text x="180" y="520" text-anchor="middle" font-family="{font}, sans-serif" font-size="12" font-weight="400" fill="{PALETTE['muted']}">Fast, uniform</text>
  </g>
  <g>
    <rect x="395" y="430" width="210" height="155" rx="14" fill="#D4EDE6" stroke="{PALETTE['ink']}" stroke-width="2.5"/>
    <rect x="382" y="412" width="236" height="24" rx="8" fill="#D4EDE6" stroke="{PALETTE['ink']}" stroke-width="2.5"/>
    <text x="500" y="495" text-anchor="middle" font-family="{font}, sans-serif" font-size="17" font-weight="600" fill="{PALETTE['ink']}">Parks</text>
    <text x="500" y="520" text-anchor="middle" font-family="{font}, sans-serif" font-size="12" font-weight="400" fill="{PALETTE['muted']}">Mixed workload</text>
  </g>
  <g>
    <rect x="715" y="430" width="210" height="155" rx="14" fill="#FCE8E6" stroke="{PALETTE['ink']}" stroke-width="2.5"/>
    <rect x="702" y="412" width="236" height="24" rx="8" fill="#FCE8E6" stroke="{PALETTE['ink']}" stroke-width="2.5"/>
    <text x="820" y="495" text-anchor="middle" font-family="{font}, sans-serif" font-size="17" font-weight="600" fill="{PALETTE['ink']}">Trees</text>
    <text x="820" y="520" text-anchor="middle" font-family="{font}, sans-serif" font-size="12" font-weight="400" fill="{PALETTE['muted']}">Highly variable</text>
  </g>

  <text x="550" y="665" text-anchor="middle" font-family="{font}, sans-serif" font-size="12" font-weight="400" fill="{PALETTE['muted']}">One average hides three very different citizen experiences</text>
</svg>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def render_zip_choropleth(
    geojson: dict,
    metrics: pd.DataFrame,
    value_col: str,
    cmap,
    title: str,
    colorbar_label: str,
    output_path: Path,
    label_format: str = "{zip}\n{value:.0f}",
    missing_fill: str | None = None,
) -> Path:
    """Render a single-variable ZIP choropleth PNG on a transparent canvas."""
    missing_fill = missing_fill or PALETTE["fill_subtle"]
    metric_lookup = metrics.set_index("zip_code").to_dict("index")

    values = metrics[value_col].dropna()
    if values.empty:
        raise ValueError(f"No values available for column '{value_col}'.")

    vmin = float(values.min())
    vmax = float(values.max())
    if vmin == vmax:
        vmax = vmin + 1.0

    norm = Normalize(vmin=vmin, vmax=vmax)

    patches: list[MplPolygon] = []
    face_colors: list = []
    label_points: list[tuple[float, float, str, float | None]] = []

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
            label_points.append((float(np.mean(xs)), float(np.mean(ys)), zcta, raw_value if has_value else None))

    apply_chart_style()
    fig, ax = plt.subplots(figsize=(12, 10))

    ax.add_collection(
        PatchCollection(
            patches,
            facecolor=face_colors,
            edgecolor=PALETTE["border"],
            linewidths=1.6,
            alpha=0.9,
        )
    )

    for lon, lat, zcta, value in label_points:
        if value is None:
            continue
        label = label_format.format(zip=zcta, value=value)
        ax.text(
            lon,
            lat,
            label,
            ha="center",
            va="center",
            fontsize=TYPE["annotation_size"],
            fontweight=TYPE["title_weight"],
            color=PALETTE["ink"],
            bbox=dict(
                boxstyle="round,pad=0.22",
                facecolor=PALETTE["fill_subtle"],
                edgecolor="none",
                alpha=0.88,
            ),
        )

    ax.autoscale()
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    ax.set_title(
        title,
        fontsize=TYPE["title_size"],
        fontweight=TYPE["title_weight"],
        color=PALETTE["ink"],
        pad=16,
    )

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label(
        colorbar_label,
        color=PALETTE["muted"],
        fontsize=TYPE["legend_size"],
        fontweight=TYPE["body_weight"],
    )
    cbar.ax.yaxis.set_tick_params(color=PALETTE["muted"])
    plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color=PALETTE["muted"])

    return save_figure(fig, output_path)


def build_income_map(
    income: pd.DataFrame,
    geojson: dict,
    output_path: Path,
) -> Path:
    """Raleigh ZIP map colored by median household income (dark green = wealthy)."""
    return render_zip_choropleth(
        geojson=geojson,
        metrics=income,
        value_col="median_income",
        cmap=income_colormap(),
        title="Raleigh Median Household Income by ZIP",
        colorbar_label="Median Income ($)",
        output_path=output_path,
        label_format="{zip}\n${value:,.0f}",
    )


def build_service_wait_map(
    task_metrics: pd.DataFrame,
    geojson: dict,
    task: ServiceMapTask,
    output_path: Path,
) -> Path:
    """Raleigh ZIP map colored by average wait for a single service category."""
    return render_zip_choropleth(
        geojson=geojson,
        metrics=task_metrics,
        value_col="avg_days",
        cmap=wait_time_colormap(),
        title=f'Raleigh "{task.display_label}" Response Time by ZIP',
        colorbar_label="Average Days to Resolve",
        output_path=output_path,
        label_format="{zip}\n{value:.0f}d",
    )


def build_tree_service_map(
    tree_metrics: pd.DataFrame,
    geojson: dict,
    output_path: Path,
) -> Path:
    """Raleigh ZIP map colored by Tree Service average wait (dark red = slow)."""
    return build_service_wait_map(
        tree_metrics,
        geojson,
        ServiceMapTask("tree_service", "service", TREE_SERVICE_LABEL, "Tree Service"),
        output_path,
    )


def build_service_wait_maps(
    requests: pd.DataFrame,
    income: pd.DataFrame,
    geojson: dict,
    output_dir: Path,
    tasks: tuple[ServiceMapTask, ...] | None = None,
) -> list[tuple[ServiceMapTask, Path, int]]:
    """Generate wait-time choropleths for each disparity service category."""
    tasks = tasks or SERVICE_WAIT_MAPS
    results: list[tuple[ServiceMapTask, Path, int]] = []

    for task in tasks:
        metrics = build_task_wait_metrics(requests, income, task)
        zips_with_data = int(metrics["avg_days"].notna().sum())
        if zips_with_data == 0:
            logger.warning("Skipping %s map — no ZIP-level data.", task.display_label)
            continue

        output_path = output_dir / f"map_{task.slug}_wait.png"
        map_path = build_service_wait_map(metrics, geojson, task, output_path)
        results.append((task, map_path, zips_with_data))

    if not results:
        raise ValueError("No service wait maps could be generated.")

    return results


def _format_zip_list(zip_codes: set[str] | Iterable[str]) -> str:
    return ", ".join(sorted(str(z) for z in zip_codes))


def _compute_task_segment_averages(
    requests: pd.DataFrame,
    task: ServiceMapTask,
    wealthy_zips: set[str],
    low_income_zips: set[str],
) -> tuple[float | None, float | None]:
    """Mean wait time in each wealth segment for a single service task."""
    subset = _filter_task_requests(requests, task)
    wealthy_avg = subset.loc[
        subset["zip_code"].isin(wealthy_zips), "days_to_resolve"
    ].mean()
    low_avg = subset.loc[
        subset["zip_code"].isin(low_income_zips), "days_to_resolve"
    ].mean()
    wealthy_val = float(wealthy_avg) if pd.notna(wealthy_avg) else None
    low_val = float(low_avg) if pd.notna(low_avg) else None
    return wealthy_val, low_val


def plot_service_disparity_bars(
    requests: pd.DataFrame,
    wealthy_zips: set[str],
    low_income_zips: set[str],
    output_path: Path,
    tasks: tuple[ServiceMapTask, ...] | None = None,
) -> Path:
    """
    Grouped horizontal bar chart of service wait-time disparities by wealth segment.

    Compares average resolution time in the top 20% wealthiest ZIP codes versus the
    bottom 20% lowest-income ZIP codes for high-disparity service categories.
    """
    if not wealthy_zips or not low_income_zips:
        raise ValueError("Wealth segments must contain at least one ZIP code each.")

    tasks = tasks or SERVICE_WAIT_MAPS
    records: list[dict[str, object]] = []

    for task in tasks:
        wealthy_avg, low_avg = _compute_task_segment_averages(
            requests, task, wealthy_zips, low_income_zips
        )
        if wealthy_avg is not None:
            records.append(
                {
                    "service_category": task.display_label,
                    "segment": "Top 20% Income",
                    "avg_days": wealthy_avg,
                }
            )
        if low_avg is not None:
            records.append(
                {
                    "service_category": task.display_label,
                    "segment": "Bottom 20% Income",
                    "avg_days": low_avg,
                }
            )

    plot_df = pd.DataFrame(records)
    if plot_df.empty:
        raise ValueError("No disparity metrics could be computed for the selected tasks.")

    category_order = (
        plot_df.groupby("service_category")["avg_days"]
        .max()
        .sort_values(ascending=True)
        .index.tolist()
    )

    apply_chart_style()
    fig, ax = plt.subplots(figsize=(10, 6.5))

    sns.barplot(
        data=plot_df,
        y="service_category",
        x="avg_days",
        hue="segment",
        order=category_order,
        hue_order=["Top 20% Income", "Bottom 20% Income"],
        palette={
            "Top 20% Income": PALETTE["wealthy"],
            "Bottom 20% Income": PALETTE["low_income"],
        },
        ax=ax,
        edgecolor=PALETTE["point_edge"],
        linewidth=0.8,
    )

    ax.set_title("Service Response Disparity by Income Segment")
    ax.set_xlabel("Average Days to Resolve")
    ax.set_ylabel("")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(days_formatter))
    trim_spines(ax)

    handles, labels = ax.get_legend_handles_labels()
    if ax.legend_ is not None:
        ax.legend_.remove()
    style_legend(
        ax,
        handles=handles,
        labels=labels,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=2,
    )

    caption = (
        f"Top 20% ZIPs: {_format_zip_list(wealthy_zips)} · "
        f"Bottom 20% ZIPs: {_format_zip_list(low_income_zips)}"
    )
    add_caption(fig, caption, y=0.01)
    fig.subplots_adjust(bottom=0.24)

    return save_figure(fig, output_path)


def main() -> int:
    """Generate all presentation graphics."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        requests_path = _resolve_requests_path(None)
        income_path = PROJECT_ROOT / "raleigh_income.csv"

        income = load_income(income_path)
        requests = load_requests_with_service(requests_path)
        requests = requests.loc[requests["zip_code"].isin(income["zip_code"])].copy()
        requests_with_income = requests.merge(income, on="zip_code", how="inner")
        wealthy_zips, low_income_zips = wealth_segments(requests_with_income)

        nc_geojson = fetch_nc_geojson()
        zip_codes = set(income["zip_code"])
        filtered_geojson = filter_geojson(nc_geojson, zip_codes)

        svg_path, png_path = build_request_breakdown_illustration(OUTPUT_DIR)
        income_map = build_income_map(
            income, filtered_geojson, OUTPUT_DIR / "map_median_income.png"
        )
        service_maps = build_service_wait_maps(
            requests,
            income,
            filtered_geojson,
            OUTPUT_DIR,
        )
        disparity_chart = plot_service_disparity_bars(
            requests,
            wealthy_zips,
            low_income_zips,
            OUTPUT_DIR / "service_disparity.png",
        )

        print("\nPresentation Graphics")
        print(f"  ZIP codes: {len(income)}")
        print("\nService wait choropleths:")
        for task, map_path, zips_with_data in service_maps:
            print(f"  {task.display_label:32s}  {zips_with_data:2d} ZIPs  {map_path.name}")
        ranked = rank_disparity_tasks(requests, income, top_n=5)
        if ranked:
            print("\nLargest low-income wait gaps in the data:")
            for task in ranked:
                print(f"  {task.display_label}")
        print("\nOutputs:")
        print(f"  Breakdown illustration (SVG): {svg_path}")
        print(f"  Breakdown illustration (PNG): {png_path}")
        print(f"  Income choropleth:            {income_map}")
        print(f"  Service disparity chart:      {disparity_chart}")
        return 0

    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Failed to build presentation graphics.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
