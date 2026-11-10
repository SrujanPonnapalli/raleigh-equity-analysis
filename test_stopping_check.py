"""Checks for the fixed investigation gate and all-ZIP eligibility."""

import unittest

import pandas as pd

from cohort_analysis import prepare_cohort
from stopping_check import PERIODS, classify, compare_zip


class StoppingCheckTests(unittest.TestCase):
    def rows(self, gap=-10, coverage=0.8, n=30):
        return [{"period": p[0], "horizon_days": h, "focal_requests": n, "coverage": coverage, "gap_pp": gap}
                for p in PERIODS for h in [90, 180]]

    def test_all_periods_and_windows_required(self):
        rows = self.rows()
        self.assertEqual(classify(rows), "investigation flag")
        rows[-1]["gap_pp"] = -9.9
        self.assertEqual(classify(rows), "no persistent shortfall under this rule")
        rows[-1] = rows[0].copy()
        self.assertEqual(classify(rows), "insufficient comparable data")

    def test_sparse_or_low_coverage_results_cannot_flag(self):
        self.assertEqual(classify(self.rows(gap=-90, n=29)), "insufficient comparable data")
        self.assertEqual(classify(self.rows(gap=-90, coverage=0.79)), "insufficient comparable data")

    def test_reference_support_and_denominator(self):
        rows = ([{"zip_code": "27601", "task": "shared", "submission_month": "2025-07", "resolved_within_window": True}] * 2
                + [{"zip_code": "27601", "task": "rare", "submission_month": "2025-07", "resolved_within_window": False}] * 3
                + [{"zip_code": "27602", "task": "shared", "submission_month": "2025-07", "resolved_within_window": False}] * 5
                + [{"zip_code": "27602", "task": "rare", "submission_month": "2025-07", "resolved_within_window": True}] * 4)
        result = compare_zip(pd.DataFrame(rows), "27601")
        self.assertEqual(result["focal_requests"], 5)
        self.assertEqual(result["comparable_focal_requests"], 2)
        self.assertEqual(result["coverage"], 0.4)
        self.assertEqual(result["gap_pp"], 100)
        self.assertIsNone(compare_zip(pd.DataFrame(rows), "99999")["gap_pp"])

    def test_middle_income_zips_are_not_lost_in_location_screen(self):
        income = pd.DataFrame({"zip_code": ["27601", "27602", "27603"], "median_income": [50000, 70000, 100000]})
        requests = pd.DataFrame({"zip_code": ["27602"], "Submittal Date": ["2025-07-02T00:00:00Z"],
                                 "Resolved At": [None], "service": ["Tree Service"], "request_type": [None]})
        args = (requests, income, "2026-11-10T00:00:00Z", "2025-07-01T00:00:00Z", "2026-01-01T00:00:00Z")
        self.assertEqual(len(prepare_cohort(*args)), 0)
        result = prepare_cohort(*args, include_middle=True)
        self.assertEqual(result.income_group.tolist(), ["Middle"])


if __name__ == "__main__":
    unittest.main()
