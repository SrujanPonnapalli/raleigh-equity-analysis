"""
Deep-dive exploratory analysis for Raleigh 311 civic equity.

Tests three hypotheses that broad ZIP-level aggregation may mask real
income–response-time relationships: standardized sub-category comparison,
30-day neglect rate thresholding, and median-based typical experience.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

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
    percent_formatter,
    save_figure,
    style_legend,
    trim_spines,
)
from data_pipeline import load_income, wealth_segments
from main import _resolve_requests_path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "eda"

HOURS_PER_DAY = 24.0
NEGLECT_THRESHOLD_DAYS = 30
DISTRIBUTION_CAP_DAYS = 60
MIN_ZIPS_FOR_CORRELATION = 3


def _normalize_zip(series: pd.Series) -> pd.Series:
    """Normalize ZIP codes to comparable string values."""
    return (
        series.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(5)
    )


def load_requests_for_eda(path: str | Path) -> pd.DataFrame:
    """
    Load request data with fields needed for sub-category drilldown.

    Missing resolution times and ZIP codes are dropped so downstream
    statistics are computed on comparable, complete records only.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Requests file not found: {path}")

    df = pd.read_csv(path)
    required = ["ZIP Code", "Hours to Resolve", "Service Category", "Service", "Request Type"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Requests file is missing required columns: {missing}")

    cleaned = df.copy()
    cleaned["zip_code"] = _normalize_zip(cleaned["ZIP Code"])
    cleaned["hours_to_resolve"] = pd.to_numeric(cleaned["Hours to Resolve"], errors="coerce")
    cleaned["days_to_resolve"] = cleaned["hours_to_resolve"] / HOURS_PER_DAY
    cleaned["service_category"] = cleaned["Service Category"].astype("string").str.strip()
    cleaned["service"] = cleaned["Service"].astype("string").str.strip()
    cleaned["request_type"] = cleaned["Request Type"].astype("string").str.strip()

    # Prefer the most specific label available; fall back to broader Service.
    cleaned["specific_request"] = cleaned["request_type"].where(
        cleaned["request_type"].notna() & (cleaned["request_type"] != "<NA>") & (cleaned["request_type"] != ""),
        cleaned["service"],
    )
    cleaned["specific_request"] = cleaned["specific_request"].replace({"<NA>": pd.NA, "": pd.NA})

    before = len(cleaned)
    cleaned = cleaned.dropna(subset=["zip_code", "days_to_resolve", "specific_request"])
    dropped = before - len(cleaned)
    if dropped:
        logger.warning("Dropped %d row(s) with missing ZIP, resolve time, or request label.", dropped)

    return cleaned.reset_index(drop=True)


def merge_with_income(requests: pd.DataFrame, income: pd.DataFrame) -> pd.DataFrame:
    """Attach median income; keep only ZIP codes present in both datasets."""
    merged = requests.merge(income, on="zip_code", how="inner")
    excluded = len(requests) - len(merged)
    if excluded:
        logger.warning(
            "%d request(s) excluded because their ZIP code lacks income data.",
            excluded,
        )
    return merged


def _pearson_at_zip_level(zip_metrics: pd.DataFrame) -> tuple[float, float, int]:
    """
    Compute Pearson correlation between income and a ZIP-level metric.

    Requires at least ``MIN_ZIPS_FOR_CORRELATION`` ZIP codes so that r and
    p-values are not computed on degenerate two-point samples.
    """
    data = zip_metrics.dropna(subset=["median_income", "metric_value"])
    n = len(data)
    if n < MIN_ZIPS_FOR_CORRELATION:
        return float("nan"), float("nan"), n

    r, p = stats.pearsonr(data["median_income"], data["metric_value"])
    return float(r), float(p), n


def apples_to_apples_test(merged: pd.DataFrame) -> pd.DataFrame:
    """
    Hypothesis 1: Broad categories hide standardized-task disparities.

    For each of the top 5 most common specific requests, we compare
    median income to average wait time across ZIP codes *for that exact
  task only*. This controls for the mix of easy vs. hard work types.
    """
    print("\n" + "=" * 72)
    print("HYPOTHESIS 1 - Apples-to-Apples Sub-category Drilldown")
    print("=" * 72)
    print(
        "Rationale: Aggregating all service types within a ZIP blends fast tasks\n"
        "(e.g., potholes) with slow ones (e.g., tree removal), diluting any\n"
        "income gradient. We re-test correlation on identical, standardized tasks.\n"
    )

    top_requests = merged["specific_request"].value_counts().head(5)
    results: list[dict[str, object]] = []

    print(f"{'Specific Request':<34} {'N':>6} {'ZIPs':>5} {'r':>8} {'p-value':>10}")
    print("-" * 72)

    for request_name, count in top_requests.items():
        subset = merged.loc[merged["specific_request"] == request_name]
        zip_metrics = (
            subset.groupby("zip_code", as_index=False)
            .agg(
                median_income=("median_income", "first"),
                metric_value=("days_to_resolve", "mean"),
                request_count=("days_to_resolve", "size"),
            )
        )
        r, p, n_zips = _pearson_at_zip_level(zip_metrics)

        results.append(
            {
                "specific_request": request_name,
                "request_count": int(count),
                "zip_codes": n_zips,
                "pearson_r": r,
                "p_value": p,
            }
        )

        r_str = f"{r:+.3f}" if pd.notna(r) else "n/a"
        p_str = f"{p:.4f}" if pd.notna(p) else "n/a"
        print(f"{str(request_name)[:33]:<34} {count:>6} {n_zips:>5} {r_str:>8} {p_str:>10}")

    result_df = pd.DataFrame(results)
    significant = result_df.loc[result_df["p_value"] < 0.05]
    if not significant.empty:
        print(
            f"\n-> {len(significant)} of 5 standardized tasks show p < 0.05 "
            "(suggesting sub-category drilldown reveals signal)."
        )
    else:
        print(
            "\n-> No standardized task reached p < 0.05 at the ZIP level. "
            "Income may still not predict wait time even within task type, "
            "or sample sizes per ZIP are too thin."
        )

    return result_df


def extreme_neglect_test(merged: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    """
    Hypothesis 2: Averages are distorted by extreme delays.

    The 30-day neglect rate (% of requests unresolved beyond 30 days)
    captures systemic abandonment better than the arithmetic mean.
    """
    print("\n" + "=" * 72)
    print("HYPOTHESIS 2 - Extreme Neglect (30-Day Threshold)")
    print("=" * 72)
    print(
        "Rationale: A handful of 400-day outliers inflate ZIP-level means.\n"
        "Neglect rate measures how often a ZIP's residents experience\n"
        f"effectively forgotten service (>{NEGLECT_THRESHOLD_DAYS} days).\n"
    )

    zip_neglect = (
        merged.groupby("zip_code", as_index=False)
        .agg(
            median_income=("median_income", "first"),
            neglect_rate=(
                "days_to_resolve",
                lambda s: 100.0 * (s > NEGLECT_THRESHOLD_DAYS).mean(),
            ),
            request_count=("days_to_resolve", "size"),
        )
    )

    data = zip_neglect.dropna()
    if len(data) < MIN_ZIPS_FOR_CORRELATION:
        raise ValueError("Insufficient ZIP codes for neglect-rate regression.")

    slope, intercept, r, p, stderr = stats.linregress(
        data["median_income"], data["neglect_rate"]
    )

    print(f"ZIP codes analyzed:          {len(data)}")
    print(f"Mean neglect rate:           {data['neglect_rate'].mean():.1f}%")
    print(f"Pearson r (income vs neglect): {r:+.3f}")
    print(f"p-value:                     {p:.4f}")
    print(f"Regression slope:            {slope * 1000:.4f} pp per $1k income")

    if p < 0.05:
        direction = "higher-income" if slope < 0 else "lower-income"
        print(f"\n-> Significant relationship: {direction} ZIPs show different neglect rates.")
    else:
        print("\n-> No significant income-neglect relationship at the ZIP level.")

    apply_chart_style()
    fig, ax = plt.subplots(figsize=(10, 6.5))

    sizes = 60 + (data["request_count"] / data["request_count"].max()) * 280
    ax.scatter(
        data["median_income"],
        data["neglect_rate"],
        s=sizes,
        c=PALETTE["scatter"],
        alpha=0.78,
        edgecolors=PALETTE["point_edge"],
        linewidths=1.1,
        zorder=3,
    )

    x_line = np.linspace(data["median_income"].min(), data["median_income"].max(), 100)
    y_line = slope * x_line + intercept
    ax.plot(
        x_line,
        y_line,
        color=PALETTE["trend"],
        linewidth=2.2,
        linestyle="--",
        label=f"Trend (r = {r:.2f}, p = {p:.3g})",
        zorder=2,
    )

    for _, row in data.iterrows():
        ax.annotate(
            row["zip_code"],
            (row["median_income"], row["neglect_rate"]),
            textcoords="offset points",
            xytext=(4, 4),
            fontsize=TYPE["annotation_size"],
            fontweight=TYPE["title_weight"],
            color=PALETTE["muted"],
        )

    ax.set_title(f"Median Income vs. {NEGLECT_THRESHOLD_DAYS}-Day Neglect Rate")
    ax.set_xlabel("Median Household Income")
    ax.set_ylabel(f"Neglect Rate (% requests > {NEGLECT_THRESHOLD_DAYS} days)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(percent_formatter))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(currency_formatter))
    style_legend(ax, loc="upper left")
    trim_spines(ax)

    output_path = output_dir / "neglect_rate_scatter.png"
    save_figure(fig, output_path)
    print(f"\nSaved chart: {output_path}")

    return zip_neglect


def typical_experience_test(merged: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    """
    Hypothesis 3: The arithmetic mean misrepresents typical wait times.

    Right-skewed resolution times make the median a more honest central
    tendency. We also visualize the raw distributions for wealth segments.
    """
    print("\n" + "=" * 72)
    print("HYPOTHESIS 3 - Typical Experience (Median vs. Mean)")
    print("=" * 72)
    print(
        "Rationale: A few extreme delays pull ZIP-level means upward.\n"
        "Median days-to-resolve better reflects what most residents experience.\n"
    )

    zip_median = (
        merged.groupby("zip_code", as_index=False)
        .agg(
            median_income=("median_income", "first"),
            median_days=("days_to_resolve", "median"),
            mean_days=("days_to_resolve", "mean"),
            request_count=("days_to_resolve", "size"),
        )
    )

    data = zip_median.dropna(subset=["median_income", "median_days"])
    slope, intercept, r, p, _ = stats.linregress(
        data["median_income"], data["median_days"]
    )

    print(f"ZIP codes analyzed:               {len(data)}")
    print(f"Overall median resolve time:      {merged['days_to_resolve'].median():.1f} days")
    print(f"Overall mean resolve time:        {merged['days_to_resolve'].mean():.1f} days")
    print(f"Pearson r (income vs median days): {r:+.3f}")
    print(f"p-value:                          {p:.4f}")

    wealthy_zips, low_income_zips = wealth_segments(merged)
    wealthy_label = f"Top 20% income ({len(wealthy_zips)} ZIPs)"
    low_label = f"Bottom 20% income ({len(low_income_zips)} ZIPs)"

    wealthy_times = merged.loc[
        merged["zip_code"].isin(wealthy_zips), "days_to_resolve"
    ].clip(upper=DISTRIBUTION_CAP_DAYS)
    low_times = merged.loc[
        merged["zip_code"].isin(low_income_zips), "days_to_resolve"
    ].clip(upper=DISTRIBUTION_CAP_DAYS)

    print(f"\nSegment medians (all requests, uncapped):")
    print(
        f"  {wealthy_label}: "
        f"{merged.loc[merged['zip_code'].isin(wealthy_zips), 'days_to_resolve'].median():.1f} days"
    )
    print(
        f"  {low_label}: "
        f"{merged.loc[merged['zip_code'].isin(low_income_zips), 'days_to_resolve'].median():.1f} days"
    )
    print(
        f"\nDistribution plot capped at {DISTRIBUTION_CAP_DAYS} days "
        "so the bulk of the distribution is readable."
    )

    apply_chart_style()
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), sharey=True)

    plot_specs = [
        (axes[0], wealthy_times, wealthy_label, PALETTE["wealthy"]),
        (axes[1], low_times, low_label, PALETTE["low_income"]),
    ]

    for ax, series, title, color in plot_specs:
        if series.empty:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(title)
            continue

        sns.histplot(
            series,
            bins=30,
            stat="density",
            kde=True,
            color=color,
            alpha=0.55,
            edgecolor="white",
            linewidth=0.6,
            ax=ax,
        )
        ax.axvline(
            series.median(),
            color=PALETTE["ink"],
            linestyle="--",
            linewidth=1.5,
            label=f"Median = {series.median():.1f}d",
        )
        ax.set_title(title, fontsize=TYPE["panel_title_size"], fontweight=TYPE["title_weight"])
        ax.set_xlabel("Days to Resolve")
        ax.set_xlim(0, DISTRIBUTION_CAP_DAYS)
        style_legend(ax, fontsize=TYPE["legend_size"])
        trim_spines(ax)

    axes[0].set_ylabel("Density")
    fig.suptitle(
        "Resolution Time Distributions by Income Segment",
        fontsize=TYPE["title_size"],
        fontweight=TYPE["title_weight"],
        y=1.02,
        color=PALETTE["ink"],
    )

    output_path = output_dir / "distribution_skew.png"
    save_figure(fig, output_path, bbox_inches="tight")
    print(f"Saved chart: {output_path}")

    return zip_median


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Raleigh 311 equity deep-dive EDA.")
    parser.add_argument("--requests", type=str, default=None, help="Path to requests CSV.")
    parser.add_argument(
        "--income",
        type=str,
        default=str(PROJECT_ROOT / "raleigh_income.csv"),
        help="Path to median-income CSV.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for exploratory charts.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run all three hypothesis tests and write EDA artifacts."""
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    try:
        requests_path = _resolve_requests_path(args.requests)
        income_path = Path(args.income)
        output_dir = Path(args.output_dir)

        print("Raleigh 311 Equity Deep Dive")
        print(f"Requests: {requests_path}")
        print(f"Income:   {income_path}")

        requests = load_requests_for_eda(requests_path)
        income = load_income(income_path)
        merged = merge_with_income(requests, income)

        if merged.empty:
            raise ValueError("No overlapping records between requests and income data.")

        print(
            f"\nAnalysis cohort: {len(merged):,} requests across "
            f"{merged['zip_code'].nunique()} ZIP codes with income data."
        )

        apples_to_apples_test(merged)
        extreme_neglect_test(merged, output_dir)
        typical_experience_test(merged, output_dir)

        print("\n" + "=" * 72)
        print("Deep dive complete. Charts saved to:", output_dir)
        print("=" * 72)
        return 0

    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Unexpected error during deep dive.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
