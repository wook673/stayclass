# -*- coding: utf-8 -*-
"""build_rotation.py — 서울 25개 자치구 + 경기 31개 시·군 = 56지역 순환표 생성.

OSM Nominatim으로 각 지역의 boundingbox를 조회해 캐시하고,
서울·경기를 번갈아 섞은 고정 배열로 routine/city_rotation.json 을 재작성한다.

  python routine/build_rotation.py --fetch    # Nominatim 조회 → bbox 캐시 갱신
  python routine/build_rotation.py --write    # 캐시로 city_rotation.json 재작성(백업 남김)
  python routine/build_rotation.py --verify   # 스키마·bbox·날짜·next_index 검증

Nominatim 이용약관 준수: User-Agent 명시, 요청 간 1.3초(>=1.1초) 스로틀.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import time

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROTATION = os.path.join(HERE, "city_rotation.json")
CACHE = os.path.join(HERE, "bbox_cache.json")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = {"User-Agent": "danielstay-routine/1.0 (market research; wook910123@gmail.com)"}
THROTTLE = 1.3          # >= 1.1초 (Nominatim 정책)

INTERVAL_DAYS = 3
MIN_REVISIT_DAYS = 45

# --------------------------------------------------------------------------- #
# 지역 목록 — 지리적 편중을 피하려 각 광역을 두 그룹으로 나눠 번갈아 배치한다.
# --------------------------------------------------------------------------- #
SEOUL_NORTH = ["종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구",
               "성북구", "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구"]
SEOUL_SOUTH = ["양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구",
               "서초구", "강남구", "송파구", "강동구"]

GG_SOUTH = ["수원시", "성남시", "안양시", "부천시", "광명시", "평택시", "안산시",
            "과천시", "오산시", "시흥시", "군포시", "의왕시", "하남시", "용인시",
            "이천시", "안성시", "화성시", "광주시", "여주시"]
GG_NORTH = ["의정부시", "동두천시", "고양시", "구리시", "남양주시", "파주시", "김포시",
            "양주시", "포천시", "연천군", "가평군", "양평군"]

# 이관: 기존 history 2건
MIGRATED = {"수원시": "2026-08-21", "용인시": "2026-08-25"}
# 배열 선두에 고정(이미 조사됨 → next_index 는 그 다음부터)
HEAD = ["수원시", "용인시"]

# Nominatim 조회 실패 시 사용할 수동 근사 bbox (필요할 때만 채워진다)
APPROX = {}


def _zip_alternate(a: list, b: list) -> list:
    """두 목록을 길이 비율에 맞춰 고르게 섞는다(한쪽이 몰리지 않게)."""
    out, ia, ib = [], 0, 0
    na, nb = len(a), len(b)
    while ia < na or ib < nb:
        # 진행률이 낮은 쪽에서 하나 꺼낸다
        pa = ia / na if na else 2.0
        pb = ib / nb if nb else 2.0
        if pa <= pb and ia < na:
            out.append(a[ia]); ia += 1
        elif ib < nb:
            out.append(b[ib]); ib += 1
        else:
            out.append(a[ia]); ia += 1
    return out


def build_order() -> list:
    """(region, name) 56개 고정 배열."""
    seoul = [("서울", n) for n in _zip_alternate(SEOUL_NORTH, SEOUL_SOUTH)]
    gg = [("경기", n) for n in _zip_alternate(GG_SOUTH, GG_NORTH)]
    merged = _zip_alternate(gg, seoul)          # 경기 31 + 서울 25 를 고르게 교차
    head = [x for h in HEAD for x in merged if x[1] == h]
    rest = [x for x in merged if x[1] not in HEAD]
    return head + rest


def query_of(region: str, name: str) -> str:
    return ("서울특별시 " if region == "서울" else "경기도 ") + name


# --------------------------------------------------------------------------- #
# 1) Nominatim 조회 → 캐시
# --------------------------------------------------------------------------- #
def fetch_bbox(q: str, expect: str) -> tuple:
    """(bbox dict | None, display_name)."""
    try:
        r = requests.get(NOMINATIM, params={
            "q": q, "format": "json", "countrycodes": "kr",
            "limit": 3, "addressdetails": 0}, headers=UA, timeout=20)
        arr = r.json()
    except (ValueError, requests.RequestException) as e:
        print(f"    ! 요청 실패: {e}")
        return None, ""
    for g in arr:
        disp = g.get("display_name", "")
        if expect and expect not in disp:
            continue
        s, n, w, e2 = (float(x) for x in g["boundingbox"])
        return {"swLat": round(s, 6), "swLng": round(w, 6),
                "neLat": round(n, 6), "neLng": round(e2, 6)}, disp
    if arr:                                     # expect 불일치지만 후보는 있음
        g = arr[0]
        s, n, w, e2 = (float(x) for x in g["boundingbox"])
        return {"swLat": round(s, 6), "swLng": round(w, 6),
                "neLat": round(n, 6), "neLng": round(e2, 6)}, \
            "(불일치)" + g.get("display_name", "")
    return None, ""


def cmd_fetch():
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    order = build_order()
    for i, (region, name) in enumerate(order, 1):
        key = f"{region} {name}"
        if key in cache and cache[key].get("bbox"):
            print(f"[{i:2}/56] {key} — 캐시 사용")
            continue
        q = query_of(region, name)
        expect = "서울" if region == "서울" else "경기"
        bbox, disp = fetch_bbox(q, expect)
        time.sleep(THROTTLE)
        if bbox is None and key in APPROX:
            bbox, disp = APPROX[key], "(수동 근사값)"
        src = "approx" if disp.startswith("(수동") else (
            "nominatim_mismatch" if disp.startswith("(불일치)") else "nominatim")
        cache[key] = {"region": region, "name": name, "query": q,
                      "bbox": bbox, "source": src if bbox else "FAILED",
                      "display": disp}
        flag = "OK " if bbox and src == "nominatim" else "?? "
        print(f"[{i:2}/56] {flag}{key} -> {bbox}  {disp[:60]}")
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    bad = [k for k, v in cache.items() if not v.get("bbox")]
    print(f"\n캐시 저장: {CACHE} ({len(cache)}건, 실패 {len(bad)}건)")
    if bad:
        print("실패 지역: " + ", ".join(bad))


# --------------------------------------------------------------------------- #
# 2) city_rotation.json 재작성
# --------------------------------------------------------------------------- #
def cmd_write():
    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)
    old = {}
    if os.path.exists(ROTATION):
        shutil.copy2(ROTATION, ROTATION + ".bak")
        with open(ROTATION, encoding="utf-8") as f:
            old = json.load(f)

    regions = []
    for region, name in build_order():
        c = cache[f"{region} {name}"]
        if not c.get("bbox"):
            raise SystemExit(f"bbox 없음: {region} {name} — --fetch 먼저 완료할 것")
        regions.append({
            "region": region,
            "name": name,
            "label": f"{region} {name}",
            "query": c["query"],
            "bbox": c["bbox"],
            "bbox_source": c["source"],
            "last_scanned": MIGRATED.get(name),
        })

    scanned = [i for i, r in enumerate(regions) if r["last_scanned"]]
    next_index = (max(scanned) + 1) % len(regions) if scanned else 0

    data = {
        "schema": 2,
        "updated_at": datetime.date.today().isoformat(),
        "scope": "서울특별시 25개 자치구 + 경기도 31개 시·군",
        "interval_days": INTERVAL_DAYS,
        "min_revisit_days": MIN_REVISIT_DAYS,
        "cycle_days": INTERVAL_DAYS * len(regions),
        "min_supply_rooms": 10,
        "max_regions_per_run": 3,
        "notes": [
            "cities[] 는 고정 순서 배열이다. next_index 가 이번 회차 대상.",
            "last_scanned 가 min_revisit_days 이내면 건너뛰고 다음 지역으로.",
            "필터 후 매물 10실 미만이면 '공급 부족'으로 기록·last_scanned 갱신 후 다음 지역.",
            "한 회차 최대 max_regions_per_run 개 지역까지 시도.",
            "bbox_source=approx 는 Nominatim 실패로 수동 근사값을 넣은 지역.",
        ],
        "cities": regions,
        "next_index": next_index,
        "history": old.get("history", []),
    }
    with open(ROTATION, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"작성 완료: {ROTATION}")
    print(f"  지역 {len(regions)}개 / 주기 {data['cycle_days']}일 / "
          f"next_index={next_index} -> {regions[next_index]['label']}")


# --------------------------------------------------------------------------- #
# 3) 검증
# --------------------------------------------------------------------------- #
def cmd_verify():
    with open(ROTATION, encoding="utf-8") as f:
        d = json.load(f)
    errs, warns = [], []
    cities = d["cities"]
    if len(cities) != 56:
        errs.append(f"지역 수 {len(cities)} != 56")
    names = [c["label"] for c in cities]
    if len(set(names)) != len(names):
        errs.append("중복 지역 존재")
    n_seoul = sum(1 for c in cities if c["region"] == "서울")
    n_gg = sum(1 for c in cities if c["region"] == "경기")
    if (n_seoul, n_gg) != (25, 31):
        errs.append(f"서울 {n_seoul}/25, 경기 {n_gg}/31")

    approx = []
    for c in cities:
        b = c.get("bbox") or {}
        for k in ("swLat", "swLng", "neLat", "neLng"):
            if not isinstance(b.get(k), (int, float)):
                errs.append(f"{c['label']}: bbox.{k} 누락")
        if len(b) == 4 and all(isinstance(b.get(k), (int, float)) for k in
                               ("swLat", "swLng", "neLat", "neLng")):
            if not b["swLat"] < b["neLat"]:
                errs.append(f"{c['label']}: swLat >= neLat")
            if not b["swLng"] < b["neLng"]:
                errs.append(f"{c['label']}: swLng >= neLng")
            if not (33.0 <= b["swLat"] <= 39.0 and 33.0 <= b["neLat"] <= 39.0):
                errs.append(f"{c['label']}: 위도 한반도 범위 밖 {b['swLat']}~{b['neLat']}")
            if not (124.0 <= b["swLng"] <= 132.0 and 124.0 <= b["neLng"] <= 132.0):
                errs.append(f"{c['label']}: 경도 한반도 범위 밖 {b['swLng']}~{b['neLng']}")
            if not (36.5 <= b["swLat"] <= 38.5 and 126.0 <= b["swLng"] <= 128.2):
                warns.append(f"{c['label']}: 수도권 범위 밖일 수 있음")
            span = (b["neLat"] - b["swLat"], b["neLng"] - b["swLng"])
            if span[0] > 1.0 or span[1] > 1.0:
                warns.append(f"{c['label']}: bbox 과대 {span}")
        if c.get("bbox_source") != "nominatim":
            approx.append(f"{c['label']}({c.get('bbox_source')})")
        ls = c.get("last_scanned")
        if ls is not None:
            try:
                datetime.date.fromisoformat(ls)
            except (TypeError, ValueError):
                errs.append(f"{c['label']}: last_scanned 형식 오류 {ls!r}")

    ni = d.get("next_index")
    if not isinstance(ni, int) or not (0 <= ni < len(cities)):
        errs.append(f"next_index 범위 오류: {ni}")
    for k, v in (("interval_days", 3), ("min_revisit_days", 45)):
        if d.get(k) != v:
            errs.append(f"{k} != {v} (현재 {d.get(k)})")
    if d.get("cycle_days") != d.get("interval_days", 0) * len(cities):
        errs.append("cycle_days 불일치")
    for h in d.get("history", []):
        try:
            datetime.date.fromisoformat(h["date"])
        except (KeyError, ValueError):
            errs.append(f"history 날짜 오류: {h.get('date')}")

    print(f"지역 {len(cities)}개 (서울 {n_seoul} / 경기 {n_gg}), "
          f"주기 {d.get('cycle_days')}일, 재방문 금지 {d.get('min_revisit_days')}일")
    print("근사 bbox: " + (", ".join(approx) if approx else "없음 (56개 전부 Nominatim 실측)"))
    print(f"next_index={ni} -> {cities[ni]['label'] if isinstance(ni, int) else '?'}")
    scanned = [f"{c['label']}={c['last_scanned']}" for c in cities if c["last_scanned"]]
    print("last_scanned 보유: " + (", ".join(scanned) or "없음"))
    print(f"\n검증 결과: 오류 {len(errs)}건 / 경고 {len(warns)}건")
    for e in errs:
        print("  [ERR] " + e)
    for w in warns:
        print("  [WARN] " + w)
    return 1 if errs else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.fetch:
        cmd_fetch()
    if a.write:
        cmd_write()
    if a.verify:
        sys.exit(cmd_verify())
    if not (a.fetch or a.write or a.verify):
        ap.print_help()
