"""Download the published Wake index and assess spatial linkage, without outcomes.

Install requirements-atlas.txt. Run once with --download, then run offline.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from shapely import Point, STRtree
from shapely.geometry import shape

from data_pipeline import _normalize_zip
from refresh_data import get_json

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "atlas_pilot"
OUT = ROOT / "output" / "atlas_pilot"
ORG = "a7CWfuGP5ZnLYE7I"
MAP_ID = "443b36c6f1e4428bad45db641060288e"
ITEM_ID = "eb973c734de14652bcadd9af211c751d"
LAYER = f"https://services1.arcgis.com/{ORG}/arcgis/rest/services/Vulnerability_Assessment_Index_Series_2024/FeatureServer/0"
ITEMS = "https://www.arcgis.com/sharing/rest/content/items/"
RANKS = ["AGE_DPND_RANK", "POV_RANK", "NO_DIP_RANK", "VAC_RANK", "UNEMP_RANK"]


def download():
    started = datetime.now(timezone.utc)
    target = DATA / started.strftime("%Y%m%dT%H%M%SZ")
    target.mkdir(parents=True)
    organization = get_json(f"https://www.arcgis.com/sharing/rest/portals/{ORG}")
    item = get_json(ITEMS + ITEM_ID)
    map_item = get_json(ITEMS + MAP_ID)
    map_data = get_json(ITEMS + MAP_ID + "/data")
    metadata = get_json(LAYER)
    if organization.get("name") != "Wake County" or item.get("orgId") != ORG or map_item.get("orgId") != ORG:
        raise ValueError("Unexpected publisher organization")
    if not any(l.get("url") == LAYER and l.get("itemId") == ITEM_ID for l in map_data["operationalLayers"]):
        raise ValueError("Published map does not reference the selected index layer")
    ids = sorted(get_json(LAYER + "/query", where="1=1", returnIdsOnly="true")["objectIds"])
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Empty or duplicate source IDs")
    features = []
    for offset in range(0, len(ids), 100):
        batch = ids[offset:offset + 100]
        result = get_json(LAYER + "/query", objectIds=",".join(map(str, batch)), outFields="*", outSR=4326, returnGeometry="true", f="geojson")
        returned = result.get("features", [])
        if len(returned) != len(batch) or {f["properties"]["OBJECTID"] for f in returned} != set(batch):
            raise ValueError("Incomplete polygon batch")
        features.extend(returned)
    after = get_json(LAYER)
    after_ids = sorted(get_json(LAYER + "/query", where="1=1", returnIdsOnly="true")["objectIds"])
    if metadata.get("editingInfo") != after.get("editingInfo") or ids != after_ids:
        raise ValueError("Source changed during polygon download")
    files = {"organization.json": organization, "item.json": item, "map_item.json": map_item,
             "map_data.json": map_data, "layer.json": metadata,
             "block_groups.geojson": {"type": "FeatureCollection", "features": features}}
    for name, content in files.items():
        (target / name).write_text(json.dumps(content, ensure_ascii=False) + "\n")
    manifest = {"retrieved_at_utc": started.isoformat(), "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "layer": LAYER, "map_id": MAP_ID, "item_id": ITEM_ID, "feature_count": len(features),
                "requested_output_crs": "EPSG:4326", "object_ids": ids,
                "files_sha256": {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in files}}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (DATA / "latest_snapshot.txt").write_text(str(target.relative_to(ROOT)) + "\n")
    print(f"Saved {len(features)} county polygons to {target.relative_to(ROOT)}", flush=True)


def build_index(features):
    """Reject broken geometry or keys before linking any requests."""
    props = pd.DataFrame([f["properties"] for f in features])
    ids = props["GEOID"].astype("string")
    if ids.isna().any() or ids.duplicated().any() or not ids.str.fullmatch(r"37183\d{7}").all():
        raise ValueError("Expected unique Wake County block-group GEOIDs")
    geometries = [shape(f["geometry"]) for f in features]
    if any(g.is_empty or not g.is_valid or g.geom_type not in ["Polygon", "MultiPolygon"] for g in geometries):
        raise ValueError("Invalid, empty, or nonpolygon source geometry")
    if any(not (-180 <= g.bounds[0] <= g.bounds[2] <= 180 and -90 <= g.bounds[1] <= g.bounds[3] <= 90) for g in geometries):
        raise ValueError("Polygon coordinates are not valid longitude/latitude")
    return props, geometries, STRtree(geometries)


def locate(longitude, latitude, geometries, tree):
    """One strict interior match only; no nearest-neighbor or ZIP imputation."""
    if pd.isna(longitude) or pd.isna(latitude):
        return None, "missing_coordinates"
    if not np.isfinite(longitude) or not np.isfinite(latitude) or not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None, "invalid_coordinates"
    point = Point(longitude, latitude)
    intersects = tree.query(point, predicate="intersects")
    inside = [int(i) for i in intersects if geometries[int(i)].contains(point)]
    if len(intersects) > 1:
        return None, "multiple_or_shared_boundary"
    if len(inside) == 1:
        return inside[0], "matched"
    return None, "boundary" if len(intersects) else "outside_atlas"


def published_band(score, renderer):
    if pd.isna(score) or not np.isfinite(score) or score < renderer["minValue"]:
        return None
    for i, band in enumerate(renderer["classBreakInfos"], start=1):
        if score <= band["classMaxValue"]:
            return i
    return None


def verify_server():
    """Cross-check one deterministic pilot point per band and one outside point."""
    snapshot = ROOT / (DATA / "latest_snapshot.txt").read_text().strip()
    frozen = json.loads((snapshot / "layer.json").read_text())
    if get_json(LAYER).get("editingInfo") != frozen.get("editingInfo"):
        raise ValueError("Server changed since the saved Atlas snapshot")
    linked = pd.read_csv(OUT / "request_geography.csv", dtype={"GEOID": "string"})
    sample = linked.loc[linked["pilot_cohort"] & linked["score_status"].eq("usable")].sort_values("Service Request Number").groupby("published_band").head(1)
    outside = linked.loc[linked["join_status"].eq("outside_atlas")].sort_values("Service Request Number").head(1)
    checks = []
    for _, row in pd.concat([sample, outside]).iterrows():
        point = json.dumps({"x": row["x"], "y": row["y"], "spatialReference": {"wkid": 4326}})
        result = get_json(LAYER + "/query", geometry=point, geometryType="esriGeometryPoint", inSR=4326,
                          spatialRel="esriSpatialRelIntersects", outFields="GEOID", returnGeometry="false")
        found = sorted(f["attributes"]["GEOID"] for f in result["features"])
        expected = [row["GEOID"]] if row["join_status"] == "matched" else []
        if found != expected:
            raise AssertionError(f"Server spatial query disagrees for {row['Service Request Number']}")
        checks.append({"request_id": row["Service Request Number"], "expected_geoids": expected,
                       "server_geoids": found, "agreement": True})
    (OUT / "server_crosscheck.json").write_text(json.dumps({"verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection": "First request ID per published band in the pilot cohort, plus first outside-Atlas request ID",
        "scope": "Six sampled points; this is not exhaustive geographic verification", "checks": checks}, indent=2) + "\n")
    print(f"Server cross-check passed for {len(checks)} sampled points.")


def plot_feasibility(usable):
    import matplotlib.pyplot as plt

    if usable.empty:
        (OUT / "feasibility.png").unlink(missing_ok=True)
        return
    bands = usable.groupby("published_band").size().reindex(range(1, 6), fill_value=0)
    area_counts = usable.groupby("GEOID").size()
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    axes[0].bar(range(1, 6), bands, color="#34778a")
    for i, n in enumerate(bands, start=1):
        axes[0].text(i, n + 3, str(n), ha="center")
    axes[0].set_xticks(range(1, 6), ["1\nLower", "2", "3", "4", "5\nHigher"])
    axes[0].set_xlabel("Published county vulnerability band")
    axes[0].set_ylabel("Matched parks requests")
    axes[0].set_ylim(0, max(1, bands.max()) * 1.15)
    axes[1].hist(area_counts, bins=np.arange(0.5, area_counts.max() + 1.5), color="#34778a", edgecolor="white")
    axes[1].set_xlabel("Requests per represented block group")
    axes[1].set_ylabel("Block groups")
    fig.suptitle("Atlas pilot: usable matches across bands, sparse data within small areas")
    fig.text(0.02, 0.025, "Original 15-ZIP parks scope, July 2025 to April 2026. Counts only; no resolution outcomes examined.", fontsize=9)
    fig.subplots_adjust(bottom=0.24, top=0.85, wspace=0.3)
    fig.savefig(OUT / "feasibility.png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def run():
    snapshot = ROOT / (DATA / "latest_snapshot.txt").read_text().strip()
    manifest = json.loads((snapshot / "manifest.json").read_text())
    if manifest["requested_output_crs"] != "EPSG:4326":
        raise ValueError("Expected WGS84 polygons")
    for name, digest in manifest["files_sha256"].items():
        if hashlib.sha256((snapshot / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Atlas snapshot hash mismatch: {name}")
    features = json.loads((snapshot / "block_groups.geojson").read_text())["features"]
    if len(features) != manifest["feature_count"]:
        raise ValueError("Atlas feature count does not match manifest")
    props, geometries, tree = build_index(features)
    renderer = json.loads((snapshot / "layer.json").read_text())["drawingInfo"]["renderer"]
    if renderer["field"] != "TOTAL_SCORE":
        raise ValueError("Published legend does not classify TOTAL_SCORE")
    request_snapshot = ROOT / (ROOT / "data/latest_snapshot.txt").read_text().strip()
    request_manifest = json.loads((request_snapshot / "manifest.json").read_text())
    request_path = ROOT / "Ask_Raleigh_Requests.csv"
    if hashlib.sha256(request_path.read_bytes()).hexdigest() != request_manifest["files_sha256"][request_path.name]:
        raise ValueError("Active requests do not match the saved snapshot")
    # Outcome columns are intentionally not read in the feasibility phase.
    columns = ["Service Request Number", "ZIP Code", "Service Category", "Service", "Request Type", "Submittal Date", "x", "y"]
    requests = pd.read_csv(request_path, usecols=columns, dtype={"ZIP Code": "string"})
    if requests["Service Request Number"].isna().any() or requests["Service Request Number"].duplicated().any():
        raise ValueError("Missing or duplicate request identities")
    requests["zip_code"] = _normalize_zip(requests["ZIP Code"])
    for column in ["Service Category", "Service", "Request Type"]:
        requests[column] = requests[column].astype("string").str.strip().replace("", pd.NA)
    dates = pd.to_datetime(requests["Submittal Date"], utc=True, format="mixed", errors="raise")
    requests["submission_month"] = dates.dt.tz_convert("America/New_York").dt.strftime("%Y-%m")
    requests["pilot_cohort"] = (requests["Service Category"].eq("Parks & Recreation")
        & requests["zip_code"].isin(request_manifest["analysis_zips"])
        & dates.ge(pd.Timestamp("2025-07-01", tz="America/New_York"))
        & dates.lt(pd.Timestamp("2026-05-01", tz="America/New_York")))
    matches = []
    for row in requests.itertuples(index=False):
        longitude = pd.to_numeric(row.x, errors="coerce")
        latitude = pd.to_numeric(row.y, errors="coerce")
        index, status = locate(longitude, latitude, geometries, tree)
        record = {"join_status": status, "GEOID": None, "population": None, "TOTAL_SCORE": None, "published_band": None, "score_status": "not_matched"}
        if index is not None:
            area = props.iloc[index]
            score, population = area["TOTAL_SCORE"], area["B01001e1"]
            band = published_band(score, renderer)
            record.update(GEOID=area["GEOID"], population=population, TOTAL_SCORE=score, published_band=band)
            record["score_status"] = "missing_population" if pd.isna(population) else "zero_population" if population <= 0 else "invalid_score" if band is None else "usable"
        matches.append(record)
    linked = pd.concat([requests.reset_index(drop=True), pd.DataFrame(matches)], axis=1)
    if len(linked) != len(requests) or linked["Service Request Number"].duplicated().any():
        raise AssertionError("Spatial join expanded the request population")
    OUT.mkdir(parents=True, exist_ok=True)
    linked.to_csv(OUT / "request_geography.csv", index=False)
    linked.groupby(["pilot_cohort", "join_status", "score_status"], dropna=False).size().rename("requests").reset_index().to_csv(OUT / "join_accounting.csv", index=False)
    cohort = linked.loc[linked["pilot_cohort"]].copy()
    if cohort.empty:
        raise ValueError("No requests in the fixed pilot cohort")
    cohort["usable_match"] = cohort["score_status"].eq("usable")
    for column in ["zip_code", "submission_month", "Service"]:
        cohort.groupby(column, dropna=False)["usable_match"].agg(requests="size", usable="sum", coverage="mean").to_csv(OUT / f"coverage_by_{column.lower()}.csv")
    usable = cohort.loc[cohort["usable_match"]].copy()
    usable.groupby("published_band").agg(requests=("GEOID", "size"), block_groups=("GEOID", "nunique")).to_csv(OUT / "band_counts.csv")
    usable.groupby("GEOID").size().rename("requests").to_csv(OUT / "block_group_counts.csv")
    usable["period"] = np.where(usable["submission_month"].lt("2026-01"), "2025 Jul-Dec", "2026 Jan-Apr")
    usable["task"] = usable["Service"].fillna("<missing service>") + " / " + usable["Request Type"].fillna("<unspecified type>")
    usable.groupby(["period", "published_band", "task", "submission_month"]).size().rename("requests").reset_index().to_csv(OUT / "task_month_counts.csv", index=False)
    pooled = usable.loc[usable["published_band"].ne(3)].copy()
    pooled["vulnerability_group"] = np.where(pooled["published_band"].le(2), "Lower bands 1-2", "Higher bands 4-5")
    pooled.groupby(["period", "vulnerability_group"]).agg(requests=("GEOID", "size"), block_groups=("GEOID", "nunique")).to_csv(OUT / "pooled_group_counts.csv")
    support = []
    for period, subset in pooled.groupby("period"):
        counts = subset.groupby(["task", "submission_month", "vulnerability_group"]).size().unstack("vulnerability_group", fill_value=0)
        counts = counts.reindex(columns=["Lower bands 1-2", "Higher bands 4-5"], fill_value=0)
        for minimum in [1, 5]:
            shared = counts.loc[counts.min(axis=1).ge(minimum)]
            for group in counts:
                retained, total = int(shared[group].sum()), int(counts[group].sum())
                support.append({"period": period, "minimum_each_group_per_task_month": minimum, "group": group,
                                "requests": total, "comparable_requests": retained, "coverage": retained / total if total else None, "shared_task_months": len(shared)})
    pd.DataFrame(support).to_csv(OUT / "pooled_task_month_support.csv", index=False)
    sums_match = props[RANKS].sum(axis=1).eq(props["TOTAL_CALC"])
    index_fields = RANKS + ["B01001e1", "TOTAL_CALC", "TOTAL_SCORE", "POV_RATE", "UNEMP_RATE", "PRCNT_AGE_DPND", "VAC_RATE", "PRCNT_No_DIP"]
    props[index_fields].agg(["min", "max", "count"]).T.to_csv(OUT / "index_field_profile.csv")
    tie_rows = []
    for rate, rank in [("POV_RATE", "POV_RANK"), ("UNEMP_RATE", "UNEMP_RANK"), ("PRCNT_AGE_DPND", "AGE_DPND_RANK"), ("VAC_RATE", "VAC_RANK"), ("PRCNT_No_DIP", "NO_DIP_RANK")]:
        zeros = props.loc[props[rate].eq(0), rank]
        tie_rows.append({"indicator": rate, "zero_value_block_groups": len(zeros), "minimum_zero_value_rank": int(zeros.min()) if len(zeros) else None, "maximum_zero_value_rank": int(zeros.max()) if len(zeros) else None})
    pd.DataFrame(tie_rows).to_csv(OUT / "equal_value_rank_audit.csv", index=False)
    summary = {"request_snapshot": str(request_snapshot.relative_to(ROOT)), "atlas_snapshot": str(snapshot.relative_to(ROOT)),
        "outcomes_examined": False, "source_polygons": len(props), "unique_geoids": int(props["GEOID"].nunique()),
        "zero_population_polygons": int(props["B01001e1"].le(0).sum()), "population_under_100_polygons": int(props["B01001e1"].lt(100).sum()),
        "rank_sum_matches_total_calc": int(sums_match.sum()), "published_score_range": [float(props["TOTAL_SCORE"].min()), float(props["TOTAL_SCORE"].max())],
        "source_fields_with_nulls": props[index_fields].isna().sum().loc[lambda x: x.gt(0)].to_dict(),
        "tied_total_calc_rows_beyond_unique": int(len(props) - props["TOTAL_CALC"].nunique()),
        "score_increases_with_total_calc": bool(props.sort_values("TOTAL_SCORE")["TOTAL_CALC"].is_monotonic_increasing),
        "all_request_join_status": linked["join_status"].value_counts().to_dict(),
        "all_request_score_status": linked["score_status"].value_counts().to_dict(),
        "pilot_requests": len(cohort), "pilot_join_status": cohort["join_status"].value_counts().to_dict(),
        "pilot_score_status": cohort["score_status"].value_counts().to_dict(),
        "pilot_usable_coverage": float(cohort["usable_match"].mean()),
        "coverage_gate_passed": bool(cohort["usable_match"].mean() >= 0.95),
        "pilot_distinct_block_groups": int(usable["GEOID"].nunique()),
        "median_requests_per_block_group": float(usable.groupby("GEOID").size().median()),
        "max_requests_per_block_group": int(usable.groupby("GEOID").size().max()),
        "matched_requests_in_population_under_100": int(usable["population"].lt(100).sum()),
        "legend_breaks": [b["classMaxValue"] for b in renderer["classBreakInfos"]],
        "scope_limit": "County block groups and request ZIP scope; city limits and historical service jurisdiction have not been established."}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    plot_feasibility(usable)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Save a new public Atlas snapshot before linking")
    parser.add_argument("--verify-server", action="store_true", help="Cross-check six sampled locations against the public spatial query")
    args = parser.parse_args()
    if args.download:
        download()
    run()
    if args.verify_server:
        verify_server()
