"""Run the single exploratory comparison fixed in docs/atlas-outcome-plan.md."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cohort_analysis import load_snapshot, prepare_cohort, standardize

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "atlas_outcomes"
GEO_HASH = "798529dc8da3a8b8ee1c6dc8b710f3c72a9e0d2dc6e6687d1830caa75aaefba6"


def estimate(data, groups, minimum=1):
    """Reuse standardization; Higher/Lower refer to vulnerability, not income."""
    keep = groups.isin(["Lower", "Higher"])
    selected = data.loc[keep].copy()
    selected["income_group"] = groups[keep]
    result = standardize(selected, ["task", "submission_month"], minimum)
    counts = selected.groupby("income_group")["resolved_within_window"].agg(["size", "sum", "mean"])
    lower_n = int(counts.loc["Lower", "size"]) if "Lower" in counts.index else 0
    higher_n = int(counts.loc["Higher", "size"]) if "Higher" in counts.index else 0
    return {"eligible_lower": lower_n, "eligible_higher": higher_n,
        "unadjusted_rate_lower": float(counts.loc["Lower", "mean"]) if lower_n else None,
        "unadjusted_rate_higher": float(counts.loc["Higher", "mean"]) if higher_n else None,
        "comparable_lower": result["requests_lower"], "comparable_higher": result["requests_higher"],
        "coverage_lower": result["requests_lower"] / lower_n if lower_n else 0,
        "coverage_higher": result["requests_higher"] / higher_n if higher_n else 0,
        "adjusted_rate_lower": result["rate_lower"], "adjusted_rate_higher": result["rate_higher"],
        "gap_pp_higher_minus_lower": -result["gap_pp"] if result["gap_pp"] is not None else None,
        "shared_task_months": result["strata"]}


def published_groups(data):
    return pd.Series(np.select([data["published_band"].le(2), data["published_band"].ge(4)],
                               ["Lower", "Higher"], default="Middle"), index=data.index)


def poverty_groups(data, lower_cut, higher_cut):
    if not lower_cut < higher_cut:
        raise ValueError("Poverty cutoffs do not define disjoint groups")
    return pd.Series(np.select([data["POV_RATE"].le(lower_cut), data["POV_RATE"].ge(higher_cut)],
                               ["Lower", "Higher"], default="Middle"), index=data.index)


def plot_results(results):
    import matplotlib.pyplot as plt

    order = ["Published bands, pooled", "Published bands, minimum 5 per cell", "2025 Jul-Dec", "2026 Jan-Apr", "Poverty-rate sensitivity"]
    names = ["Published index, pooled", "At least 5 per task/month cell", "July to December 2025", "January to April 2026", "Poverty-rate sensitivity"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), sharey=True)
    for ax, horizon in zip(axes, [90, 180]):
        rows = [next(r for r in results if r["comparison"] == label and r["horizon_days"] == horizon) for label in order]
        gaps = [r["gap_pp_higher_minus_lower"] for r in rows]
        ax.barh(range(len(rows)), gaps, color="#34778a")
        ax.axvline(0, color="#555555", linewidth=0.8)
        ax.axvline(-10, color="#9b3a2d", linestyle="--", linewidth=1)
        for i, (gap, row) in enumerate(zip(gaps, rows)):
            ax.text(gap + (0.2 if gap >= 0 else -0.2), i, f"{gap:+.1f}", va="center", ha="left" if gap >= 0 else "right")
        ax.set_yticks(range(len(rows)), [f"{name}\n(n = {r['comparable_lower'] + r['comparable_higher']})" for name, r in zip(names, rows)])
        ax.set_xlim(-12, 6)
        ax.set_title(f"Recorded resolution within {horizon} days")
        ax.set_xlabel("Higher minus lower vulnerability (percentage points)")
    axes[0].invert_yaxis()
    fig.suptitle("Atlas comparison: modest pooled differences, sensitivity to period and measure")
    fig.text(0.02, 0.025, "Matched task/month subsets in the original parks scope. Dashed line: -10-point follow-up threshold. Point estimates only.\n"
             "Poverty sensitivity uses different groups. Both follow-up windows reuse requests. Physical work completion remains unverified.", fontsize=9)
    fig.subplots_adjust(left=0.25, right=0.98, top=0.85, bottom=0.25, wspace=0.18)
    fig.savefig(OUT / "comparison.png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main():
    requests, income, as_of, request_snapshot = load_snapshot()
    geo_path = ROOT / "output/atlas_pilot/request_geography.csv"
    if hashlib.sha256(geo_path.read_bytes()).hexdigest() != GEO_HASH:
        raise ValueError("Geography file differs from the frozen feasibility result; review the specification first")
    geo = pd.read_csv(geo_path, dtype={"GEOID": "string"})
    geo = geo[["Service Request Number", "GEOID", "published_band", "score_status"]]
    atlas_snapshot = ROOT / (ROOT / "data/atlas_pilot/latest_snapshot.txt").read_text().strip()
    manifest = json.loads((atlas_snapshot / "manifest.json").read_text())
    raw_path = atlas_snapshot / "block_groups.geojson"
    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != manifest["files_sha256"][raw_path.name]:
        raise ValueError("Atlas source hash mismatch")
    props = pd.DataFrame([f["properties"] for f in json.loads(raw_path.read_text())["features"]])
    positive = props.loc[props["B01001e1"].gt(0)]
    lower_cut, higher_cut = positive["POV_RATE"].quantile([0.4, 0.6])
    start = pd.Timestamp("2025-07-01", tz="America/New_York")
    end = pd.Timestamp("2026-05-01", tz="America/New_York")
    results = []
    retained = {}
    for horizon in [90, 180]:
        data = prepare_cohort(requests, income, as_of, start, end, horizon, include_middle=True)
        data = data.loc[data["service_category"].eq("Parks & Recreation")]
        before = len(data)
        data = data.merge(geo, on="Service Request Number", how="left", validate="one_to_one")
        data = data.loc[data["score_status"].eq("usable")].copy()
        data = data.merge(props[["GEOID", "POV_RATE"]], on="GEOID", how="left", validate="many_to_one")
        if before != 773 or len(data) != 761 or data["POV_RATE"].isna().any():
            raise ValueError("Outcome population differs from the frozen pilot")
        retained[horizon] = data
        groups = published_groups(data)
        results.append({"comparison": "Published bands, pooled", "horizon_days": horizon, **estimate(data, groups)})
        results.append({"comparison": "Published bands, minimum 5 per cell", "horizon_days": horizon, **estimate(data, groups, 5)})
        for label, period in [("2025 Jul-Dec", data["submission_month"].lt("2026-01")),
                              ("2026 Jan-Apr", data["submission_month"].ge("2026-01"))]:
            results.append({"comparison": label, "horizon_days": horizon, **estimate(data.loc[period], groups.loc[period])})
        results.append({"comparison": "Poverty-rate sensitivity", "horizon_days": horizon,
                        **estimate(data, poverty_groups(data, lower_cut, higher_cut))})
    data = retained[90]
    groups = published_groups(data)
    contrast = data.loc[groups.isin(["Lower", "Higher"])]
    omission = []
    for area in sorted(contrast["GEOID"].unique()):
        subset = contrast.loc[contrast["GEOID"].ne(area)]
        omission.append({"omitted_geoid": area, **estimate(subset, groups.loc[subset.index])})
    primary = next(r for r in results if r["comparison"] == "Published bands, pooled" and r["horizon_days"] == 90)
    periods = [r for r in results if r["comparison"] in ["2025 Jul-Dec", "2026 Jan-Apr"] and r["horizon_days"] == 90]
    poverty = next(r for r in results if r["comparison"] == "Poverty-rate sensitivity" and r["horizon_days"] == 90)
    coverage_ok = all(r["eligible_lower"] >= 30 and r["eligible_higher"] >= 30 and min(r["coverage_lower"], r["coverage_higher"]) >= .8 for r in periods)
    gaps = [r["gap_pp_higher_minus_lower"] for r in omission]
    follow_up = (coverage_ok and primary["gap_pp_higher_minus_lower"] is not None
                 and primary["gap_pp_higher_minus_lower"] <= -10
                 and all(r["gap_pp_higher_minus_lower"] is not None and r["gap_pp_higher_minus_lower"] < 0 for r in periods + [poverty])
                 and all(g is not None and g < 0 for g in gaps))
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).to_csv(OUT / "comparisons.csv", index=False)
    pd.DataFrame(omission).to_csv(OUT / "leave_one_block_group_out.csv", index=False)
    data[["Service Request Number", "GEOID", "published_band", "POV_RATE", "submission_month", "task", "resolved_within_window"]].to_csv(OUT / "parks_90_day_cohort.csv", index=False)
    summary = {"request_snapshot": str(request_snapshot.relative_to(ROOT)), "atlas_snapshot": str(atlas_snapshot.relative_to(ROOT)),
        "plan_commit": "2266436", "geography_sha256": GEO_HASH, "primary_endpoint_days": 90,
        "gap_definition": "Higher vulnerability minus lower vulnerability, percentage points",
        "usable_requests": 761, "primary_contrast_requests": len(contrast), "middle_band_excluded": int(groups.eq("Middle").sum()),
        "poverty_cutoffs_percent": {"lower_at_or_below": float(lower_cut), "higher_at_or_above": float(higher_cut)},
        "primary": primary, "period_coverage_requirements_passed": coverage_ok,
        "leave_one_block_group_out": {"areas": len(omission), "minimum_gap_pp": min(gaps), "maximum_gap_pp": max(gaps),
                                      "interpretation": "Sensitivity range, not a confidence interval; common support and weights re-estimated"},
        "additional_follow_up_lead": bool(follow_up), "comparisons": results,
        "interpretation": "Exploratory point estimates only. No causal estimate or calibrated significance test. Physical completion and city/service jurisdiction remain unverified."}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    plot_results(results)
    print(pd.DataFrame(results).to_string(index=False))
    print(json.dumps({k: v for k, v in summary.items() if k not in ["primary", "comparisons"]}, indent=2))


if __name__ == "__main__":
    main()
