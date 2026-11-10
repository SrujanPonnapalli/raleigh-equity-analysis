# Wake County Atlas feasibility pilot

Branch: `explore/wake-equity-atlas-pilot`.

## Scope

Use the saved November 10, 2026 Ask Raleigh snapshot. Do not refresh the request
data, change the existing ZIP analysis, or select an Atlas measure by its
relationship to resolution outcomes.

First assess whether request locations can be linked to the county's published
2020 to 2024 Community Vulnerability Index at Census block-group level. This
phase examines source definitions, spatial matches, missing data, and sample
sizes. It does not calculate resolution rates or test disparities.

The main coverage check uses the same 15-ZIP parks cohort as the stopping screen:
submissions from July 1, 2025 through April 30, 2026. Also report geographic
coverage for the full request snapshot and parks submissions outside that scope.
Those diagnostic populations must not silently replace the original cohort.

## Source choice before the join

Use the county's existing Community Vulnerability Index, not a new index built
from selected indicators:

- [Published map, Community Vulnerability Series 2020–2024](https://www.arcgis.com/home/item.html?id=443b36c6f1e4428bad45db641060288e).
- [Underlying service item](https://www.arcgis.com/home/item.html?id=eb973c734de14652bcadd9af211c751d), published in the Wake County ArcGIS organization.
- [Vulnerability assessment polygon layer](https://services1.arcgis.com/a7CWfuGP5ZnLYE7I/arcgis/rest/services/Vulnerability_Assessment_Index_Series_2024/FeatureServer/0).

The service describes five ACS indicators: poverty, unemployment, age dependency,
housing vacancy, and educational attainment. Inspect its component ranks,
`TOTAL_CALC`, and `TOTAL_SCORE` before treating the final value as an index.
The map's existing legend defines the bands; do not choose breaks from the
request outcomes. Higher `TOTAL_SCORE` is displayed as greater vulnerability.

The published layer's low-population areas need explicit checks. A published
rank in an area with no residents is not a meaningful measure of resident
vulnerability. Exclude zero-population areas from usable vulnerability matches,
but retain them in the geographic coverage accounting. Flag areas with fewer
than 100 residents for review without inventing a suppression standard.

## Checks and decision criteria

1. Confirm the publisher organization, map-to-layer lineage, ACS period,
   unique block-group identifiers, and complete feature download. Preserve raw
   inputs, metadata, download times, and hashes.
2. Request polygons in WGS84, matching the request longitude/latitude fields.
   Check geometry validity. Assign a point only when it lies strictly inside
   exactly one polygon. Report boundary points and multiple matches separately;
   do not use nearest-area assignment or infer an area from ZIP alone.
3. Report missing coordinates, locations outside the layer, ambiguous matches,
   missing/invalid scores, and zero-population matches. Keep one output row per
   input request and verify that the join does not duplicate requests.
4. Require at least 95% of all submissions in the original parks cohort to have
   an unambiguous, usable vulnerability match before recommending an outcome
   comparison. This is a practical completeness threshold, not a significance
   test. Report coverage by ZIP and submission month as well as overall.
5. Count requests and distinct block groups across the published bands and
   service/month combinations. Assess whether pooled comparisons have enough
   data; do not assume each block group supports its own statistical test.

County polygons do not establish Raleigh service jurisdiction. In particular,
Raleigh request locations outside Wake County cannot be assigned to the county
Atlas. City limits and service responsibility must be checked before expanding
the analytical population beyond the original scope. Boundary and layer dates
also need to be distinguished from the request dates.

## Next stage

If the pilot supports proceeding, write a separate outcome-analysis specification
before looking at resolution differences. It must fix the geography, primary
measure, grouping, endpoint, follow-up windows, minimum sample sizes, adjustment,
and sensitivity checks. It must also carry forward the unresolved definition of
physical service completion. The original 27610 finding remains a separate lead.
