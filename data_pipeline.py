"""
Data pipeline for Raleigh 311 civic equity analysis.

Loads, cleans, aggregates, and merges service-request data with
Census median-income data by ZIP code.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

HOURS_PER_DAY = 24.0

REQUESTS_COLUMNS = {
    "zip": "ZIP Code",
    "hours": "Hours to Resolve",
    "category": "Service Category",
    "longitude": "x",
    "latitude": "y",
}

INCOME_COLUMNS = {
    "zip": "Zip Code",
    "income": "Median Income",
}


def _normalize_zip(series: pd.Series) -> pd.Series:
    """Normalize ZIP codes to comparable string values."""
    return (
        series.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(5)
    )


def load_requests(path: str | Path) -> pd.DataFrame:
    """
    Load and clean the Ask Raleigh service-requests dataset.

    Parameters
    ----------
    path : str | Path
        Path to the requests CSV file.

    Returns
    -------
    pd.DataFrame
        Cleaned request-level records with derived ``days_to_resolve``.

    Raises
    ------
    FileNotFoundError
        If the CSV file does not exist.
    ValueError
        If required columns are missing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Requests file not found: {path}")

    df = pd.read_csv(path)
    missing = [col for col in REQUESTS_COLUMNS.values() if col not in df.columns]
    if missing:
        raise ValueError(f"Requests file is missing required columns: {missing}")

    cleaned = df.copy()
    cleaned["zip_code"] = _normalize_zip(cleaned[REQUESTS_COLUMNS["zip"]])
    cleaned["hours_to_resolve"] = pd.to_numeric(
        cleaned[REQUESTS_COLUMNS["hours"]], errors="coerce"
    )
    cleaned["days_to_resolve"] = cleaned["hours_to_resolve"] / HOURS_PER_DAY
    cleaned["service_category"] = cleaned[REQUESTS_COLUMNS["category"]].astype("string")
    cleaned["longitude"] = pd.to_numeric(
        cleaned[REQUESTS_COLUMNS["longitude"]], errors="coerce"
    )
    cleaned["latitude"] = pd.to_numeric(
        cleaned[REQUESTS_COLUMNS["latitude"]], errors="coerce"
    )

    invalid_coords = cleaned["longitude"].isna() | cleaned["latitude"].isna()
    if invalid_coords.any():
        logger.warning(
            "Dropping %d request(s) with missing or invalid coordinates.",
            int(invalid_coords.sum()),
        )
        cleaned = cleaned.loc[~invalid_coords].copy()

    invalid_hours = cleaned["hours_to_resolve"].isna()
    if invalid_hours.any():
        logger.warning(
            "Dropping %d request(s) with missing resolution time.",
            int(invalid_hours.sum()),
        )
        cleaned = cleaned.loc[~invalid_hours].copy()

    return cleaned.reset_index(drop=True)


def load_income(path: str | Path) -> pd.DataFrame:
    """
    Load and clean the median-income-by-ZIP dataset.

    Parameters
    ----------
    path : str | Path
        Path to the income CSV file.

    Returns
    -------
    pd.DataFrame
        Cleaned income records keyed by ``zip_code``.

    Raises
    ------
    FileNotFoundError
        If the CSV file does not exist.
    ValueError
        If required columns are missing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Income file not found: {path}")

    df = pd.read_csv(path)
    missing = [col for col in INCOME_COLUMNS.values() if col not in df.columns]
    if missing:
        raise ValueError(f"Income file is missing required columns: {missing}")

    cleaned = df.copy()
    cleaned["zip_code"] = _normalize_zip(cleaned[INCOME_COLUMNS["zip"]])
    cleaned["median_income"] = pd.to_numeric(
        cleaned[INCOME_COLUMNS["income"]], errors="coerce"
    )

    invalid_income = cleaned["median_income"].isna()
    if invalid_income.any():
        logger.warning(
            "Dropping %d ZIP code(s) with missing median income.",
            int(invalid_income.sum()),
        )
        cleaned = cleaned.loc[~invalid_income].copy()

    return cleaned[["zip_code", "median_income"]].drop_duplicates("zip_code")


def aggregate_by_zip(requests: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate request metrics at the ZIP-code level.

    Parameters
    ----------
    requests : pd.DataFrame
        Cleaned request-level data from :func:`load_requests`.

    Returns
    -------
    pd.DataFrame
        ZIP-level summary with request volume and average resolution time.
    """
    if requests.empty:
        return pd.DataFrame(
            columns=[
                "zip_code",
                "request_volume",
                "avg_days_to_resolve",
                "median_days_to_resolve",
            ]
        )

    grouped = (
        requests.groupby("zip_code", as_index=False)
        .agg(
            request_volume=("days_to_resolve", "size"),
            avg_days_to_resolve=("days_to_resolve", "mean"),
            median_days_to_resolve=("days_to_resolve", "median"),
        )
        .sort_values("request_volume", ascending=False)
    )
    return grouped.reset_index(drop=True)


def merge_datasets(
    requests: pd.DataFrame,
    income: pd.DataFrame,
    zip_summary: Optional[pd.DataFrame] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Merge income data onto request and ZIP-level tables.

    Parameters
    ----------
    requests : pd.DataFrame
        Cleaned request-level data.
    income : pd.DataFrame
        Cleaned income data.
    zip_summary : pd.DataFrame, optional
        Pre-computed ZIP aggregates. Computed when omitted.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        ``(merged_requests, merged_zip_summary)`` containing only ZIP codes
        present in the income table.
    """
    if zip_summary is None:
        zip_summary = aggregate_by_zip(requests)

    merged_requests = requests.merge(income, on="zip_code", how="inner")
    merged_zip = zip_summary.merge(income, on="zip_code", how="inner")

    unmatched_requests = len(requests) - len(merged_requests)
    if unmatched_requests > 0:
        logger.warning(
            "%d request(s) excluded because their ZIP code is absent from income data.",
            unmatched_requests,
        )

    unmatched_zips = len(zip_summary) - len(merged_zip)
    if unmatched_zips > 0:
        logger.warning(
            "%d ZIP code(s) excluded from ZIP-level analysis due to missing income.",
            unmatched_zips,
        )

    return merged_requests.reset_index(drop=True), merged_zip.reset_index(drop=True)


def wealth_segments(
    merged_requests: pd.DataFrame,
    quantile: float = 0.20,
) -> tuple[set[str], set[str]]:
    """
    Identify the highest- and lowest-income ZIP code segments.

    Parameters
    ----------
    merged_requests : pd.DataFrame
        Request-level data merged with income.
    quantile : float, optional
        Fraction of ZIP codes in each wealth segment (default 0.20).

    Returns
    -------
    tuple[set[str], set[str]]
        ``(wealthy_zips, low_income_zips)`` based on median income ranks.
    """
    zip_income = (
        merged_requests[["zip_code", "median_income"]]
        .drop_duplicates()
        .sort_values("median_income")
    )
    n_zips = len(zip_income)
    if n_zips == 0:
        return set(), set()

    segment_size = max(1, int(np.ceil(n_zips * quantile)))
    low_income_zips = set(zip_income.head(segment_size)["zip_code"])
    wealthy_zips = set(zip_income.tail(segment_size)["zip_code"])
    return wealthy_zips, low_income_zips


def income_tiers(
    merged_requests: pd.DataFrame,
    quantile: float = 0.20,
) -> tuple[set[str], set[str], set[str]]:
    """
    Split ZIP codes into bottom, middle, and top income tiers.

    Parameters
    ----------
    merged_requests : pd.DataFrame
        Request-level data merged with income.
    quantile : float, optional
        Fraction of ZIP codes in the bottom and top tiers (default 0.20).
        The remainder forms the middle tier.

    Returns
    -------
    tuple[set[str], set[str], set[str]]
        ``(low_income_zips, middle_zips, wealthy_zips)`` ordered by median income.
    """
    zip_income = (
        merged_requests[["zip_code", "median_income"]]
        .drop_duplicates()
        .sort_values("median_income")
    )
    n_zips = len(zip_income)
    if n_zips == 0:
        return set(), set(), set()

    segment_size = max(1, int(np.ceil(n_zips * quantile)))
    low_income_zips = set(zip_income.head(segment_size)["zip_code"])
    wealthy_zips = set(zip_income.tail(segment_size)["zip_code"])
    if segment_size >= n_zips - segment_size:
        middle_zips: set[str] = set()
    else:
        middle_zips = set(
            zip_income.iloc[segment_size : n_zips - segment_size]["zip_code"]
        )
    return low_income_zips, middle_zips, wealthy_zips


def build_pipeline(
    requests_path: str | Path,
    income_path: str | Path,
) -> dict[str, pd.DataFrame | tuple[set[str], set[str]]]:
    """
    Run the full data pipeline end to end.

    Parameters
    ----------
    requests_path : str | Path
        Path to the Ask Raleigh requests CSV.
    income_path : str | Path
        Path to the median-income CSV.

    Returns
    -------
    dict
        Dictionary with keys ``requests``, ``income``, ``zip_summary``,
        ``merged_requests``, ``merged_zip``, and ``wealth_segments``.
    """
    requests = load_requests(requests_path)
    income = load_income(income_path)
    zip_summary = aggregate_by_zip(requests)
    merged_requests, merged_zip = merge_datasets(requests, income, zip_summary)
    segments = wealth_segments(merged_requests)

    return {
        "requests": requests,
        "income": income,
        "zip_summary": zip_summary,
        "merged_requests": merged_requests,
        "merged_zip": merged_zip,
        "wealth_segments": segments,
    }
