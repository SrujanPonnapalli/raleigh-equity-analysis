"""Checks for contrast direction and poverty ties in the specified comparison."""

import unittest

import pandas as pd

from atlas_outcomes import estimate, poverty_groups, published_groups


class AtlasOutcomeTests(unittest.TestCase):
    def test_negative_gap_means_lower_resolution_in_higher_vulnerability(self):
        data = pd.DataFrame({"published_band": [1, 2, 3, 4, 5], "task": ["same"] * 5,
                             "submission_month": ["2025-07"] * 5,
                             "resolved_within_window": [True, True, True, False, False]})
        result = estimate(data, published_groups(data))
        self.assertEqual(result["eligible_lower"], 2)
        self.assertEqual(result["eligible_higher"], 2)
        self.assertEqual(result["gap_pp_higher_minus_lower"], -100)
        self.assertEqual(result["adjusted_rate_higher"], 0)

    def test_poverty_cutoff_ties_stay_together(self):
        data = pd.DataFrame({"POV_RATE": [2, 2, 4, 6, 6]})
        self.assertEqual(poverty_groups(data, 2, 6).tolist(), ["Lower", "Lower", "Middle", "Higher", "Higher"])
        with self.assertRaises(ValueError):
            poverty_groups(data, 2, 2)


if __name__ == "__main__":
    unittest.main()
