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

## Request eligibility and duration checks

The shared request loader retains all 18,526 requests, including unresolved cases
and missing coordinates. Completed-only ZIP comparisons explicitly select known
ZIPs and reported resolution hours, without requiring coordinates. All output
loaders now use that common eligibility rule. EDA further excludes missing task
labels. Income joins reject duplicate ZIP keys rather than multiplying records,
and the main pipeline defines income groups from the income table independently
of completion outcomes.

In this snapshot, all 15,626 reported durations agree with submission-to-resolution
elapsed calendar hours to within one hour: 15,625 are rounded down to whole hours,
and one retains fractional precision. There are no negative resolution durations.
`Closed At` is a different endpoint: 52 records have closure before their recorded
resolution, and two have closure before submission. Nine nonterminal-status
records retain resolution timestamps but no reported resolution hours. A single
snapshot cannot reconstruct reopenings or explain these exceptions. Recorded
resolution must not be equated with verified completion of physical work.

The main pipeline, EDA, and ZIP choropleth outputs were regenerated after the
eligibility corrections. The main completed-only analysis now includes 13,117
income-matched requests across 15 ZIPs, up from 12,871 when coordinates were
required. The map still displays 2,500 sampled markers from 12,709 requests with
coordinates, reported resolution hours, and service categories. Map display
counts are separate from analytical sample counts.

The legacy `neglect_rate` field and output filename remain for compatibility,
but labels now describe the metric accurately: the share of **completed requests**
taking over 30 days, not the share of all requests still waiting. EDA task keys
include category and service to prevent conflating generic request-type labels.
The five task correlation tests now include Bonferroni-adjusted p-values; the
other EDA correlations are explicitly exploratory and unadjusted. Charts display
long durations outside a 60-day window without moving them into the final bin,
and ZIP rankings use separate axes for percentages and days.

The historical presentation outputs in `presentation/output/` and
`final_presentation/output/` were not regenerated. Their hardcoded examples and
selected tasks are exploratory illustrations, not confirmed equity findings.

## Fixed-follow-up parks comparison

Run `python3 cohort_analysis.py` with the packages in `requirements.txt` installed.
Outputs go to `output/cohorts/`: a record-level cohort, counts by task, month,
task/month and ZIP, a JSON summary, and a comparison chart. The script verifies
both active input hashes against the snapshot manifest before calculation.

The primary endpoint is a recorded `Resolved At` timestamp within **90 elapsed
calendar days** of submission. Missing resolution timestamps remain in the
denominator and count as no recorded resolution within the window. Neither
administrative closure nor rounded hours substitute for the endpoint. Cancelled
requests would count as no recorded resolution unless they have a resolution
timestamp; none of the 497 primary parks-cohort records is cancelled. The city
has not been shown to promise 90-day completion: this is an analytical window.

Use complete submission months in America/New_York from July 2025, when the
[public portal launched](https://raleighnc.gov/government/news/ask-raleigh-launches-july-1),
through July 2026, the latest complete month giving every request at least
90 days of observation at the snapshot's source-data edit timestamp. Exclude
prelaunch records from this primary comparison. Sensitivities use 30 and 60 days
on the same submission cohort. The analysis is a follow-up to an observed pattern,
not a held-out or preregistered confirmation.

Lower-income ZIPs: 27604, 27605, 27610. Higher-income ZIPs: 27608, 27613, 27614.
These are the bottom and top three estimates in the original 15-ZIP income scope.
They are area-level groups, not individual household classifications. ACS margins
of error are retained in the source but are not propagated into rank uncertainty.
Notably, ZIPs 27605 and 27601 differ by only $254 in estimated income, much less
than either estimate's margin of error; membership near the cutoff is uncertain.

For direct standardization, define tasks as service plus request type (keeping an
explicit unspecified-type bucket) within Parks & Recreation. Retain task/month
strata represented in both income groups. Give both groups the **same** weight
for each retained stratum: combined request count in that stratum divided by all
requests in retained strata. The adjusted group rate is the weighted sum of its
within-stratum resolution rates. This controls observed task/month composition
on common support; it does not control severity, routing, precise location,
repeat reports of the same issue, or reporting propensity. Matching a task label
does not prove equivalent work. Do not extrapolate to excluded task/months.

For the 90-day endpoint, all 497 eligible requests show recorded-resolution rates
of 47.5% in lower-income ZIPs (142/299) and 56.6% in higher-income ZIPs (112/198).
Common task/month support retains 447 requests: 252 lower-income and 195
higher-income. Their unadjusted rates are 50.8% and 56.9%; standardization gives
51.7% and 56.4%, a lower-minus-higher gap of **-4.7 percentage points**.
The change from the original -9.1-point gap reflects both support restriction
and reweighting; it is not all attributable to task/month adjustment.

Requiring five requests per group in each stratum retains only 354 requests
and gives a -6.7-point gap. Recomputing after removing each ZIP in turn gives
gaps from -21.1 to +0.8 points; excluding 27613 reverses the sign slightly.
Those sensitivities re-estimate common support and weights. They are not
confidence intervals. With only three ZIPs per group, request-level independence
would exaggerate the evidence. No request-independent p-value or causal effect
is claimed. The results support investigation of local backlogs, not a stable
citywide income-disparity headline.

Regression tests: `python3 -m unittest -v`. The tests cover eligibility,
duplicate identities and joins, invalid durations, disjoint income groups,
fixed-window boundaries, unresolved denominators, one-sided strata, and an
artificial task-mix gap that should disappear after standardization.
