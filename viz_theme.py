"""
Shared visual theme for Raleigh 311 civic equity graphics.

See VISUAL_LANGUAGE.md for the full design specification.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FuncFormatter

# ---------------------------------------------------------------------------
# Color tokens (VISUAL_LANGUAGE.md)
# ---------------------------------------------------------------------------
PALETTE = {
    "ink": "#1B2838",
    "muted": "#5A6B7D",
    "border": "#C5CDD6",
    "fill_subtle": "#E8EDF2",
    "wealthy": "#1F8A7A",
    "low_income": "#D4624A",
    "scatter": "#4A6073",
    "trend": "#1F6F5F",
    "point_edge": "#FFFFFF",
    "seq_low": "#1F8A7A",
    "seq_mid": "#E3A008",
    "seq_high": "#C94C4C",
    # Back-compat aliases used across modules
    "slate": "#5A6B7D",
    "slate_light": "#C5CDD6",
    "accent": "#D4624A",
    "accent_alt": "#1F8A7A",
    "scatter_fill": "#4A6073",
    "background": "none",
}

FONT_FAMILY = "Open Sans"
FONT_FALLBACK = "DejaVu Sans"

TYPE = {
    "title_size": 15,
    "panel_title_size": 13,
    "label_size": 12,
    "tick_size": 10,
    "legend_size": 10,
    "caption_size": 9,
    "annotation_size": 8,
    "title_weight": 600,
    "body_weight": 400,
}

SEGMENT_PALETTE = {
    "Top 20% Income": PALETTE["wealthy"],
    "Bottom 20% Income": PALETTE["low_income"],
}

SAVE_DPI = 300


def resolve_font_family() -> str:
    """Return Open Sans when available, otherwise a sensible fallback."""
    from matplotlib import font_manager

    installed = {f.name for f in font_manager.fontManager.ttflist}
    if FONT_FAMILY in installed:
        return FONT_FAMILY
    return FONT_FALLBACK


def neglect_colormap() -> LinearSegmentedColormap:
    """Three-stop sequential scale for neglect-rate choropleths."""
    return LinearSegmentedColormap.from_list(
        "raleigh_neglect",
        [PALETTE["seq_low"], PALETTE["seq_mid"], PALETTE["seq_high"]],
    )


def income_colormap() -> LinearSegmentedColormap:
    """Light-to-dark green scale: darker = higher median income."""
    return LinearSegmentedColormap.from_list(
        "raleigh_income",
        ["#D4EDE6", "#7FBFB3", "#1F8A7A", "#0D5C4D"],
    )


def wait_time_colormap() -> LinearSegmentedColormap:
    """Light-to-dark red scale: darker = longer response time."""
    return LinearSegmentedColormap.from_list(
        "raleigh_wait",
        ["#FCE8E6", "#E88880", "#C94C4C", "#7F1D1D"],
    )


def apply_chart_style() -> str:
    """
    Apply the project-wide matplotlib / seaborn style.

    Returns the font family actually in use.
    """
    family = resolve_font_family()
    sns.set_theme(style="white", font=family)
    plt.rcParams.update(
        {
            "font.family": family,
            "font.size": TYPE["tick_size"],
            "font.weight": TYPE["body_weight"],
            "figure.facecolor": "none",
            "axes.facecolor": "none",
            "axes.edgecolor": PALETTE["border"],
            "axes.labelcolor": PALETTE["ink"],
            "axes.labelsize": TYPE["label_size"],
            "axes.labelweight": TYPE["body_weight"],
            "axes.titlesize": TYPE["title_size"],
            "axes.titleweight": TYPE["title_weight"],
            "text.color": PALETTE["ink"],
            "xtick.color": PALETTE["muted"],
            "ytick.color": PALETTE["muted"],
            "xtick.labelsize": TYPE["tick_size"],
            "ytick.labelsize": TYPE["tick_size"],
            "legend.fontsize": TYPE["legend_size"],
            "legend.frameon": False,
            "grid.color": PALETTE["border"],
            "grid.alpha": 0.35,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.dpi": 120,
            "savefig.dpi": SAVE_DPI,
            "savefig.bbox": "tight",
            "savefig.transparent": True,
            "savefig.facecolor": "none",
        }
    )
    return family


def trim_spines(ax: plt.Axes) -> None:
    """Remove top/right spines and soften the remainder."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(PALETTE["border"])
    ax.spines["bottom"].set_color(PALETTE["border"])


def style_legend(ax: plt.Axes, **kwargs: object) -> None:
    """Apply consistent legend styling on a transparent canvas."""
    legend = ax.legend(**kwargs)
    if legend is not None:
        for text in legend.get_texts():
            text.set_color(PALETTE["ink"])
            text.set_fontweight(TYPE["body_weight"])
        title = legend.get_title()
        if title is not None:
            title.set_color(PALETTE["ink"])
            title.set_fontweight(TYPE["title_weight"])
    return legend


def add_caption(fig: plt.Figure, text: str, y: float = 0.01) -> None:
    """Add a footnote caption below the chart."""
    fig.text(
        0.01,
        y,
        text,
        fontsize=TYPE["caption_size"],
        fontweight=TYPE["body_weight"],
        color=PALETTE["muted"],
    )


def save_figure(fig: plt.Figure, output_path: str | Path, **kwargs: object) -> Path:
    """Save a figure as a transparent PNG at project DPI."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_kwargs = {
        "dpi": SAVE_DPI,
        "bbox_inches": "tight",
        "transparent": True,
        "facecolor": "none",
    }
    save_kwargs.update(kwargs)
    fig.savefig(output_path, **save_kwargs)
    plt.close(fig)
    return output_path


def currency_formatter(value: float, _pos: int) -> str:
    return f"${value:,.0f}"


def days_formatter(value: float, _pos: int) -> str:
    return f"{value:.0f}"


def percent_formatter(value: float, _pos: int) -> str:
    return f"{value:.0f}%"
