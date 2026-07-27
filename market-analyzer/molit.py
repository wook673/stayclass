# -*- coding: utf-8 -*-
"""molit.py — 국토교통부 오피스텔 전월세 실거래 수집·밴드 집계.

plan_src/naver_rent.py 의 molit 로직을 이식·개선:
  - UA 필수(게이트웨이 400 Request Blocked 회피)
  - totalCount 기반 페이지네이션
  - 월별 캐시(.cache/molit_{lawd}_{ym}.json) 재사용
  - 전용 ≤33㎡ · 월세>0 · 해당 법정동(umdNm) 필터
  - 보증금 밴드 분리(500=300~700 / 1000=700초과~1300, 환산 금지)
  - 표본<3 밴드는 "표본 부족(n)" (추정 금지)
"""
from __future__ import annotations

import json
import os
import statistics
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests

from config import (
    MOLIT_KEY_FILE, CACHE_DIR, MAX_AREA_SQM, BAND_500, BAND_1000,
    MIN_BAND_SAMPLES,
)

MOLIT_OFFI_RENT = ("https://apis.data.go.kr/1613000/RTMSDataSvcOffiRent/"
                   "getRTMSDataSvcOffiRent")
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Accept": "application/xml,*/*"}
_THROTTLE = 0.3


def load_service_key(key: Optional[str] = None) -> str:
    if key:
        return key.strip()
    try:
        with open(MOLIT_KEY_FILE, encoding="utf-8") as f:
            k = f.read().strip()
        if k:
            return k
    except OSError:
        pass
    raise RuntimeError(f"MOLIT 서비스키 없음 — {MOLIT_KEY_FILE} 파일 필요")


def _to_f(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _cache_path(lawd: str, ym: str) -> str:
    return os.path.join(CACHE_DIR, f"molit_{lawd}_{ym}.json")


def _fetch_month(service_key: str, lawd: str, ym: str, use_cache=True) -> list:
    """월 단위 오피스텔 전월세 원자료(캐시 우선). raw dict 리스트 반환."""
    cp = _cache_path(lawd, ym)
    if use_cache and os.path.exists(cp):
        try:
            with open(cp, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    out, page = [], 1
    while True:
        r = requests.get(MOLIT_OFFI_RENT, params=dict(
            serviceKey=service_key, LAWD_CD=str(lawd), DEAL_YMD=str(ym),
            numOfRows=1000, pageNo=page), headers=_UA, timeout=25)
        if r.status_code == 400 and "Request Blocked" in r.text:
            raise RuntimeError("data.go.kr 400 Request Blocked — UA 헤더 문제")
        if r.status_code == 401:
            raise RuntimeError("data.go.kr 401 — 서비스키 미승인/오타")
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            raise RuntimeError(f"MOLIT 응답 파싱 실패: {r.text[:160]}")
        rc = root.findtext(".//resultCode")
        if rc not in (None, "00", "000"):
            raise RuntimeError(f"MOLIT resultCode={rc}: "
                               f"{root.findtext('.//resultMsg')}")
        total = int(root.findtext(".//totalCount") or 0)
        for it in root.iter("item"):
            g = lambda *n: next((it.findtext(x).strip() for x in n
                                 if it.findtext(x)), None)
            out.append({
                "dong": g("umdNm", "법정동"),
                "deposit": _to_f(g("deposit", "보증금액")),
                "rent": _to_f(g("monthlyRent", "월세금액")),
                "area": _to_f(g("excluUseAr", "전용면적")),
                "offi": g("offiNm", "단지"),
                "floor": g("floor", "층"),
                "ymd": f"{g('dealYear','년')}-{g('dealMonth','월')}-{g('dealDay','일')}",
            })
        if page * 1000 >= total:
            break
        page += 1
        time.sleep(_THROTTLE)
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    return out


def recent_yyyymm(months: int, today=None) -> list:
    """최근 months개월 YYYYMM 리스트(과거→현재). today=(y,m) 테스트용."""
    import datetime
    if today is None:
        d = datetime.date.today()
        y, m = d.year, d.month
    else:
        y, m = today
    res = []
    for _ in range(months):
        res.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(res))


def collect(service_key: str, lawd: str, dongs, months: int,
            use_cache=True, today=None) -> dict:
    """법정동 필터 + 전용 ≤33㎡ + 월세>0 → 밴드별 집계.

    반환:
      {
        "months": [...], "lawd": ..., "dongs": [...],
        "n_raw": 전체 원자료 수, "n_filtered": 필터 후 월세건 수,
        "bands": { "500": band_dict, "1000": band_dict },
        "rows": [필터 후 행...]   # 리포트 상세용
      }
    band_dict: {"n":.., "rent_median":.., "rent_min":.., "rent_max":..,
                "deposit_median":.., "sufficient": bool, "note": str}
    """
    yms = recent_yyyymm(months, today=today)
    raw = []
    for ym in yms:
        raw += _fetch_month(service_key, lawd, ym, use_cache=use_cache)
        time.sleep(_THROTTLE if not use_cache else 0)
    dongset = set(dongs)
    sel = [r for r in raw
           if r["dong"] in dongset and r["area"] is not None
           and r["area"] <= MAX_AREA_SQM and r["rent"] and r["rent"] > 0]

    def band(lo, hi, hi_exclusive_lo=False):
        rows = [r for r in sel
                if r["deposit"] is not None
                and (lo <= r["deposit"] <= hi if not hi_exclusive_lo
                     else lo < r["deposit"] <= hi)]
        rents = [r["rent"] for r in rows]
        deps = [r["deposit"] for r in rows]
        n = len(rents)
        if n < MIN_BAND_SAMPLES:
            return {"n": n, "rent_median": None, "rent_min": None,
                    "rent_max": None, "deposit_median": None,
                    "sufficient": False, "note": f"표본 부족({n})", "rows": rows}
        return {"n": n,
                "rent_median": round(statistics.median(rents), 1),
                "rent_min": round(min(rents), 1),
                "rent_max": round(max(rents), 1),
                "deposit_median": round(statistics.median(deps), 1),
                "sufficient": True, "note": "", "rows": rows}

    # 500밴드: 300~700 포함 / 1000밴드: 700 초과~1300 (경계 700은 500에 귀속)
    b500 = band(BAND_500[0], BAND_500[1])
    b1000 = band(BAND_1000[0], BAND_1000[1], hi_exclusive_lo=True)
    return {
        "months": yms, "lawd": lawd, "dongs": list(dongs),
        "n_raw": len(raw), "n_filtered": len(sel),
        "bands": {"500": b500, "1000": b1000},
        "rows": sel,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="MOLIT 오피스텔 전월세 밴드 집계")
    ap.add_argument("--lawd", required=True)
    ap.add_argument("--dong", nargs="+", required=True)
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    key = load_service_key()
    res = collect(key, a.lawd, a.dong, a.months, use_cache=not a.no_cache)
    print(f"LAWD {a.lawd} {a.dong} months={res['months']}")
    print(f"원자료 {res['n_raw']} → 필터(≤33㎡·월세건·해당동) {res['n_filtered']}")
    for k, b in res["bands"].items():
        print(f"  {k}밴드: n={b['n']} 월세중위={b['rent_median']} "
              f"(min {b['rent_min']}/max {b['rent_max']}) "
              f"보증금중위={b['deposit_median']} {b['note']}")
