# -*- coding: utf-8 -*-
"""m33.py — 삼삼엠투(33m2) 공급 스캔(비로그인) + 예약률(로그인 세션).

지도 API : GET https://web.33m2.co.kr/v1/use-auth/map/rooms
   params : swLat,swLng,neLat,neLng,page,size(<=50)
   응답   : {"code":"SCSS_001","data":{"content":[...], "first":bool, "last":bool}}
   항목   : rid, roomName, propertyType, usingFee(임대료), mgmtFee(관리비),
            pyeongSize, roomCnt, lat, lng, addrLot, town, province, isNew...
캘린더 API: GET https://web.33m2.co.kr/v1/use-auth/rooms/{rid}/schedules
   로그인 세션 필요(쿠키/Bearer). 미로그인 시 401 AUTH_002.
   응답에서 날짜별 상태(booking/disable/available)를 창(weeks×7일) 내로 집계.

상시 지침 필터:
  - 유형: '오피스텔'만 유지. 고시원·모텔여관·호텔·게스트하우스·쉐어·펜션 제외(건수 기록).
  - 원룸만: 이름 키워드로 투룸/N룸/N베드/N인 제외.
요청 간 1초 스로틀. 세션 없음/만료(401)는 graceful degradation.
"""
from __future__ import annotations

import datetime
import math
import re
import statistics
import time
from typing import Optional

import requests

from config import THROTTLE_SEC

MAP_URL = "https://web.33m2.co.kr/v1/use-auth/map/rooms"
SCHED_URL = "https://web.33m2.co.kr/v1/use-auth/rooms/{rid}/schedules"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Accept": "application/json",
            "Referer": "https://web.33m2.co.kr/"}
_PAGE_SIZE = 50

# 유형 제외(오피스텔만 유지) — 상시 지침
_EXCLUDE_TYPES = ("고시원", "모텔", "여관", "호텔", "게스트하우스",
                  "게스트", "쉐어", "셰어", "share", "펜션")
KEEP_TYPE = "오피스텔"
# 원룸 아님(멀티룸/다인) 키워드
_MULTIROOM_RE = re.compile(
    r"(투룸|2\s*룸|２룸|two|쓰리룸|3\s*룸|3베드|2베드|[2-9]\s*베드|"
    r"[2-9]\s*bed|[2-9]\s*인|복층\s*[2-9]인)", re.IGNORECASE)


class SessionError(RuntimeError):
    """로그인 세션 없음/만료(예약률 조회 불가)."""


def _sleep():
    time.sleep(THROTTLE_SEC)


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bbox(lat, lon, radius_m):
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)  # swLat,swLng,neLat,neLng


def _weekly(item) -> Optional[float]:
    """주간가(원) = 임대료 + 관리비."""
    u = item.get("usingFee") or 0
    m = item.get("mgmtFee") or 0
    try:
        return float(u) + float(m)
    except (TypeError, ValueError):
        return None


def scan_supply(lat: float, lon: float, radius_m: float = 500,
                session_headers: Optional[dict] = None) -> dict:
    """반경 내 매물 수집 → 오피스텔·원룸 필터 → 매물수·주간가 분포.

    반환:
      {"n_total": 반경내 전체, "n_type_excluded": 유형제외,
       "n_notroom_excluded": 비원룸제외, "n_kept": 최종,
       "weekly": {"median","min","max","n"}, "rooms": [...유지 매물...]}
    """
    sw_lat, sw_lon, ne_lat, ne_lon = _bbox(lat, lon, radius_m)
    seen = {}
    page = 1
    h = dict(_HEADERS)
    if session_headers:
        h.update(session_headers)
    while True:
        r = requests.get(MAP_URL, params=dict(
            swLat=sw_lat, swLng=sw_lon, neLat=ne_lat, neLng=ne_lon,
            page=page, size=_PAGE_SIZE), headers=h, timeout=20)
        r.encoding = "utf-8"
        try:
            data = r.json().get("data") or {}
        except ValueError:
            raise RuntimeError(f"33m2 map 비 JSON 응답(status {r.status_code})")
        content = data.get("content") or []
        for it in content:
            rid = it.get("rid")
            if rid is not None and rid not in seen:
                seen[rid] = it
        if data.get("last", True) or not content:
            break
        page += 1
        _sleep()

    # 반경 필터(직선거리) + 유형/원룸 필터
    n_total = n_type_excl = n_notroom_excl = 0
    kept = []
    for it in seen.values():
        ilat, ilon = it.get("lat"), it.get("lng")
        if ilat is None or ilon is None:
            continue
        if _haversine_m(lat, lon, float(ilat), float(ilon)) > radius_m:
            continue
        n_total += 1
        ptype = (it.get("propertyType") or "").strip()
        name = it.get("roomName") or ""
        if any(x in ptype for x in _EXCLUDE_TYPES) or any(
                x in name for x in _EXCLUDE_TYPES):
            n_type_excl += 1
            continue
        if ptype != KEEP_TYPE:          # 오피스텔만 유지
            n_type_excl += 1
            continue
        if _MULTIROOM_RE.search(name) or (it.get("roomCnt") or 1) > 1:
            n_notroom_excl += 1
            continue
        kept.append({
            "rid": rid_of(it), "name": name, "type": ptype,
            "weekly": _weekly(it), "pyeong": it.get("pyeongSize"),
            "roomCnt": it.get("roomCnt"),
            "lat": float(ilat), "lon": float(ilon),
            "addr": it.get("addrLot"), "town": it.get("town"),
            "isNew": it.get("isNew"),
        })

    weeklies = [k["weekly"] for k in kept if k["weekly"]]
    wk = ({"median": round(statistics.median(weeklies)),
           "min": min(weeklies), "max": max(weeklies), "n": len(weeklies)}
          if weeklies else {"median": None, "min": None, "max": None, "n": 0})
    return {"n_total": n_total, "n_type_excluded": n_type_excl,
            "n_notroom_excluded": n_notroom_excl, "n_kept": len(kept),
            "weekly": wk, "rooms": kept}


def rid_of(it):
    return it.get("rid")


# --------------------------------------------------------------------------- #
# 예약률 (로그인 세션)
# --------------------------------------------------------------------------- #
_DATE_RE = re.compile(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})")


def _to_date(s) -> Optional[datetime.date]:
    """'2026-07-23' / '20260723' / '2026.07.23T..' 등 → date. 실패 시 None."""
    if not s:
        return None
    m = _DATE_RE.search(str(s))
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _parse_schedule_counts(payload, window_days: int, window: str = "past",
                           today: Optional[datetime.date] = None) -> Optional[dict]:
    """schedules 응답에서 booking/disable 일수 집계.

    기본 window='past': [오늘-window_days, 오늘) 확정 실적 창.
    window='future': [오늘, 오늘+window_days) 예정 창.
    분모(days)는 창 길이(window_days) 고정 — '기간' 대비 점유율.
    날짜를 하나도 못 읽으면(비정형 응답) 정렬 후 앞 window_days개로
    폴백하고 undated=True 표기.

    방어적 파싱: 응답 구조가 리스트/'data' 래핑 어느 쪽이든, 각 원소에서
    상태 문자열(booking/disable/available)을 찾아 카운트.
    """
    if isinstance(payload, dict):
        items = payload.get("data")
        if isinstance(items, dict):
            items = (items.get("content") or items.get("schedules")
                     or items.get("list") or [])
    else:
        items = payload
    if not isinstance(items, list):
        return None

    def state_of(el):
        if not isinstance(el, dict):
            return None
        for k in ("state", "status", "scheduleState", "type"):
            v = el.get(k)
            if isinstance(v, str):
                return v.lower()
        return None

    def date_of(el):
        if not isinstance(el, dict):
            return None
        for k in ("date", "day", "scheduleDate", "ymd"):
            if el.get(k):
                return str(el[k])
        return None

    today = today or datetime.date.today()
    dated = [(_to_date(date_of(e)), state_of(e)) for e in items]
    dated = [(d, s) for d, s in dated if s is not None]

    have_dates = any(d for d, _ in dated)
    if have_dates:
        if window == "past":
            lo, hi = today - datetime.timedelta(days=window_days), today
        else:
            lo, hi = today, today + datetime.timedelta(days=window_days)
        sel = [(d, s) for d, s in dated if d is not None and lo <= d < hi]
        days = window_days or 1          # 분모 = 창 길이(기간)
        undated = False
    else:
        # 날짜 없는 비정형 응답 → 앞에서 window_days개 폴백
        sel = dated[:window_days] if window_days else dated
        days = len(sel) or window_days or 1
        undated = True

    booking = sum(1 for _, s in sel if "book" in s)
    disable = sum(1 for _, s in sel
                  if "disable" in s or "block" in s or "close" in s)
    return {"days": days, "booking": booking, "disable": disable,
            "undated": undated, "n_in_window": len(sel)}


def fetch_occupancy(rooms: list, session_headers: dict, weeks: int = 8,
                    samples: int = 10, window: str = "past") -> dict:
    """가격 중위권 samples개 매물의 예약률(기본: 지난 weeks주 확정 실적).

    - window='past'(기본): 오늘 기준 과거 weeks주 창의 booking+disable ÷ 기간.
    - window='future': 향후 weeks주 예정 창(참고용).
    - 통합 가동률 = (booking+disable)/기간  (기본 지표)
    - 33m2 단독 = booking/기간
    - 타채널비중 = 통합 − 단독
    각 매물의 개별 가동률도 rooms 리스트로 반환(랭킹용: name/addr/weekly/combined).
    세션 없음/만료(401)면 SessionError.
    """
    if not session_headers:
        raise SessionError("세션 헤더 없음")
    window_days = weeks * 7
    # 가격 중위권 표본 선정
    priced = sorted([r for r in rooms if r["weekly"]], key=lambda r: r["weekly"])
    if not priced:
        return {"ok": False, "reason": "표본 없음", "rooms": []}
    n = len(priced)
    if n <= samples:
        chosen = priced
    else:
        start = max(0, (n - samples) // 2)
        chosen = priced[start:start + samples]

    h = dict(_HEADERS)
    h.update(session_headers)
    h["Accept"] = "application/json, text/plain, */*"

    results = []
    for r in chosen:
        rid = r["rid"]
        resp = requests.get(SCHED_URL.format(rid=rid), headers=h, timeout=20)
        resp.encoding = "utf-8"
        if resp.status_code == 401:
            raise SessionError(f"401 세션 만료/미로그인 (rid {rid})")
        try:
            payload = resp.json()
        except ValueError:
            _sleep()
            continue
        if isinstance(payload, dict) and payload.get("code") == "AUTH_002":
            raise SessionError("AUTH_002 로그인 필요")
        counts = _parse_schedule_counts(payload, window_days, window=window)
        if counts:
            days = counts["days"]
            results.append({
                "rid": rid, "name": r["name"], "weekly": r["weekly"],
                "addr": r.get("addr"), "town": r.get("town"),
                "booking": counts["booking"], "disable": counts["disable"],
                "undated": counts.get("undated", False),
                "pure": counts["booking"] / days,
                "combined": (counts["booking"] + counts["disable"]) / days,
            })
        _sleep()

    if not results:
        return {"ok": False, "reason": "응답 파싱 실패", "rooms": []}
    pure = statistics.mean(x["pure"] for x in results)
    combined = statistics.mean(x["combined"] for x in results)
    return {
        "ok": True, "n": len(results),
        "window": window, "weeks": weeks,   # 측정 창 메타(리포트 표기용)
        "combined_occ": combined,      # 통합 가동률(기본)
        "pure_occ": pure,              # 33m2 단독
        "other_channel": combined - pure,  # 타채널비중
        "rooms": results,
    }


def parse_session_file(path: str) -> dict:
    """세션 파일 → 요청 헤더 dict.

    허용 형식(자유):
      - 'Cookie: k=v; k2=v2'  또는 순수 'k=v; k2=v2' 한 줄
      - 'Authorization: Bearer <JWT>'  또는 순수 'Bearer <JWT>'
      - 위 두 줄을 함께 넣어도 됨.
    """
    headers = {}
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if low.startswith("cookie:"):
            headers["Cookie"] = line.split(":", 1)[1].strip()
        elif low.startswith("authorization:"):
            headers["Authorization"] = line.split(":", 1)[1].strip()
        elif low.startswith("bearer "):
            headers["Authorization"] = line
        elif "=" in line:            # 순수 쿠키 문자열 (k=v; k2=v2)
            headers["Cookie"] = line
    if not headers:
        raise SessionError(f"세션 파일에서 Cookie/Authorization 을 못 찾음: {path}")
    return headers


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="33m2 공급 스캔")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--radius", type=float, default=500)
    a = ap.parse_args()
    s = scan_supply(a.lat, a.lon, a.radius)
    print(f"반경 {a.radius:.0f}m 내 {s['n_total']}건 → "
          f"유형제외 {s['n_type_excluded']} · 비원룸제외 {s['n_notroom_excluded']} "
          f"→ 유지 {s['n_kept']}건")
    w = s["weekly"]
    if w["n"]:
        print(f"주간가(원): 중위 {w['median']:,} / 최저 {w['min']:,} / 최고 {w['max']:,} (n={w['n']})")
