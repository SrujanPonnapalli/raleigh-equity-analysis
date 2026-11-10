"""Download and validate public source snapshots without changing analysis rules.

Run: python3 refresh_data.py
Raw snapshots and provenance are retained in data/snapshots/<UTC timestamp>/.
"""

import csv
import hashlib
import io
import json
import shutil
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ITEM = "https://www.arcgis.com/sharing/rest/content/items/9ce6bd1524bc445d9fe7c852ee73b4fb"
LAYER = "https://services.arcgis.com/v400IkDOw1ad7Yad/arcgis/rest/services/Ask_Raleigh_Requests/FeatureServer/0"
INCOME = "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b19013.dat"


def get_json(url, **params):
    with urllib.request.urlopen(url + "?" + urllib.parse.urlencode({"f": "json", **params}), timeout=120) as response:
        data = json.load(response)
    if "error" in data:
        raise ValueError(f"Source error: {data['error']}")
    return data


def request_row(feature, fields):
    """Preserve source aliases; serialize epoch dates explicitly in UTC."""
    values = feature["attributes"]
    row = {}
    for field in fields:
        value = values.get(field["name"])
        if field["type"] == "esriFieldTypeDate" and value is not None:
            value = datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
        row[field["alias"]] = value
    geometry = feature.get("geometry") or {}
    row.update(x=geometry.get("x"), y=geometry.get("y"))
    return row


def income_rows(text, zips):
    """Keep estimates and 90% margins of error; missing estimates stay missing."""
    rows = []
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        geo = row["GEO_ID"]
        if not geo.startswith("860Z200US") or geo[-5:] not in zips:
            continue
        estimate, moe = row["B19013_E001"], row["B19013_M001"]
        rows.append({"Zip Code": geo[-5:], "Median Income": int(estimate) if estimate.lstrip("-").isdigit() and int(estimate) > 0 else "",
                     "Margin of Error": int(moe) if moe.isdigit() else "",
                     "ACS Period": "2020-2024", "Dollar Year": 2024, "Geography": "2020 ZCTA"})
    if len(rows) != len({r["Zip Code"] for r in rows}):
        raise ValueError("Duplicate Census ZCTAs")
    return sorted(rows, key=lambda r: r["Zip Code"])


def write_csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def refresh():
    started = datetime.now(timezone.utc)
    snapshot = ROOT / "data" / "snapshots" / started.strftime("%Y%m%dT%H%M%SZ")
    snapshot.mkdir(parents=True)
    item = get_json(ITEM)
    metadata = get_json(LAYER)
    (snapshot / "arcgis_item.json").write_text(json.dumps(item, indent=2))
    (snapshot / "arcgis_layer.json").write_text(json.dumps(metadata, indent=2))
    if item.get("owner") != "RaleighGIS" or item.get("url") + "/0" != LAYER:
        raise ValueError("Unexpected source identity")
    oid = metadata["objectIdField"]
    ids = sorted(get_json(LAYER + "/query", where="1=1", returnIdsOnly="true")["objectIds"])
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Empty or duplicate source object IDs")
    features = []
    # Small ID batches stay within the public gateway's URL length limit.
    batch_size = min(100, metadata["maxRecordCount"])
    for offset in range(0, len(ids), batch_size):
        batch_ids = ids[offset:offset + batch_size]
        result = get_json(LAYER + "/query", objectIds=",".join(map(str, batch_ids)), outFields="*", returnGeometry="true", outSR=4326)
        batch = result["features"]
        if result.get("exceededTransferLimit") or {f["attributes"][oid] for f in batch} != set(batch_ids) or len(batch) != len(batch_ids):
            raise ValueError("Incomplete ArcGIS batch; active CSV was not replaced")
        features.extend(batch)
        print(f"Downloaded {len(features):,}/{len(ids):,} requests", flush=True)
    after = get_json(LAYER)
    after_ids = sorted(get_json(LAYER + "/query", where="1=1", returnIdsOnly="true")["objectIds"])
    if metadata.get("editingInfo") != after.get("editingInfo") or ids != after_ids:
        raise ValueError("Source changed during download; rerun for a consistent snapshot")
    features.sort(key=lambda f: f["attributes"][oid])
    (snapshot / "requests_raw.json").write_text(json.dumps({"spatialReference": {"wkid": 4326}, "features": features}))
    rows = [request_row(f, metadata["fields"]) for f in features]
    numbers = [r["Service Request Number"] for r in rows]
    if any(not n for n in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError("Missing or duplicate request numbers")
    write_csv(snapshot / "Ask_Raleigh_Requests.csv", rows, list(rows[0]))
    original = ROOT / "data" / "original"
    original.mkdir(exist_ok=True)
    if not (original / "raleigh_income.csv").exists():
        shutil.copyfile(ROOT / "raleigh_income.csv", original / "raleigh_income.csv")
    with (original / "raleigh_income.csv").open() as handle:
        scope = {r["Zip Code"] for r in csv.DictReader(handle)}
    request_zips = {str(r["ZIP Code"]).strip() for r in rows if r["ZIP Code"]}
    with urllib.request.urlopen(INCOME, timeout=120) as response:
        income_bytes = response.read()
    (snapshot / "acsdt5y2024-b19013.dat").write_bytes(income_bytes)
    incomes = income_rows(income_bytes.decode("utf-8-sig"), request_zips | scope)
    scoped = [r for r in incomes if r["Zip Code"] in scope]
    if {r["Zip Code"] for r in scoped} != scope or any(not r["Median Income"] for r in scoped):
        raise ValueError("Incomplete income coverage for existing analysis scope")
    columns = list(scoped[0])
    write_csv(snapshot / "income_all_request_zctas.csv", incomes, columns)
    write_csv(snapshot / "raleigh_income.csv", scoped, columns)
    submitted = [r["Submittal Date"] for r in rows if r["Submittal Date"]]
    manifest = {
        "retrieved_at_utc": started.isoformat(), "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "requests_source": LAYER, "requests_item": ITEM, "income_source": INCOME,
        "income_period": "2020-2024", "income_dollar_year": 2024,
        "income_moe_confidence_percent": 90, "analysis_zips": sorted(scope),
        "requests_count": len(rows), "submitted_min_utc": min(submitted), "submitted_max_utc": max(submitted),
        "status_counts": dict(Counter(r["Status"] for r in rows)),
        "missing_resolution_hours": sum(r["Hours to Resolve"] is None for r in rows),
        "negative_resolution_hours": sum(r["Hours to Resolve"] is not None and r["Hours to Resolve"] < 0 for r in rows),
        "missing_coordinates": sum(r["x"] is None or r["y"] is None for r in rows),
        "requests_outside_analysis_zip_scope": sum(str(r["ZIP Code"]).strip() not in scope for r in rows),
        "request_zips_without_census_match": sorted(request_zips - {r["Zip Code"] for r in incomes}),
        "source_editing_info": metadata.get("editingInfo"),
        "files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.iterdir() if p.is_file()},
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # Validate both sources before publishing either input; each replacement is atomic.
    for name in ("Ask_Raleigh_Requests.csv", "raleigh_income.csv"):
        temp = ROOT / (name + ".tmp")
        shutil.copyfile(snapshot / name, temp)
        temp.replace(ROOT / name)
    (ROOT / "data" / "latest_snapshot.txt").write_text(str(snapshot.relative_to(ROOT)) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    refresh()
