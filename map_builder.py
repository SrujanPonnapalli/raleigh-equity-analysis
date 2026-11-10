"""
Interactive Folium map builder for Raleigh civic equity analysis.

Visualizes geographic patterns in 311 response times using the shared
visual language (VISUAL_LANGUAGE.md).
"""

from __future__ import annotations

import logging
from pathlib import Path

import branca.colormap as cm
import folium
import pandas as pd
from folium.plugins import HeatMap

from viz_theme import PALETTE

logger = logging.getLogger(__name__)

RALEIGH_CENTER = (35.7796, -78.6382)
DEFAULT_ZOOM = 11


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _resolution_color(days: float, vmin: float, vmax: float) -> str:
    """Map resolution time to the project sequential scale (teal -> amber -> red)."""
    if vmax <= vmin:
        normalized = 0.5
    else:
        normalized = (days - vmin) / (vmax - vmin)
    normalized = max(0.0, min(1.0, normalized))

    low = _hex_to_rgb(PALETTE["seq_low"])
    mid = _hex_to_rgb(PALETTE["seq_mid"])
    high = _hex_to_rgb(PALETTE["seq_high"])

    if normalized <= 0.5:
        t = normalized / 0.5
        rgb = tuple(int(low[i] + (mid[i] - low[i]) * t) for i in range(3))
    else:
        t = (normalized - 0.5) / 0.5
        rgb = tuple(int(mid[i] + (high[i] - mid[i]) * t) for i in range(3))

    return _rgb_to_hex(rgb)


def _validate_map_data(requests: pd.DataFrame) -> pd.DataFrame:
    """Return map-ready rows with valid coordinates and resolution times."""
    required = {
        "latitude",
        "longitude",
        "days_to_resolve",
        "service_category",
    }
    missing = required - set(requests.columns)
    if missing:
        raise ValueError(f"Map data is missing columns: {sorted(missing)}")

    valid = requests.dropna(
        subset=["latitude", "longitude", "days_to_resolve", "service_category"]
    ).copy()

    if valid.empty:
        raise ValueError("No geocoded requests with resolution times are available.")

    return valid


def build_equity_map(
    requests: pd.DataFrame,
    output_path: str | Path,
    use_heatmap: bool = False,
    sample_size: int | None = 2500,
) -> Path:
    """Build an interactive Folium map of 311 response-time patterns."""
    data = _validate_map_data(requests)

    if sample_size is not None and len(data) > sample_size:
        logger.info(
            "Sampling %d of %d points for circle markers.",
            sample_size,
            len(data),
        )
        marker_data = data.sample(sample_size, random_state=42)
    else:
        marker_data = data

    vmin = float(data["days_to_resolve"].quantile(0.05))
    vmax = float(data["days_to_resolve"].quantile(0.95))
    if vmin == vmax:
        vmax = vmin + 1.0

    center_lat = float(data["latitude"].median())
    center_lon = float(data["longitude"].median())

    equity_map = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=DEFAULT_ZOOM,
        tiles="CartoDB positron",
        control_scale=True,
    )

    colormap = cm.LinearColormap(
        colors=[PALETTE["seq_low"], PALETTE["seq_mid"], PALETTE["seq_high"]],
        vmin=vmin,
        vmax=vmax,
        caption="Days to Resolve",
    )
    colormap.add_to(equity_map)

    marker_cluster = folium.plugins.MarkerCluster(
        name="Service Requests",
        disableClusteringAtZoom=14,
    )

    for _, row in marker_data.iterrows():
        days = float(row["days_to_resolve"])
        color = _resolution_color(days, vmin, vmax)
        category = str(row["service_category"])
        tooltip_html = (
            f"<span style='font-family:Open Sans,sans-serif'>"
            f"<b>{category}</b><br>"
            f"Days to resolve: <b>{days:.1f}</b></span>"
        )

        folium.CircleMarker(
            location=[float(row["latitude"]), float(row["longitude"])],
            radius=5,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.78,
            weight=1,
            tooltip=folium.Tooltip(tooltip_html),
        ).add_to(marker_cluster)

    marker_cluster.add_to(equity_map)

    if use_heatmap:
        heat_data = [
            [float(row["latitude"]), float(row["longitude"]), float(row["days_to_resolve"])]
            for _, row in data.iterrows()
        ]
        HeatMap(
            heat_data,
            min_opacity=0.35,
            radius=16,
            blur=20,
            max_zoom=13,
            gradient={
                0.0: PALETTE["seq_low"],
                0.5: PALETTE["seq_mid"],
                1.0: PALETTE["seq_high"],
            },
        ).add_to(equity_map)

    folium.LayerControl(collapsed=False).add_to(equity_map)

    title_html = f"""
    <div style="
        position: fixed;
        top: 12px;
        left: 56px;
        z-index: 9999;
        background: rgba(255, 255, 255, 0.92);
        padding: 10px 14px;
        border-radius: 6px;
        border: 1px solid {PALETTE['border']};
        font-family: 'Open Sans', sans-serif;
        font-size: 14px;
        font-weight: 600;
        color: {PALETTE['ink']};
        box-shadow: 0 1px 6px rgba(27, 40, 56, 0.12);
    ">
        Raleigh 311 Response Equity Map<br>
        <span style="color:{PALETTE['muted']}; font-size:12px; font-weight:400;">
            Marker color reflects days to resolve &middot; Hover for service details
        </span>
    </div>
    """
    equity_map.get_root().html.add_child(folium.Element(title_html))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    equity_map.save(str(output_path))
    return output_path
