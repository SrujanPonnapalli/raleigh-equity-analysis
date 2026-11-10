"""Reproduce presentation-only ACS context from the saved Census source rows.

Run python3 data/presentation_context/summarize.py. This does not modify the
service-request analysis, geographic joins, or investigation thresholds.
"""

import csv
import hashlib
import json
import math
from pathlib import Path

FOLDER = Path(__file__).resolve().parent / "acs2024"
GEOGRAPHIES = {"27610": "860Z200US27610", "Raleigh": "1600000US3755000", "Wake County": "0500000US37183"}


def subset_percent(numerator, denominator, numerator_moe, denominator_moe):
    """ACS 90% proportion MOE; special Census codes are not numeric errors."""
    if denominator <= 0 or not 0 <= numerator <= denominator:
        raise ValueError("Invalid subset numerator or denominator")
    proportion = numerator / denominator
    result = {"percent": 100 * proportion, "numerator": numerator, "denominator": denominator,
              "numerator_moe_90": numerator_moe, "denominator_moe_90": denominator_moe}
    if numerator_moe < 0 or denominator_moe < 0:
        return {**result, "moe_pp_90": None, "moe_method": "not computed: source uses special MOE codes"}
    radicand = numerator_moe ** 2 - proportion ** 2 * denominator_moe ** 2
    fallback = radicand < 0
    if fallback:
        radicand = numerator_moe ** 2 + proportion ** 2 * denominator_moe ** 2
    return {**result, "moe_pp_90": 100 * math.sqrt(radicand) / denominator,
            "moe_method": "ratio fallback" if fallback else "subset proportion"}


def summarize():
    manifest = json.loads((FOLDER / "summary.json").read_text())
    tables = {}
    for table in ["B19013", "B02001", "B03003", "B17001"]:
        path = FOLDER / f"{table.lower()}-selected.csv"
        rows = list(csv.DictReader(path.open()))
        if len(rows) != 3 or {r["GEO_ID"] for r in rows} != set(GEOGRAPHIES.values()):
            raise ValueError(f"Unexpected geography coverage in {table}")
        tables[table] = {r["context_name"]: r for r in rows}
        manifest["sources"][table]["selected_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    def value(table, geography, column, kind="E"):
        return int(tables[table][geography][f"{table}_{kind}{column:03d}"])

    def percentage(table, geography, numerator, denominator):
        return subset_percent(value(table, geography, numerator), value(table, geography, denominator),
                              value(table, geography, numerator, "M"), value(table, geography, denominator, "M"))

    result = {}
    for name in GEOGRAPHIES:
        population_moe = value("B02001", name, 1, "M")
        result[name] = {"median_household_income": value("B19013", name, 1),
                        "income_moe_90": value("B19013", name, 1, "M"),
                        "population": value("B02001", name, 1),
                        "population_moe_90": population_moe if population_moe >= 0 else None,
                        "black_alone": percentage("B02001", name, 3, 1),
                        "hispanic_any_race": percentage("B03003", name, 3, 1),
                        "poverty": percentage("B17001", name, 2, 1)}
    manifest["summary"] = result
    (FOLDER / "summary.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(summarize(), indent=2))
