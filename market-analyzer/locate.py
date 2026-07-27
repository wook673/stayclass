# -*- coding: utf-8 -*-
"""locate.py — 지역명 자유 입력 → 좌표·법정동·LAWD 자동 해석(외부 API 키 없이).

파이프라인(사전에 없는 지역):
  1. 지역명 → 좌표 : OSM Nominatim(키 불필요) 지오코딩. 실패 시 폴백.
  2. 좌표 → 시군구/법정동 : 반경 내 33m2 매물 주소필드(town/province) 최빈값.
  3. 시군구 → LAWD(5자리) : 행안부 법정동코드 1회 다운로드(.cache/lawd.csv) →
       실패 시 경기남부 하드코딩 테이블 폴백.
  4. 법정동 검증·대체 : MOLIT 수집 후 33m2 표본 단지명을 MOLIT 단지명에 역매칭 →
       최빈동에 ≤33㎡ 월세 표본이 부족하면 매칭되는 동으로 자동 대체
       (동탄 오산동→여울동 사례의 자동화). 근거 문자열을 리포트에 기재.

stations.py 사전은 빠른 경로(단축어)로 유지되고, 사전에 없을 때만 이 경로가 돈다.
"""
from __future__ import annotations

import csv
import math
import os
import re
import time
from collections import Counter, defaultdict
from typing import Optional

import requests

import molit
from config import CACHE_DIR, MAX_AREA_SQM, MIN_BAND_SAMPLES

_UA = {"User-Agent": "market-analyzer/2.0 (danielstay research; contact via repo)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"
MAP_URL = "https://web.33m2.co.kr/v1/use-auth/map/rooms"
_M33_H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
          "Referer": "https://web.33m2.co.kr/"}
LAWD_CSV = os.path.join(CACHE_DIR, "lawd.csv")

# 행안부 법정동코드 전체자료 공개 URL 후보(다운로드 성공 시 .cache/lawd.csv 로 저장).
# 접근 실패해도 하드코딩 테이블로 폴백하므로 파이프라인은 죽지 않는다.
_LAWD_DOWNLOAD_URLS = (
    "https://raw.githubusercontent.com/pmj0203/legaldongcode/main/legaldong.csv",
)

# 경기남부 시군구 → LAWD(5자리) 하드코딩 폴백 (MOLIT 실증 확인 코드 포함).
# 키는 33m2 province 필드 표기(시군구명)와 매칭.
SIGUNGU_LAWD = {
    "수원시 장안구": "41111", "수원시 권선구": "41113",
    "수원시 팔달구": "41115", "수원시 영통구": "41117",
    "성남시 수정구": "41131", "성남시 중원구": "41133",
    "성남시 분당구": "41135",
    "안양시 만안구": "41171", "안양시 동안구": "41173",
    "부천시": "41190", "광명시": "41210", "평택시": "41220",
    "안산시 상록구": "41271", "안산시 단원구": "41273",
    "오산시": "41370", "시흥시": "41390", "군포시": "41410",
    "의왕시": "41430", "하남시": "41450",
    "용인시 처인구": "41461", "용인시 기흥구": "41463",
    "용인시 수지구": "41465",
    "이천시": "41500", "안성시": "41550",
    "화성시 동탄구": "41597", "화성시": "41590",
    "광주시": "41610", "여주시": "41670",
}


class LocateError(RuntimeError):
    """자동 위치 해석 실패."""


# --------------------------------------------------------------------------- #
# 1) 지역명 → 좌표 (Nominatim, 키 불필요)
# --------------------------------------------------------------------------- #
def geocode(name: str) -> Optional[dict]:
    """지역명 → {lat, lon, display, source}. 실패 시 None.

    경기남부 조사 맥락상 국내(kr)로 한정. 역명/동명/주소 모두 허용.
    Nominatim 이용약관(1req/s) 준수.
    """
    q = name.strip()
    if not q:
        return None
    for query in (q, f"{q} 경기도"):
        try:
            r = requests.get(NOMINATIM, params={
                "q": query, "format": "json", "countrycodes": "kr",
                "limit": 1, "addressdetails": 0}, headers=_UA, timeout=15)
            time.sleep(1.0)   # Nominatim 예의상 스로틀
            arr = r.json()
        except (ValueError, requests.RequestException):
            arr = []
        if arr:
            g = arr[0]
            return {"lat": float(g["lat"]), "lon": float(g["lon"]),
                    "display": g.get("display_name", ""), "source": "nominatim"}
    return None


# --------------------------------------------------------------------------- #
# 2) 좌표 → 33m2 주소 분포(town/province)
# --------------------------------------------------------------------------- #
def _bbox(lat, lon, radius_m):
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def scan_addresses(lat: float, lon: float, radius_m: float = 500) -> dict:
    """반경 내 33m2 매물의 town(법정동)·province(시군구) 분포 + 단지명 후보.

    반환: {"towns": Counter, "provinces": Counter, "complexes": set,
           "n": 매물수}
    """
    sw_lat, sw_lon, ne_lat, ne_lon = _bbox(lat, lon, radius_m)
    towns, provinces, complexes = Counter(), Counter(), set()
    n = 0
    try:
        r = requests.get(MAP_URL, params=dict(
            swLat=sw_lat, swLng=sw_lon, neLat=ne_lat, neLng=ne_lon,
            page=1, size=50), headers=_M33_H, timeout=20)
        content = (r.json().get("data") or {}).get("content") or []
    except (ValueError, requests.RequestException):
        content = []
    for it in content:
        t = it.get("town")
        p = it.get("province")
        if t:
            towns[t] += 1
        if p:
            provinces[p] += 1
        cx = _complex_from_addr(it.get("addrLot"))
        if cx:
            complexes.add(cx)
        n += 1
    return {"towns": towns, "provinces": provinces,
            "complexes": complexes, "n": n}


def _complex_from_addr(addr: Optional[str]) -> Optional[str]:
    """33m2 addrLot 에서 단지명 토큰 추출(마지막 한글 명칭). 지번/행정구역 제거."""
    if not addr:
        return None
    parts = addr.split()
    drop = ("경기도", "서울특별시", "인천광역시")
    toks = [p for p in parts
            if not re.match(r"^[0-9\-]+$", p) and p not in drop]
    # 시/구/동 3토큰 이후를 단지명으로 간주
    tail = toks[3:] if len(toks) > 3 else toks[-1:]
    name = " ".join(tail).strip()
    return name or None


# --------------------------------------------------------------------------- #
# 3) 시군구 → LAWD (다운로드 1회 → 폴백 하드코딩)
# --------------------------------------------------------------------------- #
def ensure_lawd_table() -> dict:
    """.cache/lawd.csv 를 확보(없으면 다운로드 시도) 후 {시군구명: lawd5} 로드.

    다운로드 실패해도 하드코딩 SIGUNGU_LAWD 를 항상 병합해 반환하므로 안전.
    """
    table = dict(SIGUNGU_LAWD)
    if not os.path.exists(LAWD_CSV):
        _try_download_lawd()
    if os.path.exists(LAWD_CSV):
        try:
            with open(LAWD_CSV, encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) >= 2 and re.match(r"^\d{5}$", row[0].strip()):
                        table.setdefault(row[1].strip(), row[0].strip())
        except OSError:
            pass
    return table


def _try_download_lawd():
    """행안부 법정동코드 다운로드 → 시군구 단위로 축약해 .cache/lawd.csv 저장.

    형식 다양성 방어: '코드,시도,시군구,읍면동...' 또는 '10자리코드\t명칭' 등.
    실패는 조용히 무시(하드코딩 폴백).
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    for url in _LAWD_DOWNLOAD_URLS:
        try:
            r = requests.get(url, headers=_UA, timeout=20)
            if r.status_code != 200 or len(r.text) < 500:
                continue
            rows = _parse_lawd_dump(r.text)
            if rows:
                with open(LAWD_CSV, "w", encoding="utf-8", newline="") as f:
                    csv.writer(f).writerows(rows)
                return True
        except requests.RequestException:
            continue
    return False


def _parse_lawd_dump(text: str) -> list:
    """법정동 덤프 텍스트 → [(lawd5, 시군구명)] 축약(폐지동 제외 최선노력)."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        cells = re.split(r"[\t,]", line)
        code = cells[0].strip()
        if not re.match(r"^\d{10}$", code):
            continue
        # 시군구 = 코드 앞 5자리, 명칭 = 시도+시군구 (읍면동 없는 행)
        names = [c.strip() for c in cells[1:] if c.strip()]
        joined = " ".join(names)
        # '경기도 성남시 분당구' 처럼 3토큰 이하 = 시군구 레벨
        toks = joined.split()
        if 2 <= len(toks) <= 3 and code[5:] == "00000":
            sigungu = " ".join(toks[1:])
            out.setdefault(code[:5], sigungu)
    return [(c, n) for c, n in out.items()]


def resolve_lawd(province: str, table: Optional[dict] = None) -> Optional[str]:
    """33m2 province(시군구명) → LAWD5. 완전일치 → 부분일치 순."""
    if not province:
        return None
    tbl = table or ensure_lawd_table()
    p = province.strip()
    if p in tbl:
        return tbl[p]
    # 부분일치(예: 'ㅇㅇ시 ㅇㅇ구' 표기 차이)
    for k, v in tbl.items():
        if k in p or p in k:
            return v
    # 시(구 없는) 단위만 매칭
    si = p.split()[0]
    for k, v in tbl.items():
        if k.split()[0] == si:
            return v
    return None


# --------------------------------------------------------------------------- #
# 4) 법정동 결정·검증 (단지명 역매칭 → 대체 동 자동)
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def resolve_dong(service_key: str, lawd: str, towns: Counter,
                 complexes: set, months: int, use_cache=True) -> dict:
    """LAWD 내에서 분석에 쓸 법정동 결정 + 근거.

    로직:
      A. LAWD 전체 원자료 수집 → 동별 ≤33㎡ 월세 표본수·단지명 집합.
      B. 33m2 최빈동이 충분한 표본을 가지면 그 동 채택.
      C. 부족하면 33m2 표본 단지명이 MOLIT에서 실거래된 동으로 대체(역매칭).
      D. 그래도 없으면 ≤33㎡ 표본이 가장 두터운 동 채택.
    반환: {"dongs":[..], "method": str, "evidence": str, "candidates": {...}}
    """
    raw = []
    for ym in molit.recent_yyyymm(months):
        raw += molit._fetch_month(service_key, lawd, ym, use_cache=use_cache)
    # 동별 ≤33㎡ 월세 표본수 + 단지명
    per_dong_n = defaultdict(int)
    per_dong_cx = defaultdict(set)
    for r in raw:
        if (r["area"] is not None and r["area"] <= MAX_AREA_SQM
                and r["rent"] and r["rent"] > 0):
            per_dong_n[r["dong"]] += 1
            if r["offi"]:
                per_dong_cx[r["dong"]].add(r["offi"])
    candidates = dict(sorted(per_dong_n.items(), key=lambda x: -x[1]))

    mode_dong = towns.most_common(1)[0][0] if towns else None

    # B. 최빈동 충분?
    if mode_dong and per_dong_n.get(mode_dong, 0) >= max(MIN_BAND_SAMPLES, 5):
        return {"dongs": [mode_dong], "method": "mode",
                "evidence": (f"33m2 주소 최빈 법정동 '{mode_dong}' 채택 "
                             f"(MOLIT ≤33㎡ 월세 표본 {per_dong_n[mode_dong]}건)."),
                "candidates": candidates}

    # C. 단지명 역매칭
    match_scores = Counter()
    for dong, cxset in per_dong_cx.items():
        for sc in complexes:
            n_sc = _norm(sc)
            if not n_sc:
                continue
            for oc in cxset:
                n_oc = _norm(oc)
                if n_sc and (n_sc in n_oc or n_oc in n_sc):
                    match_scores[dong] += 1
                    break
    if match_scores:
        best, score = match_scores.most_common(1)[0]
        matched_cx = sorted(
            {sc for sc in complexes for oc in per_dong_cx[best]
             if _norm(sc) and (_norm(sc) in _norm(oc) or _norm(oc) in _norm(sc))})
        note = ""
        if mode_dong and mode_dong != best:
            note = (f"33m2 최빈동 '{mode_dong}'은 MOLIT ≤33㎡ 월세 표본 부족"
                    f"({per_dong_n.get(mode_dong,0)}건) → ")
        return {"dongs": [best], "method": "complex_match",
                "evidence": (note + f"33m2 표본 단지({', '.join(matched_cx[:3])})가 "
                             f"MOLIT에서 '{best}'에 실거래 → '{best}' 대체 채택"
                             f"(≤33㎡ 표본 {per_dong_n.get(best,0)}건, 단지 역매칭 {score}건)."),
                "candidates": candidates}

    # D. 표본 최다 동
    if candidates:
        best = next(iter(candidates))
        return {"dongs": [best], "method": "richest",
                "evidence": (f"33m2 최빈동 표본 부족·역매칭 실패 → LAWD {lawd} 내 "
                             f"≤33㎡ 월세 표본 최다 '{best}'({candidates[best]}건) 채택."),
                "candidates": candidates}

    # 실패: 최빈동이라도 반환(표본 부족 경고는 상위에서)
    return {"dongs": [mode_dong] if mode_dong else [], "method": "fallback",
            "evidence": f"MOLIT ≤33㎡ 월세 표본 없음 — 33m2 최빈동 '{mode_dong}' 잠정.",
            "candidates": candidates}


# --------------------------------------------------------------------------- #
# 통합 진입점
# --------------------------------------------------------------------------- #
def auto_locate(name: str, radius: float, months: int,
                service_key: str, use_cache=True) -> dict:
    """지역명 → stations 사전과 동형인 위치 dict + 해석 근거.

    반환: {lat, lon, lawd, dongs, desc, evidence:[...], source}
    실패 시 LocateError.
    """
    ev = []
    g = geocode(name)
    if not g:
        raise LocateError(f"'{name}' 지오코딩 실패 — --lat/--lon 수동 지정 필요.")
    ev.append(f"지오코딩(OSM Nominatim): {name} → ({g['lat']:.4f}, {g['lon']:.4f})"
              + (f" · {g['display'][:50]}" if g.get("display") else ""))

    addr = scan_addresses(g["lat"], g["lon"], radius)
    if not addr["provinces"]:
        raise LocateError(
            f"좌표 반경 {radius:.0f}m 내 33m2 매물 없음 — 법정동·LAWD 자동 결정 불가. "
            f"--lawd/--dong 수동 지정 필요.")
    province = addr["provinces"].most_common(1)[0][0]
    ev.append(f"33m2 주소 최빈 시군구: {province} "
              f"(법정동 후보 {dict(addr['towns'].most_common(3))})")

    table = ensure_lawd_table()
    lawd = resolve_lawd(province, table)
    if not lawd:
        raise LocateError(f"시군구 '{province}' → LAWD 매핑 실패 "
                          f"(하드코딩 테이블·다운로드 모두 미해당). --lawd 수동 지정 필요.")
    src = "다운로드" if os.path.exists(LAWD_CSV) and province not in SIGUNGU_LAWD \
        else "내장 테이블"
    ev.append(f"LAWD 매핑({src}): {province} → {lawd}")

    dres = resolve_dong(service_key, lawd, addr["towns"], addr["complexes"],
                        months, use_cache=use_cache)
    ev.append(f"법정동 결정[{dres['method']}]: {dres['evidence']}")

    if not dres["dongs"]:
        raise LocateError(f"LAWD {lawd} 내 법정동 결정 실패.")

    desc = (f"{province} {dres['dongs'][0]} (자동 해석: 지오코딩→33m2 주소→"
            f"LAWD→단지 역매칭). 사전 미등록 지역.")
    return {"lat": g["lat"], "lon": g["lon"], "lawd": lawd,
            "dongs": dres["dongs"], "desc": desc, "evidence": ev,
            "source": "auto", "candidates": dres["candidates"]}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="지역명 자동 위치 해석")
    ap.add_argument("name")
    ap.add_argument("--radius", type=float, default=500)
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    key = molit.load_service_key()
    res = auto_locate(a.name, a.radius, a.months, key, use_cache=not a.no_cache)
    print(f"위치: {res['lat']:.4f},{res['lon']:.4f} · LAWD {res['lawd']} · "
          f"동 {'/'.join(res['dongs'])}")
    for e in res["evidence"]:
        print("  -", e)
