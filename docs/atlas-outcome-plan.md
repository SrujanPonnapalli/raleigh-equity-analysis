# Exploratory Atlas outcome comparison

This specification follows the geographic feasibility pilot. It is fixed before
examining resolution outcomes by Atlas vulnerability. Parks and the request
snapshot were already selected during the earlier ZIP analysis, so this remains
an exploratory follow-up rather than a preregistered or held-out confirmation.

## Population and question

Within the original 15-ZIP parks scope, are requests in areas classified as more
vulnerable less likely to have a recorded resolution within 90 days, after
accounting for recorded task and submission month?

Use submissions from July 1, 2025 through April 30, 2026 and the saved November 10
request snapshot. Retain unfinished requests in the denominator. Require a
unique interior block-group match with positive population and a valid index
rank. The pilot identifies 761 usable requests from 773 submissions. Do not
expand to other ZIPs, services, or county indexes in this stage.

This population is defined by the original ZIP scope and valid county geography.
It does not establish that every request was within city limits or city service
responsibility. Do not describe the estimate as covering all Raleigh residents.

## Primary measure and comparison

Use the county's published `TOTAL_SCORE` bands. Compare higher vulnerability
(bands 4 and 5, ranks 359 to 597) with lower vulnerability (bands 1 and 2, ranks
1 to 238). Exclude the middle band from this contrast and report how many
requests this removes. Do not alter the county breaks based on outcomes.

The primary endpoint is a recorded `Resolved At` timestamp within 90 elapsed
days of submission. This does not verify physical completion. Report the
unadjusted rates, shared-task/month rates, and directly standardized rates.
Use the same pooled request weights for both vulnerability groups within common
service/request-type and submission-month strata, as in the existing analysis.
The direction is higher minus lower vulnerability; a negative gap means lower
recorded resolution in the higher-vulnerability group.

Require at least 30 requests per group per period and at least 80% comparable
coverage in each group for the primary task/month comparison. A shared stratum
must contain at least one request per group. The small-cell sensitivity below
shows how conclusions change when requiring more within-stratum observations.

## Fixed sensitivity checks

- Use 180 days on the same submission population.
- Show July to December 2025 and January to April 2026 separately. These are
  stability checks, not independent confirmations of a selected result.
- Require at least five requests per group per task/month. Report the coverage
  loss and do not extrapolate to the excluded requests.
- Replace the composite classification with the published poverty rate alone.
  Among county block groups with positive population, use the 40th and 60th
  percentiles of `POV_RATE` to define lower and higher poverty, respectively.
  Include ties together at the cutoff; do not order tied areas arbitrarily.
  Use the same endpoint and task/month standardization. This is the only
  alternative socioeconomic measure tested in this stage.
- Remove each represented block group in turn and recompute the primary
  standardized gap. Report the full range and whether its direction reverses.
  Common support and weights are re-estimated, so this range is not a confidence
  interval. Do not treat individual requests as independent income or
  vulnerability observations or calculate request-independent p-values.

## Interpretation and stopping

A 10-percentage-point shortfall remains the practical threshold for considering
an additional follow-up lead. This is neither a significance threshold nor a
city service commitment. Consider a new Atlas lead only if the primary gap
reaches that threshold, both periods and the poverty sensitivity point in the
same direction, the primary coverage requirements pass, and omitting any one
block group does not reverse the direction. Show all specified results even
when these conditions fail.

Regardless of the outcome, do not test more indexes, boundaries, cutoffs, or
service categories from this snapshot to search for a preferred conclusion.
Any surviving pattern still requires validation of service responsibility and
the meaning of resolved tickets. The existing 27610 investigation flag remains
a separate result.
