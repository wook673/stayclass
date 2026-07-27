# -*- coding: utf-8 -*-
"""m33.py — 삼삼엠투(33m2) 공급 스캔(비로그인) + 예약률(로그인 세션).

지도 API : GET https://web.33m2.co.kr/v1/use-auth/map/rooms
   params : swLat,swLng,neLat,neLng,page,size(<=50)
   응답   : {"code":"SCSS_001","data":{"content":[...], "first":bool, "last":bool}}
   항목   : rid, roomName, propertyType, usingFee(임대료), mgmtFee(관리비),
            pyeongSize, roomCnt, lat, lng, addrLot, town, province, isNew...
캘린더 API: GET https://web.33m2.co.kr/v1/use-auth/rooms/{rid}/schedules
   params : year=YYYY, month=M  ← **필수**(누락 시 400 VLD_001 "월은 필수입니다").
            currentInitialContractId 는 선택(값 없으면 아예 보내지 않음).
            실제 프런트 번들(chunk 6192) 계약을 리버스로 확인한 값이다.
   로그인 세션 필요(쿠키/Bearer). 미로그인 시 401 AUTH_002.
   응답   : {"code":"SCSS_001","data":{
              "contracts":[{initialContractId,startDate,endDate,checkoutDate}],
              "schedules":[{"date":"YYYY-MM-DD","status":"BOOKING"|"DISABLE"|...}]}}
   한 번에 한 달치만 주므로, 창(weeks×7일)이 걸치는 모든 (연,월)을 각각 조회해
   날짜 기준으로 병합·중복제거한 뒤 창 안으로 필터링해 집계한다.

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


class ScheduleAPIError(RuntimeError):
    """캘린더 API 계약 위반(파라미터 거부 등) — 조용히 삼키지 않는다."""


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


def _months_in_window(lo: datetime.date, hi: datetime.date) -> list:
    """[lo, hi) 창이 걸치는 모든 (연, 월)을 시간순으로. hi는 **불포함**.

    예) 2026-07-27 ~ 2026-09-21 → [(2026,7),(2026,8),(2026,9)]
        2026-12-20 ~ 2027-02-01 → [(2026,12),(2027,1)]  (연도 경계 처리)
    """
    if hi <= lo:
        return []
    last = hi - datetime.timedelta(days=1)      # 창의 마지막 '포함' 날짜
    out = []
    y, m = lo.year, lo.month
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _schedule_items(payload):
    """페이로드에서 스케줄 리스트를 방어적으로 꺼낸다. 못 찾으면 None."""
    if isinstance(payload, dict):
        items = payload.get("data")
        if isinstance(items, dict):
            items = (items.get("content") or items.get("schedules")
                     or items.get("list") or [])
    else:
        items = payload
    return items if isinstance(items, list) else None


def _state_of(el) -> Optional[str]:
    if not isinstance(el, dict):
        return None
    for k in ("state", "status", "scheduleState", "type"):
        v = el.get(k)
        if isinstance(v, str):
            return v.lower()
    return None


def _date_of(el) -> Optional[str]:
    if not isinstance(el, dict):
        return None
    for k in ("date", "day", "scheduleDate", "ymd"):
        if el.get(k):
            return str(el[k])
    return None


def merge_schedule_counts(payloads, window_days: int,
                          today: Optional[datetime.date] = None,
                          window: str = "future") -> Optional[dict]:
    """월별 schedules 응답 여러 개를 병합해 booking/disable 일수 집계.

    payloads : (연,월)별로 받아온 디코드된 JSON 페이로드 리스트.
    기본 window='future': [오늘, 오늘+window_days) 선점 창.
      ※ 33m2 캘린더 API는 **과거 날짜를 반환하지 않는다**(2026-07 상현역 실측).
        window='past'는 집계 로직 검증용으로만 남긴다(실사용 금지).
    같은 날짜가 두 달치 응답에 겹쳐 들어와도 **날짜 기준으로 1회만** 센다.
    분모(days)는 창 길이(window_days) 고정 — '기간' 대비 점유율.
    날짜를 하나도 못 읽으면(비정형 응답) 앞 window_days개로 폴백하고
    undated=True 표기(이때도 분모는 window_days).

    어떤 페이로드에서도 리스트 구조를 못 찾으면 None.
    """
    today = today or datetime.date.today()
    if window == "past":
        lo, hi = today - datetime.timedelta(days=window_days), today
    else:
        lo, hi = today, today + datetime.timedelta(days=window_days)

    any_list = False
    by_date = {}          # date → state (중복 제거)
    undated_states = []   # 날짜를 못 읽은 항목(폴백용, 순서 보존)
    for payload in (payloads or []):
        items = _schedule_items(payload)
        if items is None:
            continue
        any_list = True
        for el in items:
            s = _state_of(el)
            if s is None:
                continue
            d = _to_date(_date_of(el))
            if d is None:
                undated_states.append(s)
            else:
                by_date[d] = s
    if not any_list:
        return None

    days = window_days or 1              # 분모 = 창 길이(기간) 고정
    if by_date:
        sel = [s for d, s in sorted(by_date.items()) if lo <= d < hi]
        undated = False
    else:
        # 날짜 없는 비정형 응답 → 앞에서 window_days개 폴백
        sel = undated_states[:window_days] if window_days else undated_states
        undated = True

    booking = sum(1 for s in sel if "book" in s)
    disable = sum(1 for s in sel
                  if "disable" in s or "block" in s or "close" in s)
    return {"days": days, "booking": booking, "disable": disable,
            "undated": undated, "n_in_window": len(sel)}


def _server_message(payload) -> str:
    """에러 페이로드의 사람이 읽는 메시지(message.content 또는 message 문자열)."""
    if not isinstance(payload, dict):
        return ""
    msg = payload.get("message")
    if isinstance(msg, dict):
        return str(msg.get("content") or msg)
    if isinstance(msg, str):
        return msg
    return ""


def fetch_occupancy(rooms: list, session_headers: dict, weeks: int = 8,
                    samples: int = 10, window: str = "future") -> dict:
    """가격 중위권 samples개 매물의 선점률(기본: 향후 weeks주).

    - window='future'(기본): [오늘, 오늘+weeks주) 창의 booking+disable ÷ 기간.
      33m2 API가 과거 날짜를 반환하지 않아 이것이 유일한 실측 경로다.
      창 후반은 아직 예약이 채워지는 중이므로 **하한 성격**(실제 최종 가동률 ≥ 측정값).
    - window='past': 하위호환용. API 미반환으로 항상 0% — 사용 금지.
    - 통합 선점률 = (booking+disable)/기간  (기본 지표)
    - 33m2 단독 = booking/기간
    - 타채널비중 = 통합 − 단독
    각 매물의 개별 가동률도 rooms 리스트로 반환(랭킹용: name/addr/weekly/combined).
    세션 없음/만료(401)면 SessionError, 캘린더 API 계약 위반이면 ScheduleAPIError.

    캘린더 API는 한 번에 한 달치만 주고 year/month 가 필수이므로,
    창이 걸치는 모든 (연,월)을 매물마다 각각 조회해 병합한다.
    """
    if not session_headers:
        raise SessionError("세션 헤더 없음")
    window_days = weeks * 7
    today = datetime.date.today()
    if window == "past":
        lo, hi = today - datetime.timedelta(days=window_days), today
    else:
        lo, hi = today, today + datetime.timedelta(days=window_days)
    months = _months_in_window(lo, hi)
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
        payloads = []
        for (y, mon) in months:
            params = {"year": y, "month": mon}      # ← 둘 다 필수
            resp = requests.get(SCHED_URL.format(rid=rid), params=params,
                                headers=h, timeout=20)
            resp.encoding = "utf-8"
            if resp.status_code == 401:
                raise SessionError(f"401 세션 만료/미로그인 (rid {rid})")
            try:
                payload = resp.json()
            except ValueError:
                raise ScheduleAPIError(
                    f"캘린더 API 비 JSON 응답 — rid {rid} params={params} "
                    f"status={resp.status_code} body={(resp.text or '')[:200]!r}")
            code = payload.get("code") if isinstance(payload, dict) else None
            if code == "AUTH_002":
                raise SessionError("AUTH_002 로그인 필요")
            if resp.status_code == 400 or (isinstance(code, str)
                                           and code.startswith("VLD_")):
                raise ScheduleAPIError(
                    f"캘린더 API 계약 위반 — rid {rid} params={params} "
                    f"status={resp.status_code} code={code} "
                    f"message={_server_message(payload)!r}")
            if not (200 <= resp.status_code < 300):
                raise ScheduleAPIError(
                    f"캘린더 API 오류 — rid {rid} params={params} "
                    f"status={resp.status_code} code={code} "
                    f"body={(resp.text or '')[:200]!r}")
            payloads.append(payload)
            _sleep()
        counts = merge_schedule_counts(payloads, window_days,
                                       today=today, window=window)
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
        # 스로틀은 요청 단위(월별 루프 안)에서 이미 걸린다.

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
