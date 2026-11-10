"""
Static chart generation for Raleigh civic equity analysis.

Produces presentation-ready matplotlib/seaborn visualizations using the
shared visual language defined in VISUAL_LANGUAGE.md and viz_theme.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

from viz_theme import (
    PALETTE,
    TYPE,
    add_caption,
    apply_chart_style,
    currency_formatter,
    days_formatter,
    save_figure,
    style_legend,
    trim_spines,
)


def plot_equity_scatter(
    merged_zip: pd.DataFrame,
    output_path: str | Path,
    top_n_categories: int = 5,
) -> Path:
    """
    Create an equity scatter plot: income vs. average resolution time by ZIP.

    Each point represents a ZIP code. Point size encodes request volume.
    A linear regression trendline highlights the wealth–response correlation.
    """
    _ = top_n_categories
    required = {"median_income", "avg_days_to_resolve", "request_volume", "zip_code"}
    missing = required - set(merged_zip.columns)
    if missing:
        raise ValueError(f"merged_zip is missing columns: {sorted(missing)}")
    if len(merged_zip) < 2:
        raise ValueError("At least two ZIP codes are required for the scatter plot.")

    apply_chart_style()
    data = merged_zip.dropna(
        subset=["median_income", "avg_days_to_resolve", "request_volume"]
    ).copy()
    if len(data) < 3 or data["median_income"].nunique() < 2:
        raise ValueError("At least three valid ZIPs and distinct incomes are required.")

    fig, ax = plt.subplots(figsize=(10, 6.5))

    size_scale = 350
    min_size = 60
    volumes = data["request_volume"].to_numpy(dtype=float)
    sizes = min_size + (volumes / volumes.max()) * size_scale

    ax.scatter(
        data["median_income"],
        data["avg_days_to_resolve"],
        s=sizes,
        c=PALETTE["scatter"],
        alpha=0.78,
        edgecolors=PALETTE["point_edge"],
        linewidths=1.2,
        zorder=3,
    )

    x = data["median_income"].to_numpy(dtype=float)
    y = data["avg_days_to_resolve"].to_numpy(dtype=float)
    slope, intercept, r_value, p_value, _ = stats.linregress(x, y)
    x_line = np.linspace(x.min(), x.max(), 100)
    y_line = slope * x_line + intercept
    ax.plot(
        x_line,
        y_line,
        color=PALETTE["trend"],
        linewidth=2.2,
        linestyle="--",
        label=f"Exploratory trend (r = {r_value:.2f}, p = {p_value:.3g})",
        zorder=2,
    )

    for _, row in data.iterrows():
        ax.annotate(
            row["zip_code"],
            (row["median_income"], row["avg_days_to_resolve"]),
            textcoords="offset points",
            xytext=(4, 4),
            fontsize=TYPE["annotation_size"],
            fontweight=TYPE["title_weight"],
            color=PALETTE["muted"],
        )

    ax.set_title("Income and Recorded Resolution Time by ZIP Code")
    ax.set_xlabel("Median Household Income")
    ax.set_ylabel("Average Days to Resolve")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(currency_formatter))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(days_formatter))
    style_legend(ax, loc="upper right")
    trim_spines(ax)
    fig.subplots_adjust(bottom=0.2)

    add_caption(
        fig,
        "Completed requests with matched income only; unfinished requests excluded. Point size = completed count.",
    )
    return save_figure(fig, output_path)


def plot_service_disparity_bars(
    merged_requests: pd.DataFrame,
    wealthy_zips: Iterable[str],
    low_income_zips: Iterable[str],
    output_path: str | Path,
    top_categories: int = 5,
) -> Path:
    """
    Create a grouped horizontal bar chart of service-category disparities.

    Compares average resolution time in the top 20% wealthiest ZIP codes
    versus the bottom 20% lowest-income ZIP codes for the most common
    service categories.
    """
    required = {"service_category", "days_to_resolve", "zip_code"}
    missing = required - set(merged_requests.columns)
    if missing:
        raise ValueError(f"merged_requests is missing columns: {sorted(missing)}")

    wealthy = set(wealthy_zips)
    low_income = set(low_income_zips)
    if not wealthy or not low_income:
        raise ValueError("Wealth segments must contain at least one ZIP code each.")

    top_cats = (
        merged_requests["service_category"]
        .value_counts()
        .head(top_categories)
        .index.tolist()
    )
    if not top_cats:
        raise ValueError("No service categories available for disparity chart.")

    records: list[dict[str, object]] = []
    for category in top_cats:
        subset = merged_requests.loc[merged_requests["service_category"] == category]
        wealthy_avg = subset.loc[
            subset["zip_code"].isin(wealthy), "days_to_resolve"
        ].mean()
        low_avg = subset.loc[
            subset["zip_code"].isin(low_income), "days_to_resolve"
        ].mean()

        if pd.notna(wealthy_avg):
            records.append(
                {
                    "service_category": category,
                    "segment": "Top 20% Income",
                    "avg_days": wealthy_avg,
                }
            )
        if pd.notna(low_avg):
            records.append(
                {
                    "service_category": category,
                    "segment": "Bottom 20% Income",
                    "avg_days": low_avg,
                }
            )

    plot_df = pd.DataFrame(records)
    if plot_df.empty:
        raise ValueError("No disparity metrics could be computed for the top categories.")

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

    ax.set_title("Completed-Request Resolution Time by Income Segment")
    ax.set_xlabel("Average Days to Resolve")
    ax.set_ylabel("")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(days_formatter))
    style_legend(ax, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    fig.subplots_adjust(bottom=0.24)
    trim_spines(ax)

    add_caption(
        fig,
        "Completed requests only; unfinished requests excluded. Top 5 categories; top/bottom 20% of income ZIPs.",
    )
    return save_figure(fig, output_path)
