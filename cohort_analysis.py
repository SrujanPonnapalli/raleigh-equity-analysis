"""Compare recorded resolution within a fixed follow-up window.

Run ``python cohort_analysis.py`` against the saved snapshot. This is exploratory
direct standardization, not a causal estimate or a service-standard assessment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from data_pipeline import load_income, load_requests, wealth_segments

ROOT = Path(__file__).resolve().parent
LOCAL_TIME = "America/New_York"


def prepare_cohort(requests, income, as_of, start, end, horizon=90, include_middle=False):
    """Use all submissions in [start, end), with complete follow-up for everyone.

    A request succeeds only if Resolved At is within horizon calendar days of
    submission and no later than the snapshot. Missing resolution is a failure,
    not an exclusion. Closed At and rounded resolution hours are not substituted.
    """
    as_of, start, end = map(pd.Timestamp, (as_of, start, end))
    if any(value.tzinfo is None for value in (as_of, start, end)):
        raise ValueError("Cohort boundaries and snapshot time must have timezones.")
    if horizon <= 0 or start >= end or end + pd.Timedelta(days=horizon) > as_of:
        raise ValueError("Invalid cohort or incomplete follow-up at the snapshot.")
    submitted = pd.to_datetime(requests["Submittal Date"], utc=True, errors="coerce", format="mixed")
    resolved = pd.to_datetime(requests["Resolved At"], utc=True, errors="coerce", format="mixed")
    if submitted.isna().any() or submitted.gt(as_of).any():
        raise ValueError("Missing, invalid, or future submission dates.")
    if (requests["Resolved At"].notna() & resolved.isna()).any():
        raise ValueError("Invalid resolution timestamps.")
    if (resolved.notna() & (resolved.lt(submitted) | resolved.gt(as_of))).any():
        raise ValueError("Resolution timestamp outside submission-to-snapshot interval.")
    higher, lower = wealth_segments(income)
    scope = set(income["zip_code"]) if include_middle else higher | lower
    mask = submitted.ge(start) & submitted.lt(end) & requests["zip_code"].isin(scope)
    cohort = requests.loc[mask].copy()
    cohort["income_group"] = np.select(
        [cohort["zip_code"].isin(lower), cohort["zip_code"].isin(higher)], ["Lower", "Higher"], default="Middle"
    )
    cohort["submission_month"] = submitted[mask].dt.tz_convert(LOCAL_TIME).dt.strftime("%Y-%m")
    cohort["task"] = cohort["service"].fillna("<missing service>") + " / " + cohort["request_type"].fillna("<unspecified type>")
    elapsed = (resolved[mask] - submitted[mask]).dt.total_seconds() / 86400
    cohort["resolved_within_window"] = elapsed.between(0, horizon)
    return cohort


def summarize(cohort, keys):
    return (cohort.groupby(keys + ["income_group"], dropna=False)["resolved_within_window"]
            .agg(requests="size", resolved="sum", rate="mean").reset_index())


def standardize(cohort, keys, min_per_group=1):
    """Give both groups the same pooled task/month distribution on common support.

    Each weight is (n_lower + n_higher) / total requests in retained strata.
    Empty or one-sided strata cannot identify a comparison and are reported as
    excluded. No continuity correction or invented outcome is used.
    """
    counts = summarize(cohort, keys).pivot(index=keys, columns="income_group", values=["requests", "resolved"])
    if not {"Lower", "Higher"}.issubset(counts.columns.get_level_values(1)):
        return {"strata": 0, "requests_lower": 0, "requests_higher": 0,
                "rate_lower": None, "rate_higher": None, "gap_pp": None}
    common = counts.dropna()
    common = common.loc[common["requests"].min(axis=1).ge(min_per_group)]
    if common.empty:
        return {"strata": 0, "requests_lower": 0, "requests_higher": 0,
                "rate_lower": None, "rate_higher": None, "gap_pp": None}
    weights = common["requests"].sum(axis=1)
    weights = weights / weights.sum()
    rates = (common["resolved"] / common["requests"]).mul(weights, axis=0).sum()
    crude = common["resolved"].sum() / common["requests"].sum()
    return {"strata": len(common), "requests_lower": int(common["requests"]["Lower"].sum()),
            "requests_higher": int(common["requests"]["Higher"].sum()),
            "rate_lower": float(rates["Lower"]), "rate_higher": float(rates["Higher"]),
            "gap_pp": float(100 * (rates["Lower"] - rates["Higher"])),
            "crude_rate_lower": float(crude["Lower"]), "crude_rate_higher": float(crude["Higher"]),
            "crude_gap_pp": float(100 * (crude["Lower"] - crude["Higher"]))}


def plot_comparison(result, output_path):
    """Keep population changes visible alongside the standardized comparison."""
    import matplotlib.pyplot as plt

    window = result["windows"]["90"]
    crude = {r["income_group"]: r for r in window["crude"]}
    adjusted = window["task_month_adjusted"]
    labels = [f"All eligible requests\n(n = {sum(r['requests'] for r in crude.values())})",
              f"Comparable task-month subset\n(n = {adjusted['requests_lower'] + adjusted['requests_higher']})",
              "Same subset, adjusted\nto a common task-month mix"]
    lower = [crude["Lower"]["rate"], adjusted["crude_rate_lower"], adjusted["rate_lower"]]
    higher = [crude["Higher"]["rate"], adjusted["crude_rate_higher"], adjusted["rate_higher"]]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    y = np.arange(3)
    for values, offset, color, label in [(lower, -0.13, "#b54a36", "Lower-income ZIPs"),
                                         (higher, 0.13, "#176c61", "Higher-income ZIPs")]:
        ax.barh(y + offset, np.array(values) * 100, height=0.24, color=color, label=label)
        for row, value in zip(y + offset, values):
            ax.text(value * 100 + 1, row, f"{value:.1%}", va="center", fontsize=10)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Recorded resolution within 90 calendar days (%)")
    ax.set_title("Parks & Recreation: recorded resolution within 90 days")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, frameon=False)
    start = pd.Timestamp(result["start_inclusive"]).strftime("%b %Y")
    last_month = (pd.Timestamp(result["end_exclusive"]) - pd.Timedelta(days=1)).strftime("%b %Y")
    gaps = [row["gap_pp"] for row in window["leave_one_zip_out"].values() if row["gap_pp"] is not None]
    fig.text(0.02, 0.025, f"Submitted {start}–{last_month}; {len(result['lower_income_zips'])} lower- and {len(result['higher_income_zips'])} higher-income ZIPs. Exploratory; not causal.\n"
             f"Only shared task-months can be adjusted. Leave-one-ZIP-out gaps: {min(gaps):+.1f} to {max(gaps):+.1f} percentage points (not a confidence interval).", fontsize=9)
    fig.subplots_adjust(left=0.31, right=0.98, top=0.88, bottom=0.3)
    fig.savefig(output_path, dpi=180, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def load_snapshot():
    """Require active inputs to match the same saved source snapshot."""
    snapshot = ROOT / (ROOT / "data/latest_snapshot.txt").read_text().strip()
    manifest = json.loads((snapshot / "manifest.json").read_text())
    for name in ["Ask_Raleigh_Requests.csv", "raleigh_income.csv"]:
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != manifest["files_sha256"][name]:
            raise ValueError(f"Active {name} does not match the snapshot manifest.")
    requests = load_requests(ROOT / "Ask_Raleigh_Requests.csv")
    income = load_income(ROOT / "raleigh_income.csv")
    as_of = min(pd.Timestamp(manifest["retrieved_at_utc"]), pd.to_datetime(manifest["source_editing_info"]["dataLastEditDate"], unit="ms", utc=True))
    return requests, income, as_of, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output" / "cohorts")
    args = parser.parse_args()
    requests, income, as_of, snapshot = load_snapshot()
    # Complete local months after the public portal launch, mature for 90 days.
    start = pd.Timestamp("2025-07-01", tz=LOCAL_TIME)
    maturity = (as_of - pd.Timedelta(days=90)).tz_convert(LOCAL_TIME)
    end = pd.Timestamp(year=maturity.year, month=maturity.month, day=1, tz=LOCAL_TIME)
    higher, lower = wealth_segments(income)
    result = {"snapshot": str(snapshot.relative_to(ROOT)), "as_of_utc": as_of.isoformat(),
              "start_inclusive": start.isoformat(), "end_exclusive": end.isoformat(),
              "lower_income_zips": sorted(lower), "higher_income_zips": sorted(higher),
              "gap_definition": "lower minus higher recorded-resolution rate, percentage points",
              "method": "Pooled request weights on common task-by-submission-month strata; descriptive, no independence-based p-values.",
              "analysis_status": "Exploratory follow-up to an observed parks signal; not a held-out confirmation.",
              "windows": {}}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for horizon in [30, 60, 90]:
        cohort = prepare_cohort(requests, income, as_of, start, end, horizon)
        cohort = cohort.loc[cohort["service_category"].eq("Parks & Recreation")].copy()
        crude = summarize(cohort, [])
        window = {"crude": crude.to_dict("records"),
                  "task_adjusted": standardize(cohort, ["task"]),
                  "month_adjusted": standardize(cohort, ["submission_month"]),
                  "task_month_adjusted": standardize(cohort, ["task", "submission_month"]),
                  "task_month_min5": standardize(cohort, ["task", "submission_month"], 5)}
        window["leave_one_zip_out"] = {z: standardize(cohort.loc[cohort["zip_code"].ne(z)], ["task", "submission_month"])
                                        for z in sorted(higher | lower)}
        result["windows"][str(horizon)] = window
        if horizon == 90:
            for filename, keys in [("by_task", ["task"]), ("by_month", ["submission_month"]),
                                   ("by_task_month", ["task", "submission_month"]), ("by_zip", ["zip_code"])]:
                summarize(cohort, keys).to_csv(args.output_dir / f"{filename}.csv", index=False)
            cohort[["Service Request Number", "zip_code", "income_group", "Service", "Request Type",
                    "Submittal Date", "Resolved At", "Status", "submission_month", "task", "resolved_within_window"]].to_csv(args.output_dir / "parks_90_day_cohort.csv", index=False)
    (args.output_dir / "parks_summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    plot_comparison(result, args.output_dir / "parks_90_day_comparison.png")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
