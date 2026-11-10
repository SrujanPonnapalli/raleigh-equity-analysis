# Source data and refresh

Run `python3 refresh_data.py` from the project directory. It uses only the Python
standard library and public HTTPS sources. Run offline conversion checks with
`python3 -m unittest -v test_refresh_data.py`.

The original class request export remains at
`Ask_Raleigh_Requests_-7614209799151684723.csv`. The original income table is
preserved in `data/original/raleigh_income.csv` during the first successful
download of requests. Its original source and vintage are unknown.
All 15 original estimates exactly match the official 2020–2024 ACS B19013
estimates downloaded in this refresh; the original assembly process is unknown.

The active inputs are root-level `Ask_Raleigh_Requests.csv` and
`raleigh_income.csv`. All existing entry points use the shared request-path
resolver, which already prefers this canonical request filename. The income
file retains `Zip Code` and `Median Income` for compatibility and adds uncertainty
and vintage columns. Existing analysis code does not yet use those extra columns.

Each refresh saves raw sources, compatible CSVs, metadata, and a manifest with
SHA-256 hashes in `data/snapshots/<UTC timestamp>/`. `data/latest_snapshot.txt`
identifies the active snapshot. Failed attempts may leave partial snapshot
directories but do not publish unvalidated data. Publication replaces each input
atomically; avoid running an analysis during the brief two-file publication step.

## Requests

[Ask Raleigh Requests, published by RaleighGIS](https://www.arcgis.com/home/item.html?id=9ce6bd1524bc445d9fe7c852ee73b4fb)
describes a twice-daily feed. Refresh retrieves all object IDs and checks every
batch against that ID inventory, unique request numbers, and unchanged edit
metadata and IDs at the end of the download. This detects routine truncation or
mid-download updates; it is not a server-side transactional snapshot.

Raw ArcGIS attributes and WGS84 geometries are saved in `requests_raw.json`.
The compatible CSV uses source field aliases and adds `x` and `y`. All epoch
timestamps are serialized in ISO 8601 **UTC**, rather than the ambiguous strings
in the original export. No status, missingness, geographic, or resolution-time
filter is applied. Service requests can be revised or removed upstream; the
new file is a fresh snapshot, not an append to old records. OBJECTID is a source
row identifier; Service Request Number is the request identity used for checks.

## Income

Source: [2020–2024 ACS five-year table B19013, public bulk file](https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b19013.dat).
See the [Census release schedule](https://www.census.gov/programs-surveys/acs/news/data-releases/2024/release-schedule.html)
and [summary-file documentation](https://www.census.gov/programs-surveys/acs/data/summary-file.2024.html).
This is the latest released five-year vintage verified for the November 10,
2026 refresh, not an estimate of income on that date. Income is median household
income in 2024 inflation-adjusted dollars. Margins of error are at 90% confidence.

The parser selects 2020 ZCTA identifiers (`860Z200US`), estimate `B19013_E001`,
and margin of error `B19013_M001`. Suppressed or unavailable estimates remain
blank. The active table keeps the original 15-code scope. The snapshot also
contains `income_all_request_zctas.csv` for Census matches to other request ZIPs;
these are not automatically included in analysis. ZIP-to-ZCTA matching needs
review before making geographic claims. The existing third-party boundary file
was not refreshed and has no verified vintage; it remains a separate review item.

The main pipeline was rerun on November 10, 2026 using this snapshot, regenerating
`output/equity_scatter.png`, `output/service_disparity.png`, and
`output/raleigh_equity_map.html`. It included 12,871 income-matched requests across
15 ZIPs under the existing exclusions. The map displays a sample of 2,500 markers
from 12,709 requests with coordinates, resolution times, and service categories.
The EDA and presentation outputs have not been regenerated. Successful execution
demonstrates compatibility, not validation of the statistical conclusions.
