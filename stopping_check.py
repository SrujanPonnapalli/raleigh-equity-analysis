"""Apply the fixed parks investigation screen documented in data/README.md.

Run python stopping_check.py. Thresholds were committed before the screen ran.
The output identifies recorded-resolution patterns, not verified repair failures.
"""

import json
from pathlib import Path

import pandas as pd

from cohort_analysis import LOCAL_TIME, load_snapshot, prepare_cohort, standardize

ROOT = Path(__file__).resolve().parent
PERIODS = [("2025 Jul-Dec", "2025-07-01", "2026-01-01"),
           ("2026 Jan-Apr", "2026-01-01", "2026-05-01")]
MIN_REQUESTS = 30
MIN_COVERAGE = 0.8
MIN_SHORTFALL_PP = 10
MIN_REFERENCE_PER_STRATUM = 5


def compare_zip(cohort, zip_code):
    """Compare a focal ZIP with other scope ZIPs on shared task/month support."""
    data = cohort.copy()
    # standardize's group labels are computational labels only: Lower = focal,
    # Higher = reference here. Income is not used to select or compare locations.
    data["income_group"] = data["zip_code"].eq(zip_code).map({True: "Lower", False: "Higher"})
    focal_n = int(data["zip_code"].eq(zip_code).sum())
    counts = data.groupby(["task", "submission_month", "income_group"]).size().unstack("income_group", fill_value=0)
    if "Higher" not in counts or "Lower" not in counts:
        return {"focal_requests": focal_n, "comparable_focal_requests": 0, "coverage": 0.0,
                "adjusted_focal_rate": None, "adjusted_reference_rate": None, "gap_pp": None}
    supported = counts.index[counts["Lower"].ge(1) & counts["Higher"].ge(MIN_REFERENCE_PER_STRATUM)]
    eligible = pd.MultiIndex.from_frame(data[["task", "submission_month"]]).isin(supported)
    result = standardize(data.loc[eligible], ["task", "submission_month"])
    return {"focal_requests": focal_n, "comparable_focal_requests": result["requests_lower"],
            "coverage": result["requests_lower"] / focal_n if focal_n else 0.0,
            "adjusted_focal_rate": result["rate_lower"], "adjusted_reference_rate": result["rate_higher"],
            "gap_pp": result["gap_pp"]}


def classify(rows):
    """A flag requires every prespecified period/window; no choosing the best one."""
    expected = {(p[0], h) for p in PERIODS for h in [90, 180]}
    if len(rows) != len(expected) or {(r["period"], r["horizon_days"]) for r in rows} != expected:
        return "insufficient comparable data"
    if any(r["focal_requests"] < MIN_REQUESTS or r["coverage"] < MIN_COVERAGE or r["gap_pp"] is None for r in rows):
        return "insufficient comparable data"
    if all(r["gap_pp"] <= -MIN_SHORTFALL_PP for r in rows):
        return "investigation flag"
    return "no persistent shortfall under this rule"


def plot_flag(results, decisions, output_path):
    """Show all four required comparisons for any ZIP meeting the fixed gate."""
    import matplotlib.pyplot as plt

    flagged = [d["zip_code"] for d in decisions if d["decision"] == "investigation flag"]
    if not flagged:
        output_path.unlink(missing_ok=True)
        return
    fig, axes = plt.subplots(len(flagged), 1, figsize=(9, 4 * len(flagged)), squeeze=False)
    for ax, z in zip(axes.flat, flagged):
        data = results.loc[results["zip_code"].eq(z)]
        labels = [f"{r.period}\n{r.horizon_days}-day window" for r in data.itertuples()]
        ax.barh(labels, data["gap_pp"], color="#2e6d80")
        ax.axvline(-MIN_SHORTFALL_PP, linestyle="--", color="#9b3a2d", label="Investigation threshold")
        for i, gap in enumerate(data["gap_pp"]):
            ax.text(gap - 0.3, i, f"{gap:.1f}", ha="right", va="center")
        ax.set_xlim(min(-20, data["gap_pp"].min() - 4), 0)
        ax.invert_yaxis()
        ax.set_title(f"ZIP {z}: recorded resolution shortfall persists across both periods")
        ax.set_xlabel("Adjusted rate difference versus the other 14 analysis ZIPs (percentage points)")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), frameon=False)
    inadequate = sum(d["decision"] == "insufficient comparable data" for d in decisions)
    fig.text(0.02, 0.025, f"Screened {len(decisions)} ZIPs; {len(flagged)} flagged, {inadequate} had insufficient comparable data. Exploratory investigation screen.\n"
             "Within recorded task and submission month; not a causal effect or verification of physical work. Windows share requests.", fontsize=9)
    fig.subplots_adjust(left=0.21, right=0.98, top=0.86, bottom=0.34, hspace=0.65)
    fig.savefig(output_path, dpi=180, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def main():
    requests, income, as_of, snapshot = load_snapshot()
    out = ROOT / "output" / "stopping_check"
    out.mkdir(parents=True, exist_ok=True)
    all_rows = []
    cohort_ids = {}
    for label, start, end in PERIODS:
        start, end = [pd.Timestamp(d, tz=LOCAL_TIME) for d in (start, end)]
        for horizon in [90, 180]:
            cohort = prepare_cohort(requests, income, as_of, start, end, horizon, include_middle=True)
            cohort = cohort.loc[cohort["service_category"].eq("Parks & Recreation")].copy()
            cohort_ids[f"{label}/{horizon}"] = sorted(cohort["Service Request Number"].tolist())
            for z in sorted(income["zip_code"]):
                all_rows.append({"zip_code": z, "period": label, "horizon_days": horizon, **compare_zip(cohort, z)})
    results = pd.DataFrame(all_rows)
    decisions = [{"zip_code": z, "decision": classify([r for r in all_rows if r["zip_code"] == z])}
                 for z in sorted(income["zip_code"])]
    results.to_csv(out / "zip_period_windows.csv", index=False)
    pd.DataFrame(decisions).to_csv(out / "decisions.csv", index=False)
    plot_flag(results, decisions, out / "investigation_flags.png")
    # Confirm the endpoint changes, not the eligible submission population.
    for label, _, _ in PERIODS:
        if cohort_ids[f"{label}/90"] != cohort_ids[f"{label}/180"]:
            raise AssertionError("Follow-up windows used different submission cohorts")
    result = {"snapshot": str(snapshot.relative_to(ROOT)), "as_of_utc": as_of.isoformat(),
              "policy_commit": "196fb9e", "scope": "Parks & Recreation requests in the original 15 income ZIPs",
              "comparison": "Each ZIP versus the other 14 scope ZIPs; common pooled task/month weights",
              "thresholds": {"min_requests_per_period": MIN_REQUESTS, "min_focal_coverage": MIN_COVERAGE,
                             "min_shortfall_pp": MIN_SHORTFALL_PP, "min_reference_requests_per_stratum": MIN_REFERENCE_PER_STRATUM,
                             "required_windows_days": [90, 180], "required_periods": [p[0] for p in PERIODS]},
              "decisions": decisions, "flagged_zips": [d["zip_code"] for d in decisions if d["decision"] == "investigation flag"],
              "interpretation": "Exploratory screening policy, not a significance test, causal estimate, or verified physical-work backlog.",
              "cohort_request_ids": cohort_ids}
    (out / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(pd.DataFrame(decisions).to_string(index=False))
    print(results[["zip_code", "period", "horizon_days", "focal_requests", "coverage", "gap_pp"]].to_string(index=False))


if __name__ == "__main__":
    main()
