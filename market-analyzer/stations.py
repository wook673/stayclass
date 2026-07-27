# -*- coding: utf-8 -*-
"""stations.py — 역/지역 사전.

이번 조사(2026-07)에서 실증 확정한 좌표 + LAWD(시군구 5자리) + 법정동 매핑.
법정동은 MOLIT 비용 표본 필터에 사용(yield_deposit_bands.md §2 실증 매핑 그대로).

각 항목: (lat, lon, lawd, [법정동...], 설명)
  - 법정동 리스트는 MOLIT umdNm 과 정확히 일치해야 함(공백/한자 없음).
  - 동탄역은 역앞 오산동 실거래 0건 → 표본단지 소재 '영천동'으로 대리(회귀 검증됨).
"""
from __future__ import annotations

# LAWD(시군구) 참고:
#   41135 성남시 분당구 · 41597 화성시(동탄2) · 41465 용인시 수지구
#   41115 수원시 팔달구 · 41117 수원시 영통구 · 41173 안양시 동안구
#   41463 용인시 기흥구
STATIONS = {
    "영통역":   dict(lat=37.2515, lon=127.0709, lawd="41117", dongs=["영통동"],
                    desc="수원 영통구 영통동(수인분당선). 앵커 확보 계약 소재."),
    "동탄역":   dict(lat=37.2003, lon=127.0986, lawd="41597", dongs=["영천동"],
                    desc="화성 동탄2(SRT/GTX). 비용 대리동=영천동(오산동 실거래 0건)."),
    "상현역":   dict(lat=37.2996, lon=127.0668, lawd="41465", dongs=["상현동"],
                    desc="용인 수지구 상현동(신분당선). 광교·판교 접근."),
    "정자역":   dict(lat=37.3671, lon=127.1082, lawd="41135", dongs=["정자동"],
                    desc="성남 분당구 정자동(신분당/수인분당). 경기남부 최대 공급."),
    "서현역":   dict(lat=37.3853, lon=127.1234, lawd="41135", dongs=["서현동"],
                    desc="성남 분당구 서현동(분당선). ≤33㎡ 표본 얇음."),
    "오리역":   dict(lat=37.3399, lon=127.1084, lawd="41135", dongs=["구미동"],
                    desc="성남 분당구 구미동(분당선)."),
    "수원역":   dict(lat=37.2659, lon=126.9997, lawd="41115",
                    dongs=["매산로1가", "매산로2가", "고등동"],
                    desc="수원 팔달구(1호선/수인분당). 모텔·고시원 밀집 지역."),
    "평촌역":   dict(lat=37.3942, lon=126.9636, lawd="41173", dongs=["관양동"],
                    desc="안양 동안구 관양동(4호선). 범계 인접."),
    "광교중앙역": dict(lat=37.2870, lon=127.0538, lawd="41117", dongs=["이의동"],
                    desc="수원 영통구 이의동(신분당선). 광교호수공원."),
    "원천동":   dict(lat=37.2779, lon=127.0439, lawd="41117", dongs=["원천동"],
                    desc="수원 영통구 원천동(삼성전자 서측·아주대). 오피스텔 예약표본 희소."),
    "상갈역":   dict(lat=37.2751, lon=127.1128, lawd="41463", dongs=["상갈동"],
                    desc="용인 기흥구 상갈동(수인분당). MOLIT 비용 표본 얇을 수 있음."),
}

ALIASES = {
    "영통": "영통역", "동탄": "동탄역", "상현": "상현역", "정자": "정자역",
    "서현": "서현역", "오리": "오리역", "수원": "수원역", "평촌": "평촌역",
    "광교중앙": "광교중앙역", "광교": "광교중앙역", "원천": "원천동", "상갈": "상갈역",
}


def resolve(name: str):
    """지역명 -> 사전 항목(dict) + 정규화 이름. 없으면 (None, None)."""
    if not name:
        return None, None
    key = name.strip()
    if key in STATIONS:
        return STATIONS[key], key
    if key in ALIASES:
        k = ALIASES[key]
        return STATIONS[k], k
    return None, None


def known_names():
    return list(STATIONS.keys())
