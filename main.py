"""
Raleigh 311 Civic Equity Analysis — entry point.

Loads data, runs the pipeline, and writes presentation-ready charts and
an interactive map to the ``output/`` directory.

Dependencies
------------
Install required packages::

    pip install pandas numpy matplotlib seaborn scipy folium branca

Usage
-----
::

    python main.py

Optional arguments allow custom input paths and output directory::

    python main.py --requests path/to/requests.csv --income path/to/income.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from charts import plot_equity_scatter, plot_service_disparity_bars
from data_pipeline import build_pipeline
from map_builder import build_equity_map

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"


def _resolve_requests_path(explicit: str | None) -> Path:
    """Resolve the requests CSV, preferring an explicit path when provided."""
    if explicit:
        return Path(explicit)

    preferred = PROJECT_ROOT / "Ask_Raleigh_Requests.csv"
    if preferred.exists():
        return preferred

    matches = sorted(PROJECT_ROOT.glob("Ask_Raleigh_Requests*.csv"))
    if matches:
        return matches[0]

    raise FileNotFoundError(
        "Could not locate requests CSV. Pass --requests or place "
        "Ask_Raleigh_Requests.csv in the project directory."
    )


def _configure_logging(verbose: bool) -> None:
    """Configure root logging for CLI execution."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s | %(name)s | %(message)s",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate Raleigh 311 civic equity visualizations."
    )
    parser.add_argument(
        "--requests",
        type=str,
        default=None,
        help="Path to Ask Raleigh requests CSV.",
    )
    parser.add_argument(
        "--income",
        type=str,
        default=str(PROJECT_ROOT / "raleigh_income.csv"),
        help="Path to median-income-by-ZIP CSV.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated PNG and HTML files.",
    )
    parser.add_argument(
        "--heatmap",
        action="store_true",
        help="Overlay a resolution-time heatmap on the Folium map.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Run the full analysis workflow.

    Returns
    -------
    int
        Process exit code (0 on success, 1 on failure).
    """
    args = parse_args(argv)
    _configure_logging(args.verbose)

    try:
        requests_path = _resolve_requests_path(args.requests)
        income_path = Path(args.income)
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Loading data from %s and %s", requests_path, income_path)
        artifacts = build_pipeline(requests_path, income_path)

        merged_requests = artifacts["merged_requests"]
        merged_zip = artifacts["merged_zip"]
        wealthy_zips, low_income_zips = artifacts["wealth_segments"]

        if merged_zip.empty:
            raise ValueError(
                "No ZIP codes overlap between requests and income data."
            )

        scatter_path = plot_equity_scatter(
            merged_zip,
            output_dir / "equity_scatter.png",
        )
        logger.info("Saved equity scatter plot to %s", scatter_path)

        disparity_path = plot_service_disparity_bars(
            merged_requests,
            wealthy_zips,
            low_income_zips,
            output_dir / "service_disparity.png",
        )
        logger.info("Saved service disparity chart to %s", disparity_path)

        map_path = build_equity_map(
            artifacts["requests"],
            output_dir / "raleigh_equity_map.html",
            use_heatmap=args.heatmap,
        )
        logger.info("Saved interactive map to %s", map_path)

        print("\nRaleigh Civic Equity Analysis complete.")
        print(f"  ZIP codes analyzed: {len(merged_zip)}")
        print(f"  Requests with income match: {len(merged_requests):,}")
        print(f"  All requests retained: {len(artifacts['requests']):,}")
        map_eligible = artifacts["requests"].dropna(
            subset=["latitude", "longitude", "days_to_resolve", "service_category"]
        )
        print(f"  Map-eligible requests: {len(map_eligible):,}; markers shown: {min(2500, len(map_eligible)):,}")
        print("\nOutputs:")
        print(f"  {scatter_path}")
        print(f"  {disparity_path}")
        print(f"  {map_path}")
        return 0

    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Unexpected error during analysis.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
