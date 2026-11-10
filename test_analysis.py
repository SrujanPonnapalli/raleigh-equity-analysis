"""Regression checks for eligibility, follow-up, and standardization."""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from cohort_analysis import prepare_cohort, standardize
from data_pipeline import _normalize_zip, build_pipeline, income_tiers, load_income, load_requests


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def save_requests(self, rows):
        data = [{"Service Request Number": f"R{i}", "ZIP Code": "27601", "Hours to Resolve": 24,
                 "Service Category": "Parks & Recreation", "Service": "Tree Service", "Request Type": None,
                 "x": None, "y": None, **row} for i, row in enumerate(rows)]
        path = self.root / "requests.csv"
        pd.DataFrame(data).to_csv(path, index=False)
        return path

    def test_unfinished_and_ungeocoded_requests_are_retained(self):
        path = self.save_requests([{}, {"Hours to Resolve": None}, {"ZIP Code": "27602", "x": -78, "y": 35}])
        income_path = self.root / "income.csv"
        pd.DataFrame({"Zip Code": ["27601", "27602"], "Median Income": [50000, 100000]}).to_csv(income_path, index=False)
        pipeline = build_pipeline(path, income_path)
        self.assertEqual(len(pipeline["requests"]), 3)
        self.assertEqual(len(pipeline["merged_requests"]), 2)
        self.assertEqual(pipeline["merged_zip"]["request_volume"].sum(), 2)
        self.assertTrue(pipeline["merged_requests"].longitude.isna().any())

    def test_duplicate_requests_and_negative_hours_rejected(self):
        path = self.save_requests([{"Service Request Number": "same"}, {"Service Request Number": "same"}])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_requests(path)
        path = self.save_requests([{"Hours to Resolve": -1}])
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            load_requests(path)

    def test_invalid_zips_do_not_become_a_fake_area(self):
        result = _normalize_zip(pd.Series(["27601.0", "", "abc", "00000", None]))
        self.assertEqual(result.iloc[0], "27601")
        self.assertTrue(result.iloc[1:].isna().all())

    def test_duplicate_income_cannot_expand_a_join(self):
        path = self.root / "income.csv"
        pd.DataFrame({"Zip Code": [27601, 27601], "Median Income": [50000, 60000]}).to_csv(path, index=False)
        with self.assertRaisesRegex(ValueError, "one row per ZIP"):
            load_income(path)

    def test_income_segments_cannot_overlap(self):
        income = pd.DataFrame({"zip_code": ["27601"], "median_income": [50000]})
        with self.assertRaisesRegex(ValueError, "disjoint"):
            income_tiers(income)
        with self.assertRaises(ValueError):
            income_tiers(income, quantile=0.8)
        tied = pd.DataFrame({"zip_code": ["27601", "27602", "27603", "27604"], "median_income": [50000, 50000, 80000, 100000]})
        with self.assertRaisesRegex(ValueError, "ties"):
            income_tiers(tied)

    def test_fixed_window_counts_unfinished_and_uses_exact_timestamps(self):
        start = pd.Timestamp("2026-01-01T00:00:00Z")
        path = self.save_requests([
            {"Submittal Date": start, "Resolved At": start + pd.Timedelta(days=90)},
            {"Submittal Date": start, "Resolved At": start + pd.Timedelta(days=90, seconds=1)},
            {"Submittal Date": start, "Resolved At": None, "Closed At": start + pd.Timedelta(days=1)},
            {"Submittal Date": "2026-02-01T00:00:00Z", "Resolved At": None},
        ])
        income = pd.DataFrame({"zip_code": ["27601", "27602"], "median_income": [50000, 100000]})
        result = prepare_cohort(load_requests(path), income, "2026-06-01T00:00:00Z", start, "2026-02-01T00:00:00Z")
        self.assertEqual(result.resolved_within_window.tolist(), [True, False, False])
        with self.assertRaisesRegex(ValueError, "incomplete follow-up"):
            prepare_cohort(load_requests(path), income, "2026-03-01T00:00:00Z", start, "2026-02-01T00:00:00Z")

    def test_standardization_removes_an_artificial_task_mix_gap(self):
        rows = []
        # Each group's task-specific rate is identical, but its task mix differs.
        for group, fast, slow in [("Lower", 2, 8), ("Higher", 8, 2)]:
            rows += [{"income_group": group, "task": "fast", "resolved_within_window": True}] * fast
            rows += [{"income_group": group, "task": "slow", "resolved_within_window": False}] * slow
        result = standardize(pd.DataFrame(rows), ["task"])
        self.assertAlmostEqual(result["rate_lower"], 0.5)
        self.assertAlmostEqual(result["rate_higher"], 0.5)
        self.assertAlmostEqual(result["gap_pp"], 0)

    def test_one_sided_strata_are_excluded_not_imputed(self):
        cohort = pd.DataFrame([
            {"income_group": "Lower", "task": "shared", "resolved_within_window": True},
            {"income_group": "Higher", "task": "shared", "resolved_within_window": False},
            {"income_group": "Lower", "task": "unshared", "resolved_within_window": False},
        ])
        result = standardize(cohort, ["task"])
        self.assertEqual(result["requests_lower"], 1)
        self.assertEqual(result["gap_pp"], 100)
        self.assertIsNone(standardize(cohort, ["task"], 5)["gap_pp"])


if __name__ == "__main__":
    unittest.main()
