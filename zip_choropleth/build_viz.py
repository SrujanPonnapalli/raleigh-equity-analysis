"""
Raleigh ZIP choropleth map + paired bar chart.

The Folium map shows *where* response-time inequity clusters geographically.
The bar chart shows *how much* each ZIP deviates in ranked, comparable
magnitudes — something color gradients on a map cannot convey precisely.

Outputs (``output/``):
  - raleigh_zip_choropleth.html   — dark-mode interactive map
  - raleigh_zip_choropleth.png    — static image render of the map
  - zip_service_disparity_bar.png — service wait-time gap by income segment
  - zip_rankings_bar.png          — ranked neglect vs. median wait per ZIP
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.request
from pathlib import Path
from typing import Iterable

import branca.colormap as cm
import folium
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.colors import Normalize
from matplotlib.patches import Polygon as MplPolygon
import numpy as np
import pandas as pd
import seaborn as sns

# Parent project modules (data loading / wealth segmentation)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_pipeline import load_income, wealth_segments  # noqa: E402
from main import _resolve_requests_path  # noqa: E402
from viz_theme import (  # noqa: E402
    PALETTE,
    TYPE,
    add_caption,
    apply_chart_style,
    currency_formatter,
    days_formatter,
    neglect_colormap,
    percent_formatter,
    save_figure,
    style_legend,
    trim_spines,
)

logger = logging.getLogger(__name__)

MODULE_DIR = Path(__file__).resolve().parent
DATA_DIR = MODULE_DIR / "data"
OUTPUT_DIR = MODULE_DIR / "output"

NC_GEOJSON_URL = (
    "https://raw.githubusercontent.com/OpenDataDE/State-zip-code-GeoJSON/"
    "master/nc_north_carolina_zip_codes_geo.min.json"
)
NC_GEOJSON_CACHE = DATA_DIR / "nc_zip_boundaries.min.json"

HOURS_PER_DAY = 24.0
NEGLECT_THRESHOLD_DAYS = 30


SERVICE_DISPARITY_CATEGORIES: tuple[str, ...] = (
    "Housing & Neighborhoods",
    "Customer Experience",
    "Public Nuisance",
    "Transportation & Mobility",
    "Parks & Recreation",
)


def _normalize_zip(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(5)
    )


def load_requests(path: Path) -> pd.DataFrame:
    """Load 311 requests with fields needed for ZIP-level metrics."""
    df = pd.read_csv(path)
    required = ["ZIP Code", "Hours to Resolve", "Service Category"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Requests CSV missing columns: {missing}")

    out = df.copy()
    out["zip_code"] = _normalize_zip(out["ZIP Code"])
    out["days_to_resolve"] = pd.to_numeric(out["Hours to Resolve"], errors="coerce") / HOURS_PER_DAY
    out["service_category"] = out["Service Category"].astype("string").str.strip()
    if "Service" in df.columns:
        out["service"] = df["Service"].astype("string").str.strip()
    if "Request Type" in df.columns:
        out["request_type"] = df["Request Type"].astype("string").str.strip()
    out = out.dropna(subset=["zip_code", "days_to_resolve"])
    return out.reset_index(drop=True)


def build_zip_metrics(requests: pd.DataFrame, income: pd.DataFrame) -> pd.DataFrame:
    """Aggregate equity metrics per ZIP and merge median income."""
    grouped = (
        requests.groupby("zip_code", as_index=False)
        .agg(
            request_volume=("days_to_resolve", "size"),
            median_days=("days_to_resolve", "median"),
            mean_days=("days_to_resolve", "mean"),
            neglect_rate=(
                "days_to_resolve",
                lambda s: 100.0 * (s > NEGLECT_THRESHOLD_DAYS).mean(),
            ),
        )
    )
    metrics = grouped.merge(income, on="zip_code", how="inner")
    if metrics.empty:
        raise ValueError("No ZIP codes overlap between requests and income data.")
    return metrics.sort_values("neglect_rate", ascending=False).reset_index(drop=True)


def fetch_nc_geojson() -> dict:
    """Download (or load cached) North Carolina ZCTA GeoJSON."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if NC_GEOJSON_CACHE.exists():
        logger.info("Loading cached GeoJSON from %s", NC_GEOJSON_CACHE)
        return json.loads(NC_GEOJSON_CACHE.read_text(encoding="utf-8"))

    logger.info("Downloading NC ZIP boundaries...")
    request = urllib.request.Request(NC_GEOJSON_URL, headers={"User-Agent": "RaleighEquityViz/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()

    NC_GEOJSON_CACHE.write_bytes(raw)
    return json.loads(raw.decode("utf-8"))


def filter_geojson(geojson: dict, zip_codes: set[str]) -> dict:
    """Keep only features whose ZCTA appears in our analysis cohort."""
    features = []
    for feature in geojson.get("features", []):
        zcta = str(feature.get("properties", {}).get("ZCTA5CE10", "")).zfill(5)
        if zcta in zip_codes:
            features.append(feature)

    if not features:
        raise ValueError("No GeoJSON polygons matched the income ZIP codes.")

    return {"type": "FeatureCollection", "features": features}


def _neglect_colormap(vmin: float, vmax: float) -> cm.LinearColormap:
    """Sequential scale for neglect rate (Folium legend)."""
    return cm.LinearColormap(
        colors=[PALETTE["seq_low"], PALETTE["seq_mid"], PALETTE["seq_high"]],
        vmin=vmin,
        vmax=vmax,
        caption=f"% Requests Unresolved Beyond {NEGLECT_THRESHOLD_DAYS} Days",
    )


def build_choropleth_map(metrics: pd.DataFrame, geojson: dict, output_path: Path) -> Path:
    """
    Dark-mode Folium choropleth of ZIP polygons.

    Fill color encodes 30-day neglect rate; outlines keep adjacent ZIPs
    visually distinct on the dark basemap.
    """
    metric_lookup = metrics.set_index("zip_code").to_dict("index")
    vmin = float(metrics["neglect_rate"].min())
    vmax = float(metrics["neglect_rate"].max())
    if vmin == vmax:
        vmax = vmin + 1.0

    colormap = _neglect_colormap(vmin, vmax)

    # Center on Raleigh using polygon centroids
    lats, lons = [], []
    for feature in geojson["features"]:
        geom = feature["geometry"]
        if geom["type"] == "Polygon":
            coords = geom["coordinates"][0]
        elif geom["type"] == "MultiPolygon":
            coords = geom["coordinates"][0][0]
        else:
            continue
        for lon, lat in coords:
            lats.append(lat)
            lons.append(lon)

    center = (float(np.mean(lats)), float(np.mean(lons)))

    equity_map = folium.Map(
        location=center,
        zoom_start=10,
        tiles="CartoDB positron",
        control_scale=True,
    )

    def style_function(feature: dict) -> dict:
        zcta = str(feature["properties"].get("ZCTA5CE10", "")).zfill(5)
        row = metric_lookup.get(zcta)
        if row is None:
            return {
                "fillColor": PALETTE["fill_subtle"],
                "color": PALETTE["border"],
                "weight": 1.2,
                "fillOpacity": 0.2,
            }
        color = colormap(row["neglect_rate"])
        return {
            "fillColor": color,
            "color": PALETTE["border"],
            "weight": 2.0,
            "fillOpacity": 0.78,
        }

    def highlight_function(_feature: dict) -> dict:
        return {"weight": 3, "color": PALETTE["ink"], "fillOpacity": 0.9}

    def on_each_feature(feature: dict, layer: folium.FeatureGroup) -> None:
        zcta = str(feature["properties"].get("ZCTA5CE10", "")).zfill(5)
        row = metric_lookup.get(zcta)
        if row is None:
            return

        popup_html = f"""
        <div style="font-family:'Open Sans',sans-serif; min-width:210px; color:{PALETTE['ink']};">
            <strong style="font-size:14px; font-weight:600;">ZIP {zcta}</strong>
            <hr style="border-color:{PALETTE['border']}; margin:6px 0;">
            <div>Median income: <b>${row['median_income']:,.0f}</b></div>
            <div>Requests: <b>{int(row['request_volume']):,}</b></div>
            <div>Median resolve: <b>{row['median_days']:.1f} days</b></div>
            <div>Mean resolve: <b>{row['mean_days']:.1f} days</b></div>
            <div>30-day neglect: <b>{row['neglect_rate']:.1f}%</b></div>
        </div>
        """
        tooltip = (
            f"ZIP {zcta} | Neglect {row['neglect_rate']:.1f}% "
            f"| Median {row['median_days']:.1f}d"
        )
        layer.bind_popup(folium.Popup(popup_html, max_width=280))
        layer.bind_tooltip(tooltip)

    folium.GeoJson(
        geojson,
        style_function=style_function,
        highlight_function=highlight_function,
        on_each_feature=on_each_feature,
        name="ZIP Boundaries",
    ).add_to(equity_map)

    colormap.add_to(equity_map)

    title_html = f"""
    <div style="position:fixed; top:14px; left:60px; z-index:9999;
                background:rgba(255,255,255,0.92); padding:12px 16px; border-radius:8px;
                border:1px solid {PALETTE['border']}; font-family:'Open Sans',sans-serif;
                color:{PALETTE['ink']}; box-shadow:0 4px 18px rgba(27,40,56,0.12);">
        <div style="font-size:15px; font-weight:600;">Raleigh 311 ZIP Equity Map</div>
        <div style="font-size:12px; font-weight:400; color:{PALETTE['muted']}; margin-top:4px;">
            Polygon color = share of requests taking &gt; {NEGLECT_THRESHOLD_DAYS} days
        </div>
    </div>
    """
    equity_map.get_root().html.add_child(folium.Element(title_html))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    equity_map.save(str(output_path))
    return output_path


def _geometry_rings(geometry: dict) -> list[list[list[float]]]:
    """Extract exterior coordinate rings from a GeoJSON geometry."""
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if geom_type == "Polygon":
        return [coords[0]]
    if geom_type == "MultiPolygon":
        return [part[0] for part in coords]
    return []


def _neglect_mpl_cmap():
    """Matplotlib colormap matching the Folium neglect-rate scale."""
    return neglect_colormap()


def build_choropleth_image(
    metrics: pd.DataFrame,
    geojson: dict,
    output_path: Path,
) -> Path:
    """
    Render a static transparent PNG of the ZIP choropleth.

    Polygon fill encodes 30-day neglect rate with project sequential colors.
    """
    metric_lookup = metrics.set_index("zip_code").to_dict("index")
    vmin = float(metrics["neglect_rate"].min())
    vmax = float(metrics["neglect_rate"].max())
    if vmin == vmax:
        vmax = vmin + 1.0

    cmap = _neglect_mpl_cmap()
    norm = Normalize(vmin=vmin, vmax=vmax)

    patches: list[MplPolygon] = []
    face_colors: list[str] = []
    label_points: list[tuple[float, float, str, float]] = []

    for feature in geojson["features"]:
        zcta = str(feature["properties"].get("ZCTA5CE10", "")).zfill(5)
        row = metric_lookup.get(zcta)
        neglect = row["neglect_rate"] if row else vmin
        color = cmap(norm(neglect))

        for ring in _geometry_rings(feature["geometry"]):
            poly = MplPolygon(ring, closed=True)
            patches.append(poly)
            face_colors.append(color)

            xs = [pt[0] for pt in ring]
            ys = [pt[1] for pt in ring]
            label_points.append((float(np.mean(xs)), float(np.mean(ys)), zcta, neglect))

    apply_chart_style()
    fig, ax = plt.subplots(figsize=(12, 10))

    collection = PatchCollection(
        patches,
        facecolor=face_colors,
        edgecolor=PALETTE["border"],
        linewidths=1.6,
        alpha=0.88,
    )
    ax.add_collection(collection)

    for lon, lat, zcta, neglect in label_points:
        ax.text(
            lon,
            lat,
            f"{zcta}\n{neglect:.0f}%",
            ha="center",
            va="center",
            fontsize=TYPE["annotation_size"],
            fontweight=TYPE["title_weight"],
            color=PALETTE["ink"],
            bbox=dict(
                boxstyle="round,pad=0.25",
                facecolor=PALETTE["fill_subtle"],
                edgecolor="none",
                alpha=0.85,
            ),
        )

    ax.autoscale()
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    ax.set_title(
        f"Raleigh 311 ZIP Equity Map\n"
        f"Color = % of requests taking > {NEGLECT_THRESHOLD_DAYS} days to resolve",
        fontsize=TYPE["title_size"],
        fontweight=TYPE["title_weight"],
        color=PALETTE["ink"],
        pad=16,
    )

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label(
        "30-Day Neglect Rate (%)",
        color=PALETTE["muted"],
        fontsize=TYPE["legend_size"],
        fontweight=TYPE["body_weight"],
    )
    cbar.ax.yaxis.set_tick_params(color=PALETTE["muted"])
    plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color=PALETTE["muted"])

    fig.text(
        0.5,
        0.02,
        "ZIP choropleth | Data: Ask Raleigh 311 + Census median income",
        ha="center",
        fontsize=TYPE["caption_size"],
        fontweight=TYPE["body_weight"],
        color=PALETTE["muted"],
    )

    return save_figure(fig, output_path)


def _format_zip_list(zip_codes: set[str] | Iterable[str]) -> str:
    return ", ".join(sorted(str(z) for z in zip_codes))


def build_service_disparity_bar(
    requests: pd.DataFrame,
    income: pd.DataFrame,
    output_path: Path,
    categories: tuple[str, ...] | None = None,
) -> Path:
    """
    Grouped bar chart: wealthy vs. low-income wait times by service category.

    Maps reveal geography; they obscure *which service types* drive inequity
    and the exact gap between income segments. This chart makes that gap legible.
    """
    merged = requests.merge(income, on="zip_code", how="inner")
    wealthy_zips, low_income_zips = wealth_segments(merged)
    if not wealthy_zips or not low_income_zips:
        raise ValueError("Wealth segments must contain at least one ZIP code each.")

    categories = categories or SERVICE_DISPARITY_CATEGORIES
    records: list[dict[str, object]] = []
    for category in categories:
        subset = merged.loc[merged["service_category"] == category]
        wealthy_avg = subset.loc[
            subset["zip_code"].isin(wealthy_zips), "days_to_resolve"
        ].mean()
        low_avg = subset.loc[
            subset["zip_code"].isin(low_income_zips), "days_to_resolve"
        ].mean()

        if pd.notna(wealthy_avg):
            records.append(
                {
                    "category": category,
                    "segment": "Top 20% Income",
                    "avg_days": float(wealthy_avg),
                }
            )
        if pd.notna(low_avg):
            records.append(
                {
                    "category": category,
                    "segment": "Bottom 20% Income",
                    "avg_days": float(low_avg),
                }
            )

    plot_df = pd.DataFrame(records)
    if plot_df.empty:
        raise ValueError("No service-category disparity data to plot.")

    category_order = (
        plot_df.groupby("category")["avg_days"]
        .max()
        .sort_values(ascending=True)
        .index.tolist()
    )

    apply_chart_style()
    fig, ax = plt.subplots(figsize=(10, 6.5))

    sns.barplot(
        data=plot_df,
        y="category",
        x="avg_days",
        hue="segment",
        order=category_order,
        hue_order=["Top 20% Income", "Bottom 20% Income"],
        palette={
            "Top 20% Income": PALETTE["wealthy"],
            "Bottom 20% Income": PALETTE["low_income"],
        },
        edgecolor=PALETTE["point_edge"],
        linewidth=0.8,
        ax=ax,
    )

    ax.set_title("Service Response Disparity by Income Segment")
    ax.set_xlabel("Average Days to Resolve")
    ax.set_ylabel("")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(days_formatter))
    ax.grid(False)
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


def build_zip_ranking_bar(metrics: pd.DataFrame, output_path: Path) -> Path:
    """
    Dual-metric ranked bar chart: neglect rate vs. median resolve time per ZIP.

    Complements the map by showing exact ranked magnitudes — how far each ZIP
    sits from the cohort median — without relying on color interpretation alone.
    """
    data = metrics.sort_values("neglect_rate", ascending=True).copy()
    y_pos = np.arange(len(data))
    bar_height = 0.36

    apply_chart_style()
    fig, ax = plt.subplots(figsize=(11, 7))

    ax.barh(
        y_pos - bar_height / 2,
        data["neglect_rate"],
        height=bar_height,
        color=PALETTE["seq_high"],
        alpha=0.88,
        label=f"Neglect rate (>{NEGLECT_THRESHOLD_DAYS}d)",
        edgecolor=PALETTE["point_edge"],
        linewidth=0.6,
    )
    ax.barh(
        y_pos + bar_height / 2,
        data["median_days"],
        height=bar_height,
        color=PALETTE["seq_low"],
        alpha=0.88,
        label="Median days to resolve",
        edgecolor=PALETTE["point_edge"],
        linewidth=0.6,
    )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(
        [f"{z}  (${inc:,.0f})" for z, inc in zip(data["zip_code"], data["median_income"])],
        fontsize=TYPE["tick_size"],
        color=PALETTE["ink"],
    )
    ax.set_xlabel("Days / Percent", color=PALETTE["ink"])
    ax.set_title(
        "ZIP Rankings: Neglect Rate vs. Typical Wait Time",
        fontsize=TYPE["title_size"],
        fontweight=TYPE["title_weight"],
        color=PALETTE["ink"],
        pad=14,
    )
    trim_spines(ax)
    ax.grid(axis="x", color=PALETTE["border"], alpha=0.35, linestyle="--")
    style_legend(ax, loc="lower right")

    add_caption(
        fig,
        "Sorted by neglect rate | Labels include ZIP median income",
    )

    return save_figure(fig, output_path)


def main() -> int:
    """Build dark-mode ZIP choropleth and paired bar charts."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    try:
        requests_path = _resolve_requests_path(None)
        income_path = PROJECT_ROOT / "raleigh_income.csv"

        requests = load_requests(requests_path)
        income = load_income(income_path)
        metrics = build_zip_metrics(requests, income)

        nc_geojson = fetch_nc_geojson()
        zip_codes = set(metrics["zip_code"])
        filtered_geojson = filter_geojson(nc_geojson, zip_codes)

        map_path = build_choropleth_map(
            metrics,
            filtered_geojson,
            OUTPUT_DIR / "raleigh_zip_choropleth.html",
        )
        map_image_path = build_choropleth_image(
            metrics,
            filtered_geojson,
            OUTPUT_DIR / "raleigh_zip_choropleth.png",
        )
        service_bar_path = build_service_disparity_bar(
            requests,
            income,
            OUTPUT_DIR / "zip_service_disparity_bar.png",
        )
        ranking_bar_path = build_zip_ranking_bar(
            metrics,
            OUTPUT_DIR / "zip_rankings_bar.png",
        )

        print("\nRaleigh ZIP Choropleth Visualization")
        print(f"  ZIP codes mapped: {len(metrics)}")
        print(f"  Requests in cohort: {metrics['request_volume'].sum():,}")
        print("\nOutputs:")
        print(f"  Map (interactive HTML):    {map_path}")
        print(f"  Map (static PNG):          {map_image_path}")
        print(f"  Service disparity bars:    {service_bar_path}")
        print(f"  ZIP ranking bars:          {ranking_bar_path}")
        print(
            "\nPairing rationale:"
            "\n  Map  -> spatial clustering of 30-day neglect"
            "\n  Bars -> exact service-type gaps & ranked ZIP magnitudes"
        )
        return 0

    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Failed to build ZIP choropleth visualization.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
