# -*- coding: utf-8 -*-
"""scan.py — 지역 스캔 모드: 바운딩박스 타일 수집 → 그리디 500m 클러스터링 →
상위 N 클러스터 각각 분석 → 비교 랭킹.

방법론(market_gyeonggi_south.md §1-3):
  1. 지역명 → Nominatim 바운딩박스 → 타일 분할, 페이지네이션 전수 수집(비로그인),
     rid 기준 중복 제거.
  2. 상시 지침 필터(오피스텔 원룸만, 고시원·모텔·쉐어 등 제외) 후,
     그리디 클러스터링: 잔여 매물 중 500m 반경 이웃 최다 지점을 중심 →
     반경 내 전 매물 배정·제거 반복. 매물 3+ 클러스터만 후보.
  3. 상위 N 클러스터 각각: 법정동 자동 결정(locate) → MOLIT 비용 밴드 →
     수익률(예약률 세션 있으면 클러스터당 표본 5개로 축소, 없으면 공급·비용 랭킹만).

요청 간 1초 스로틀(상시 지침) 준수.
"""
from __future__ import annotations

import math
import statistics
import time
from typing import Optional

import requests

import locate
import m33
import model
import molit
import rules
import config

_H = dict(m33._HEADERS)
_TILE_DEG = 0.025          # 타일 한 변(도) ≈ 2.2km — 밀집지 페이지 상한 회피
_SCAN_SAMPLES = 5          # 세션 있을 때 클러스터당 예약률 표본(축소)


# --------------------------------------------------------------------------- #
# 1) 타일 수집
# --------------------------------------------------------------------------- #
def geocode_bbox(region: str) -> Optional[dict]:
    """지역명 → {south,north,west,east,lat,lon}. Nominatim 바운딩박스."""
    try:
        r = requests.get(locate.NOMINATIM, params={
            "q": region, "format": "json", "countrycodes": "kr",
            "limit": 1, "addressdetails": 0}, headers=locate._UA, timeout=15)
        time.sleep(1.0)
        arr = r.json()
    except (ValueError, requests.RequestException):
        return None
    if not arr:
        return None
    g = arr[0]
    s, n, w, e = (float(x) for x in g["boundingbox"])
    return {"south": s, "north": n, "west": w, "east": e,
            "lat": float(g["lat"]), "lon": float(g["lon"]),
            "display": g.get("display_name", "")}


def collect_tiles(bbox: dict, tile_deg: float = _TILE_DEG) -> dict:
    """바운딩박스를 타일로 나눠 전 매물 수집(rid 중복 제거).

    반환: {"items": {rid: item}, "n_tiles": int, "n_raw": int}
    """
    items = {}
    lat = bbox["south"]
    n_tiles = 0
    while lat < bbox["north"]:
        lon = bbox["west"]
        while lon < bbox["east"]:
            sw_lat, sw_lon = lat, lon
            ne_lat = min(lat + tile_deg, bbox["north"])
            ne_lon = min(lon + tile_deg, bbox["east"])
            _fetch_tile(sw_lat, sw_lon, ne_lat, ne_lon, items)
            n_tiles += 1
            time.sleep(config.THROTTLE_SEC)   # 상시 지침: 요청 간 1초
            lon += tile_deg
        lat += tile_deg
    return {"items": items, "n_tiles": n_tiles, "n_raw": len(items)}


def _fetch_tile(sw_lat, sw_lon, ne_lat, ne_lon, items: dict):
    page = 1
    while True:
        try:
            r = requests.get(m33.MAP_URL, params=dict(
                swLat=sw_lat, swLng=sw_lon, neLat=ne_lat, neLng=ne_lon,
                page=page, size=50), headers=_H, timeout=20)
            r.encoding = "utf-8"
            data = r.json().get("data") or {}
        except (ValueError, requests.RequestException):
            return
        content = data.get("content") or []
        for it in content:
            rid = it.get("rid")
            if rid is not None and rid not in items:
                items[rid] = it
        if data.get("last", True) or not content:
            return
        page += 1
        time.sleep(config.THROTTLE_SEC)


# --------------------------------------------------------------------------- #
# 2) 필터 + 그리디 클러스터링
# --------------------------------------------------------------------------- #
def filter_supply(items: dict) -> list:
    """상시 지침 필터(오피스텔 원룸만) → room dict 리스트. m33 로직 재사용."""
    kept = []
    for it in items.values():
        ilat, ilon = it.get("lat"), it.get("lng")
        if ilat is None or ilon is None:
            continue
        ptype = (it.get("propertyType") or "").strip()
        name = it.get("roomName") or ""
        if any(x in ptype for x in m33._EXCLUDE_TYPES) or any(
                x in name for x in m33._EXCLUDE_TYPES):
            continue
        if ptype != m33.KEEP_TYPE:
            continue
        if m33._MULTIROOM_RE.search(name) or (it.get("roomCnt") or 1) > 1:
            continue
        kept.append({
            "rid": it.get("rid"), "name": name, "type": ptype,
            "weekly": m33._weekly(it), "pyeong": it.get("pyeongSize"),
            "roomCnt": it.get("roomCnt"), "lat": float(ilat), "lon": float(ilon),
            "addr": it.get("addrLot"), "town": it.get("town"),
            "province": it.get("province"), "isNew": it.get("isNew"),
        })
    return kept


def greedy_clusters(rooms: list, radius_m: float = 500,
                    min_size: int = 3) -> list:
    """그리디 500m 클러스터링(하버사인). 이웃 최다 지점을 중심으로 반복.

    반환: [{center:(lat,lon), rooms:[...], n:int, weekly_median, towns, complexes}]
    (매물 수 내림차순)
    """
    remaining = list(rooms)
    clusters = []
    while remaining:
        # 각 점의 반경 내 이웃 수
        best_i, best_neigh = -1, []
        for i, r in enumerate(remaining):
            neigh = [o for o in remaining
                     if m33._haversine_m(r["lat"], r["lon"],
                                         o["lat"], o["lon"]) <= radius_m]
            if len(neigh) > len(best_neigh):
                best_i, best_neigh = i, neigh
        if best_i < 0:
            break
        seed = remaining[best_i]
        members = best_neigh
        member_ids = {id(m) for m in members}
        remaining = [r for r in remaining if id(r) not in member_ids]
        if len(members) >= min_size:
            weeklies = [m["weekly"] for m in members if m["weekly"]]
            from collections import Counter
            clusters.append({
                "center": (seed["lat"], seed["lon"]),
                "rooms": members, "n": len(members),
                "weekly_median": round(statistics.median(weeklies)) if weeklies else None,
                "weekly_n": len(weeklies),
                "towns": Counter(m["town"] for m in members if m["town"]),
                "complexes": {locate._complex_from_addr(m["addr"])
                              for m in members if m["addr"]} - {None},
                "province": Counter(m["province"] for m in members
                                    if m["province"]).most_common(1)[0][0]
                             if any(m["province"] for m in members) else None,
            })
    clusters.sort(key=lambda c: c["n"], reverse=True)
    return clusters


# --------------------------------------------------------------------------- #
# 3) 클러스터별 분석
# --------------------------------------------------------------------------- #
def analyze_cluster(cluster: dict, months: int, service_key: str,
                    occ_assumed: Optional[float] = None,
                    session_headers: Optional[dict] = None,
                    mgmt: float = config.DEFAULT_MGMT,
                    use_cache=True) -> dict:
    """단일 클러스터 → 법정동 자동결정 + MOLIT 밴드 + (예약률) + 수익률 + 판단.

    반환 dict: cluster 요약 + {lawd, dong, bands, occ_used, scenarios, analysis, locate_ev}
    """
    lat, lon = cluster["center"]
    table = locate.ensure_lawd_table()
    lawd = locate.resolve_lawd(cluster["province"] or "", table)
    result = {
        "n": cluster["n"], "weekly_median": cluster["weekly_median"],
        "weekly_n": cluster["weekly_n"], "center": cluster["center"],
        "province": cluster["province"], "lawd": lawd,
        "dong": None, "bands": None, "occ_used": None, "occ_measured": False,
        "scenarios": [], "analysis": None, "locate_ev": [],
    }
    if not lawd:
        result["locate_ev"].append(
            f"시군구 '{cluster['province']}' → LAWD 매핑 실패(비용 분석 생략).")
        return result

    dres = locate.resolve_dong(service_key, lawd, cluster["towns"],
                               cluster["complexes"], months, use_cache=use_cache)
    dong = dres["dongs"][0] if dres["dongs"] else None
    result["dong"] = dong
    result["locate_ev"].append(f"법정동[{dres['method']}]: {dres['evidence']}")
    if not dong:
        return result

    mo = molit.collect(service_key, lawd, [dong], months, use_cache=use_cache)
    result["bands"] = mo["bands"]
    result["molit"] = mo

    # 예약률: 세션 있으면 축소 표본(5), 없으면 가정값
    occ_used, occ_measured, occupancy = None, False, None
    if session_headers:
        try:
            occupancy = m33.fetch_occupancy(cluster["rooms"], session_headers,
                                            weeks=config.DEFAULT_WEEKS,
                                            samples=_SCAN_SAMPLES)
            if occupancy.get("ok"):
                occ_used, occ_measured = occupancy["combined_occ"], True
        except m33.SessionError:
            occupancy = None
    if occ_used is None and occ_assumed is not None:
        occ_used = occ_assumed
    result["occ_used"], result["occ_measured"] = occ_used, occ_measured
    result["occupancy"] = occupancy

    # 수익률
    scenarios = []
    if occ_used is not None and cluster["weekly_median"] is not None:
        weekly_man = cluster["weekly_median"] / 10000.0
        for band, dep in (("500", config.DEPOSIT_500), ("1000", config.DEPOSIT_1000)):
            b = mo["bands"][band]
            if not b["sufficient"]:
                continue
            p60 = model.monthly_profit(weekly_man, occ_used, b["rent_median"],
                                       mgmt, config.UTILITIES, config.SHARE_PRIMARY)
            p50 = model.monthly_profit(weekly_man, occ_used, b["rent_median"],
                                       mgmt, config.UTILITIES, config.SHARE_ALT)
            scenarios.append({
                "band": band, "deposit": dep, "rent": b["rent_median"],
                "profit60": p60, "profit50": p50,
                "yield60": model.annual_yield_pct(p60, dep),
                "yield50": model.annual_yield_pct(p50, dep)})
    result["scenarios"] = scenarios

    # 판단룰
    ctx = {"supply": {"weekly": {"n": cluster["weekly_n"]}},
           "occupancy": occupancy, "molit": mo, "scenarios": scenarios}
    result["analysis"] = rules.analyze(ctx)
    return result


# --------------------------------------------------------------------------- #
# 통합 진입점
# --------------------------------------------------------------------------- #
def run_scan(region: str, top: int, months: int, radius: float,
             occ_assumed: Optional[float] = None,
             session_headers: Optional[dict] = None,
             mgmt: float = config.DEFAULT_MGMT, use_cache=True,
             min_size: int = 3, progress=print) -> dict:
    """스캔 오케스트레이션 → 랭킹 데이터."""
    bbox = geocode_bbox(region)
    if not bbox:
        raise locate.LocateError(f"'{region}' 지오코딩 실패 — 스캔 불가.")
    progress(f"  바운딩박스: {bbox['south']:.4f},{bbox['west']:.4f} → "
             f"{bbox['north']:.4f},{bbox['east']:.4f}")
    tiles = collect_tiles(bbox)
    progress(f"  타일 {tiles['n_tiles']}개 · 고유 매물 {tiles['n_raw']}건 수집")
    kept = filter_supply(tiles["items"])
    progress(f"  오피스텔 원룸 필터 후 {len(kept)}건")
    clusters = greedy_clusters(kept, radius, min_size)
    progress(f"  매물 {min_size}+ 클러스터 {len(clusters)}개 발굴 → 상위 {top} 분석")

    analyzed = []
    for i, cl in enumerate(clusters[:top], 1):
        town = cl["towns"].most_common(1)[0][0] if cl["towns"] else "?"
        progress(f"  [{i}/{min(top,len(clusters))}] 클러스터 "
                 f"({cl['province']} {town}, 매물 {cl['n']}) 분석...")
        analyzed.append(analyze_cluster(cl, months, molit.load_service_key(),
                                        occ_assumed, session_headers, mgmt,
                                        use_cache))
    return {
        "region": region, "bbox": bbox, "n_tiles": tiles["n_tiles"],
        "n_raw": tiles["n_raw"], "n_kept": len(kept),
        "n_clusters": len(clusters), "top": top,
        "clusters": analyzed, "date": _today(),
        "has_session": bool(session_headers),
    }


def _today():
    import datetime
    return datetime.date.today().isoformat()
