"""Spatial edge cases. Requires the optional requirements-atlas.txt packages."""

import unittest

import pandas as pd

try:
    from shapely import STRtree
    from shapely.geometry import MultiPolygon, Polygon, box, mapping
    from atlas_pilot import build_index, locate, published_band
except ModuleNotFoundError as error:
    if error.name == "shapely":
        raise unittest.SkipTest("Install requirements-atlas.txt for spatial tests") from error
    raise


class AtlasPilotTests(unittest.TestCase):
    def test_holes_and_multipolygons(self):
        hole = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)], holes=[[(1, 1), (2, 1), (2, 2), (1, 2)]])
        shapes = [hole, MultiPolygon([box(5, 0, 6, 1), box(8, 0, 9, 1)])]
        tree = STRtree(shapes)
        self.assertEqual(locate(0.5, 0.5, shapes, tree), (0, "matched"))
        self.assertEqual(locate(1.5, 1.5, shapes, tree), (None, "outside_atlas"))
        self.assertEqual(locate(8.5, 0.5, shapes, tree), (1, "matched"))

    def test_boundary_and_overlap_are_not_assigned_arbitrarily(self):
        shapes = [box(0, 0, 2, 2), box(1, 1, 3, 3)]
        tree = STRtree(shapes)
        self.assertEqual(locate(1.5, 1.5, shapes, tree), (None, "multiple_or_shared_boundary"))
        self.assertEqual(locate(0, 1, shapes, tree), (None, "boundary"))
        adjacent = [box(0, 0, 1, 1), box(1, 0, 2, 1)]
        self.assertEqual(locate(1, 0.5, adjacent, STRtree(adjacent)), (None, "multiple_or_shared_boundary"))

    def test_missing_invalid_and_distant_points_remain_unmatched(self):
        shapes = [box(0, 0, 1, 1)]
        tree = STRtree(shapes)
        self.assertEqual(locate(None, 0.5, shapes, tree), (None, "missing_coordinates"))
        self.assertEqual(locate(181, 0, shapes, tree), (None, "invalid_coordinates"))
        self.assertEqual(locate(10, 10, shapes, tree), (None, "outside_atlas"))

    def test_duplicate_geographic_keys_and_invalid_geometry_rejected(self):
        feature = {"type": "Feature", "properties": {"GEOID": "371830001001"}, "geometry": mapping(box(0, 0, 1, 1))}
        with self.assertRaisesRegex(ValueError, "unique"):
            build_index([feature, feature])
        feature["geometry"] = mapping(Polygon([(0, 0), (1, 1), (0, 1), (1, 0)]))
        with self.assertRaisesRegex(ValueError, "Invalid"):
            build_index([feature])

    def test_band_boundaries_follow_published_legend(self):
        renderer = {"minValue": 1, "classBreakInfos": [{"classMaxValue": 119}, {"classMaxValue": 238}, {"classMaxValue": 358}]}
        self.assertEqual(published_band(119, renderer), 1)
        self.assertEqual(published_band(120, renderer), 2)
        self.assertIsNone(published_band(0, renderer))
        self.assertIsNone(published_band(359, renderer))
        self.assertIsNone(published_band(pd.NA, renderer))


if __name__ == "__main__":
    unittest.main()
