"""Offline checks for source-to-CSV conversions: python3 -m unittest."""

import unittest

from refresh_data import income_rows, request_row


class RefreshDataTests(unittest.TestCase):
    def test_dates_aliases_and_missing_geometry(self):
        fields = [{"name": "DATE", "alias": "Submittal Date", "type": "esriFieldTypeDate"},
                  {"name": "HOURS", "alias": "Hours to Resolve", "type": "esriFieldTypeDouble"}]
        row = request_row({"attributes": {"DATE": 0, "HOURS": None}}, fields)
        self.assertEqual(row["Submittal Date"], "1970-01-01T00:00:00+00:00")
        self.assertIsNone(row["Hours to Resolve"])
        self.assertIsNone(row["x"])

    def test_zcta_scope_and_suppressed_estimates(self):
        text = ("GEO_ID|B19013_E001|B19013_M001\n"
                "860Z200US27601|80000|5000\n"
                "860Z200US27602|-666666666|*****\n"
                "860Z200US27603|90000|6000\n"
                "0400000US37|70000|100\n")
        rows = income_rows(text, {"27601", "27602"})
        self.assertEqual([r["Zip Code"] for r in rows], ["27601", "27602"])
        self.assertEqual(rows[0]["Median Income"], 80000)
        self.assertEqual(rows[0]["Margin of Error"], 5000)
        self.assertEqual(rows[1]["Median Income"], "")
        self.assertEqual(rows[1]["Margin of Error"], "")

    def test_duplicate_zctas_rejected(self):
        text = "GEO_ID|B19013_E001|B19013_M001\n" + "860Z200US27601|80000|5000\n" * 2
        with self.assertRaises(ValueError):
            income_rows(text, {"27601"})


if __name__ == "__main__":
    unittest.main()
