# Context for the Raleigh presentation

These data describe the areas discussed in the presentation. They do not change
the request cohorts, matching, investigation rule, or Atlas outcome analysis.
The demographic profile was added after 27610 was identified by the parks screen;
it was not used to choose the location or test racial disparities in service.

## One release and explicit geographies

All estimates below use the **2020–2024 American Community Survey five-year
release**, with income in 2024 dollars. The comparison areas are Census ZCTA
27610, Raleigh city, and Wake County. These are different geographic units;
27610 is not the same as Southeast Raleigh or the portion inside city limits.

| Characteristic | ZCTA 27610 | Raleigh city | Wake County |
| --- | ---: | ---: | ---: |
| Median household income | $67,932 ± $6,108 | $85,395 ± $2,159 | $105,768 ± $1,626 |
| People below the poverty line | 15.7% ± 2.7 pp | 11.9% ± 0.8 pp | 8.1% ± 0.4 pp |
| Black or African American alone | 54.7% ± 3.2 pp | 26.6% ± 0.7 pp | 18.8% |
| Hispanic or Latino, any race | 20.1% ± 2.7 pp | 12.6% ± 0.7 pp | 11.6% |

The ± values are **90% margins of error**, not service-outcome confidence
intervals. Black-alone and Hispanic ethnicity estimates overlap and must not be
added. Poverty uses people for whom poverty status is determined, rather than
the full population. No significance test between these overlapping areas is
claimed. The saved summary preserves more precision than this rounded table.

## Sources and calculations

The [saved source rows](acs2024/) come directly from the Census Bureau's
[2024 ACS table-based summary files](https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/):

- **B19013:** median household income, estimate and margin of error.
- **B02001:** Black-alone count divided by total population.
- **B03003:** Hispanic-or-Latino count divided by total population, regardless of race.
- **B17001:** count below poverty divided by the population with determined poverty status.

[summary.json](acs2024/summary.json) records the source URLs, retrieval time,
full-download hashes, selected-row hashes, denominators, and margins of error.
The large national downloads are represented by the selected rows and their
original source hashes; they are not duplicated here in full.

For a subset proportion `p = numerator / denominator`, the approximate percent
margin of error is `100 × sqrt(M_num² − p² × M_den²) / denominator`. If the term
under the square root is negative, the Census ratio formula uses a plus sign.
This follows the Census Bureau's
[2024 worked examples](https://www2.census.gov/programs-surveys/acs/tech_docs/accuracy/2024_ACS_Accuracy_Document_Worked_Examples.pdf).
These approximations do not include covariance. Negative special MOE codes are
retained in source rows and are never treated as numerical uncertainty. Derived
MOEs are left null when either input has such a code; that is why the two Wake
County race/ethnicity percentages above have no derived MOE.

Reproduce the saved calculations without a network connection:

```bash
python3 data/presentation_context/summarize.py
```

## Geographic illustration

The saved [Raleigh](acs2024/raleigh.geojson) and
[27610](acs2024/zcta27610.geojson) polygons come from
[Census TIGERweb ACS2024](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_ACS2024/MapServer).
The ZCTA uses the 2020 delineation. Geometry was simplified at 0.00015 degrees
for an orientation figure; it is not used for service assignment, current city
jurisdiction, or the request-to-block-group join. Exact query URLs and hashes are
in [boundary-sources.json](acs2024/boundary-sources.json).

Raleigh's [FY2024–25 draft action plan](https://cityofraleigh0drupal.blob.core.usgovcloudapi.net/drupal-prod/COR19/FY25-AAP-Draft-Combined.pdf)
includes 27610 among Southeast Raleigh ZIP codes (public survey analysis),
alongside 27601 and 27603. The presentation therefore says 27610 **includes parts
of Southeast Raleigh**, without equating the ZIP and neighborhood boundaries.

## Interpretation

The profile provides resident and area context for a records review. It does not
establish who submitted the requests, which residents use a particular park,
or why a ticket received a resolution timestamp. This project has not tested a
racial disparity in service outcomes.

A single five-year snapshot cannot establish that the Hispanic population is
growing, that the area is gentrifying, or that displacement is occurring.
Those descriptions from the proposed background text are not presented as
findings. Age, house values, and renter cost burden are also omitted from this
briefing to keep its context focused and avoid mixing releases or universes.
