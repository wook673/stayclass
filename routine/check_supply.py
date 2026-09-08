# -*- coding: utf-8 -*-
"""check_supply.py — city_rotation.json 의 bbox 로 33m2 공급이 실제로 잡히는지 확인.

  python routine/check_supply.py "서울 강남구" "경기 김포시" "경기 가평군" [--tiles 3]

지역 bbox 를 큰 타일 몇 개로 나눠 지도 API 를 호출하고, 상시 지침 필터
(오피스텔 + 원룸, 고시원·모텔 등 제외)를 적용한 잔존 매물 수를 센다.
min_supply_rooms(기본 10) 미만이면 '공급 부족 → 스킵' 판정을 출력한다.
요청 간 1초 스로틀. 열람 전용.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "market-analyzer"))
import m33  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROTATION = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "city_rotation.json")
PAGE_SIZE = 50
MAX_PAGES = 3               # 타일당 최대 페이지(소규모 확인용)


def fetch_tile(sw_lat, sw_lng, ne_lat, ne_lng, seen, calls):
    page = 1
    while page <= MAX_PAGES:
        r = requests.get(m33.MAP_URL, params=dict(
            swLat=sw_lat, swLng=sw_lng, neLat=ne_lat, neLng=ne_lng,
            page=page, size=PAGE_SIZE), headers=m33._HEADERS, timeout=20)
        r.encoding = "utf-8"
        calls[0] += 1
        data = r.json().get("data") or {}
        content = data.get("content") or []
        for it in content:
            rid = it.get("rid")
            if rid is not None:
                seen[rid] = it
        time.sleep(1.0)
        if data.get("last", True) or not content:
            return data.get("last", True)
        page += 1
    return False                # 페이지 상한에 걸림(더 있음)


def apply_filter(items):
    kept = excl_type = excl_multi = 0
    for it in items:
        ptype = (it.get("propertyType") or "").strip()
        name = it.get("roomName") or ""
        if any(x in ptype for x in m33._EXCLUDE_TYPES) or any(
                x in name for x in m33._EXCLUDE_TYPES):
            excl_type += 1
            continue
        if ptype != m33.KEEP_TYPE:
            excl_type += 1
            continue
        if m33._MULTIROOM_RE.search(name) or (it.get("roomCnt") or 1) > 1:
            excl_multi += 1
            continue
        kept += 1
    return kept, excl_type, excl_multi


def tiles_of(b, n):
    """bbox 를 n개 세로 스트립으로 분할(소규모 호출용)."""
    out = []
    step = (b["neLng"] - b["swLng"]) / n
    for i in range(n):
        out.append((b["swLat"], b["swLng"] + i * step,
                    b["neLat"], b["swLng"] + (i + 1) * step))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("labels", nargs="+")
    ap.add_argument("--tiles", type=int, default=3)
    a = ap.parse_args()

    with open(ROTATION, encoding="utf-8") as f:
        d = json.load(f)
    idx = {c["label"]: c for c in d["cities"]}
    thr = d.get("min_supply_rooms", 10)

    for label in a.labels:
        c = idx.get(label)
        if not c:
            print(f"{label}: 순환표에 없음"); continue
        seen, calls, complete = {}, [0], True
        for t in tiles_of(c["bbox"], a.tiles):
            if not fetch_tile(*t, seen, calls):
                complete = False
        kept, ex_t, ex_m = apply_filter(seen.values())
        verdict = ("공급 부족 → 스킵" if kept < thr else "조사 진행")
        note = "" if complete else "  (페이지 상한 도달 — 실제는 더 많음)"
        print(f"{label:10s} 타일 {a.tiles}개 · 호출 {calls[0]}콜 · 원천 {len(seen)}건 "
              f"→ 필터 후 {kept}실 (유형제외 {ex_t} / 멀티룸제외 {ex_m}) "
              f"· 기준 {thr}실 → {verdict}{note}")


if __name__ == "__main__":
    main()
