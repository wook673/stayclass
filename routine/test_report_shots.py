# -*- coding: utf-8 -*-
"""Unit tests for the browser-free logic in report_shots.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from report_shots import choose_crop_line  # noqa: E402


def b(label, top, bottom=None, kind="sec-num"):
    return {"label": label, "top": top,
            "bottom": bottom if bottom is not None else top + 100,
            "kind": kind}


class TestChooseCropLine(unittest.TestCase):

    # --- label match -----------------------------------------------------

    def test_matches_boundary_label(self):
        bounds = [b("03", 500), b("04", 1800), b("05", 3000)]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 1800)

    def test_label_match_wins_over_midpoint(self):
        """A label match is used even when it sits above the page midpoint."""
        bounds = [b("03", 200), b("04", 400), b("05", 3500)]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 400)

    def test_sec_num_preferred_over_section_with_same_label(self):
        bounds = [
            {"label": "04", "top": 1700, "bottom": 4000, "kind": "section"},
            {"label": "04", "top": 1760, "bottom": 3900, "kind": "sec-num"},
        ]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 1760)

    def test_first_of_duplicate_labels(self):
        bounds = [b("04", 1200), b("04", 2600)]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 1200)

    def test_label_whitespace_tolerated(self):
        bounds = [b("03", 300), b(" 04 ", 1500)]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 1500)

    # --- fallback: nearest boundary below the midpoint --------------------

    def test_fallback_nearest_below_midpoint(self):
        bounds = [b("01", 100), b("02", 900), b("03", 2100), b("05", 3300)]
        # midpoint 2000 -> first boundary at or below it is 2100
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 2100)

    def test_fallback_boundary_exactly_at_midpoint(self):
        bounds = [b("01", 100), b("02", 2000), b("03", 3500)]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 2000)

    def test_fallback_uses_last_boundary_when_all_above_midpoint(self):
        bounds = [b("01", 100), b("02", 400), b("03", 800)]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 800)

    def test_zero_and_full_height_boundaries_ignored_in_fallback(self):
        bounds = [b("01", 0), b("02", 4000), b("03", 2400)]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 2400)

    # --- degenerate cases -------------------------------------------------

    def test_single_section_at_origin_falls_back_to_midpoint(self):
        bounds = [b("01", 0, 4000, kind="section")]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 2000)

    def test_single_section_with_label_match_still_clamped(self):
        """A label match at y=0 must not produce an empty first page."""
        bounds = [b("04", 0, 4000)]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 1)

    def test_no_boundaries_at_all(self):
        self.assertEqual(choose_crop_line([], 3000, "04"), 1500)
        self.assertEqual(choose_crop_line(None, 3000, "04"), 1500)

    def test_line_clamped_below_page_height(self):
        bounds = [b("04", 9999)]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 3999)

    def test_result_always_yields_two_nonempty_pages(self):
        for bounds, h in [([], 10), ([b("04", 0)], 10), ([b("04", 10)], 10),
                          ([b("03", 3)], 10)]:
            line = choose_crop_line(bounds, h, "04")
            self.assertGreater(line, 0, bounds)
            self.assertLess(line, h, bounds)

    def test_empty_boundary_label_forces_fallback(self):
        bounds = [b("04", 300), b("05", 2600)]
        self.assertEqual(choose_crop_line(bounds, 4000, ""), 2600)

    def test_items_missing_top_are_skipped(self):
        bounds = [{"label": "04", "kind": "sec-num"}, b("05", 2500)]
        self.assertEqual(choose_crop_line(bounds, 4000, "04"), 2500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
