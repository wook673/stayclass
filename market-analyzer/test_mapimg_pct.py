# -*- coding: utf-8 -*-
"""mapimg 가동률 표기 정규화 테스트.

회귀 배경: 지도 마커 라벨이 `occ*100` 을 무조건 곱해서, 이미 퍼센트(100.0)로
넘어온 값이 `10000%` 로 찍혔다. normalize_pct/pct_label 가 비율·퍼센트를
모두 안전하게 받아 항상 한 자리 소수 퍼센트로 만든다.

    python market-analyzer/test_mapimg_pct.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mapimg


class TestNormalizePct(unittest.TestCase):
    def test_ratio_input(self):
        self.assertAlmostEqual(mapimg.normalize_pct(0.573), 57.3, places=6)

    def test_percent_input(self):
        self.assertAlmostEqual(mapimg.normalize_pct(57.3), 57.3, places=6)

    def test_boundary_one_is_full(self):
        self.assertAlmostEqual(mapimg.normalize_pct(1.0), 100.0, places=6)

    def test_hundred_stays_hundred(self):
        self.assertAlmostEqual(mapimg.normalize_pct(100), 100.0, places=6)

    def test_zero(self):
        self.assertEqual(mapimg.normalize_pct(0), 0.0)

    def test_none_and_junk(self):
        for bad in (None, "", "abc", float("nan"), float("inf"), -1, -0.5, True):
            self.assertIsNone(mapimg.normalize_pct(bad), bad)

    def test_numeric_string(self):
        self.assertAlmostEqual(mapimg.normalize_pct("0.573"), 57.3, places=6)


class TestPctLabel(unittest.TestCase):
    CASES = [(0.573, "57.3%"), (57.3, "57.3%"), (1.0, "100.0%"),
             (100, "100.0%"), (0.0, "0.0%"), (0.4402, "44.0%"),
             (44.02, "44.0%"), (None, None)]

    def test_cases(self):
        for value, want in self.CASES:
            self.assertEqual(mapimg.pct_label(value), want, value)

    def test_never_10000(self):
        """이중 변환 회귀 가드 — 어떤 입력도 100%를 넘겨 찍히지 않는다."""
        for value in (1.0, 100, 100.0, 0.999, 99.9):
            self.assertLessEqual(float(mapimg.pct_label(value)[:-1]), 100.0, value)


class TestRoomLabel(unittest.TestCase):
    ROOM = {"name": "동탄호수공원/멋진호수뷰"}
    ROOM_EN = {"name": "Dongtan Lake Park / Great Lake View"}

    def test_ko_percent_input(self):
        txt = mapimg._room_label(1, self.ROOM, {"combined": 100.0}, ko=True)
        self.assertTrue(txt.endswith("100.0%"), txt)
        self.assertNotIn("10000", txt)

    def test_ko_ratio_input(self):
        txt = mapimg._room_label(1, self.ROOM, {"combined": 0.573}, ko=True)
        self.assertTrue(txt.endswith("57.3%"), txt)

    def test_en_keeps_name(self):
        txt = mapimg._room_label(2, self.ROOM_EN, {"combined": 55.36}, ko=False)
        self.assertTrue(txt.startswith("#2 Dongtan Lake Park"), txt)
        self.assertTrue(txt.endswith("55.4%"), txt)

    def test_missing_occupancy_omits_pct(self):
        txt = mapimg._room_label(3, self.ROOM_EN, {}, ko=False)
        self.assertNotIn("%", txt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
