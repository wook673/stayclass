# -*- coding: utf-8 -*-
"""m33 선점률 집계 단위테스트 (네트워크 없음).

실행: python -m unittest test_m33_occupancy -v
"""
from __future__ import annotations

import datetime
import unittest

import m33

TODAY = datetime.date(2026, 7, 27)      # 창 고정: [2026-07-27, 2026-09-21)
WINDOW_DAYS = 56                        # 8주


def _envelope(schedules):
    """실제 응답 봉투 모양 {"code":"SCSS_001","data":{contracts,schedules}}."""
    return {"code": "SCSS_001",
            "data": {"contracts": [], "schedules": list(schedules)}}


def _row(date_str, status):
    return {"date": date_str, "status": status}


class MonthsInWindowTest(unittest.TestCase):
    def test_56day_window_spans_three_months(self):
        lo = datetime.date(2026, 7, 27)
        hi = lo + datetime.timedelta(days=56)          # 2026-09-21
        self.assertEqual(m33._months_in_window(lo, hi),
                         [(2026, 7), (2026, 8), (2026, 9)])

    def test_year_boundary(self):
        self.assertEqual(
            m33._months_in_window(datetime.date(2026, 12, 20),
                                  datetime.date(2027, 2, 1)),
            [(2026, 12), (2027, 1)])

    def test_hi_is_exclusive(self):
        # 8월 1일 0시까지 → 8월은 포함되지 않는다.
        self.assertEqual(
            m33._months_in_window(datetime.date(2026, 7, 27),
                                  datetime.date(2026, 8, 1)),
            [(2026, 7)])

    def test_empty_when_hi_not_after_lo(self):
        d = datetime.date(2026, 7, 27)
        self.assertEqual(m33._months_in_window(d, d), [])


class MergeScheduleCountsTest(unittest.TestCase):
    def _merge(self, payloads):
        return m33.merge_schedule_counts(payloads, WINDOW_DAYS,
                                         today=TODAY, window="future")

    def test_three_month_merge_and_window_filter(self):
        july = _envelope([
            _row("2026-07-20", "BOOKING"),   # lo 이전 → 제외
            _row("2026-07-26", "DISABLE"),   # lo 이전 → 제외
            _row("2026-07-27", "BOOKING"),   # lo 당일 → 포함
            _row("2026-07-28", "BOOKING"),
            _row("2026-07-29", "DISABLE"),
            _row("2026-07-30", "AVAILABLE"),
        ])
        august = _envelope([
            _row("2026-08-01", "BOOKING"),
            _row("2026-08-02", "DISABLE"),
            _row("2026-08-15", "AVAILABLE"),
        ])
        september = _envelope([
            _row("2026-09-20", "BOOKING"),   # hi 직전 → 포함
            _row("2026-09-21", "BOOKING"),   # hi 당일 → 제외(불포함)
            _row("2026-09-25", "DISABLE"),   # hi 이후 → 제외
        ])
        c = self._merge([july, august, september])
        self.assertEqual(c["days"], 56)              # 분모는 창 길이 고정
        self.assertEqual(c["booking"], 4)            # 07-27, 07-28, 08-01, 09-20
        self.assertEqual(c["disable"], 2)            # 07-29, 08-02
        # 창 안 8일: 07-27/28/29/30, 08-01/02/15, 09-20 (AVAILABLE 2건 포함)
        self.assertEqual(c["n_in_window"], 8)
        self.assertFalse(c["undated"])

    def test_duplicate_date_counted_once(self):
        july = _envelope([_row("2026-07-31", "BOOKING")])
        august = _envelope([_row("2026-07-31", "BOOKING"),   # 중복
                            _row("2026-08-01", "BOOKING")])
        c = self._merge([july, august])
        self.assertEqual(c["booking"], 2)
        self.assertEqual(c["n_in_window"], 2)
        self.assertEqual(c["days"], 56)

    def test_denominator_fixed_regardless_of_row_count(self):
        # 단 1행만 와도 분모는 56.
        c = self._merge([_envelope([_row("2026-08-03", "BOOKING")])])
        self.assertEqual(c["days"], 56)
        self.assertEqual(c["booking"], 1)

    def test_out_of_window_only(self):
        c = self._merge([_envelope([_row("2026-07-01", "BOOKING"),
                                    _row("2026-11-01", "DISABLE")])])
        self.assertEqual(c["booking"], 0)
        self.assertEqual(c["disable"], 0)
        self.assertEqual(c["days"], 56)
        self.assertEqual(c["n_in_window"], 0)

    def test_undated_fallback(self):
        rows = [{"status": "BOOKING"} for _ in range(60)]
        rows += [{"status": "DISABLE"} for _ in range(5)]
        c = self._merge([_envelope(rows)])
        self.assertTrue(c["undated"])
        self.assertEqual(c["days"], 56)
        self.assertEqual(c["booking"], 56)     # 앞 56개만
        self.assertEqual(c["disable"], 0)
        self.assertEqual(c["n_in_window"], 56)

    def test_alternate_field_names_and_bare_list(self):
        # 'state'/'scheduleDate' 키 + data 래핑 없는 맨 리스트도 처리.
        payload = [{"scheduleDate": "20260805", "state": "block"}]
        c = self._merge([payload])
        self.assertEqual(c["disable"], 1)
        self.assertEqual(c["booking"], 0)

    def test_returns_none_when_no_list_structure(self):
        self.assertIsNone(self._merge([{"code": "VLD_001"}, None]))
        self.assertIsNone(self._merge([]))

    def test_past_window(self):
        # window='past' → [today-56, today)
        payload = _envelope([_row("2026-07-26", "BOOKING"),   # 포함
                             _row("2026-07-27", "BOOKING")])  # today → 제외
        c = m33.merge_schedule_counts([payload], WINDOW_DAYS,
                                      today=TODAY, window="past")
        self.assertEqual(c["booking"], 1)
        self.assertEqual(c["days"], 56)


if __name__ == "__main__":
    unittest.main()
