# -*- coding: utf-8 -*-
"""config.py — 경로·상수 정본.

산식 고정 가정(yield_deposit_bands.md 정본)과 파일 경로를 한 곳에 모은다.
값을 바꾸면 앵커 자기검증(model.py)이 깨질 수 있으므로 주의.
"""
from __future__ import annotations

import os

# --------------------------------------------------------------------------- #
# 경로
# --------------------------------------------------------------------------- #
BASE_DIR = os.path.dirname(os.path.abspath(__file__))          # market-analyzer/
REPO_ROOT = os.path.dirname(BASE_DIR)                          # test/
PLAN_SRC = os.path.join(REPO_ROOT, "plan_src")

# MOLIT 서비스키: plan_src/molit.key 를 그대로 읽는다(.gitignore 등록됨).
MOLIT_KEY_FILE = os.path.join(PLAN_SRC, "molit.key")
# HTML 리포트 디자인 토큰(인라인용)
TOKENS_CSS = os.path.join(PLAN_SRC, "tokens.css")

CACHE_DIR = os.path.join(BASE_DIR, ".cache")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# --------------------------------------------------------------------------- #
# 산식 고정 가정 (yield_deposit_bands.md §1 정본 — 변형 금지)
# --------------------------------------------------------------------------- #
WEEKS_PER_MONTH = 4.345        # 월 환산 주 수
FEE_FACTOR = 0.967            # 플랫폼 수수료 3.3% 차감(=1-0.033)
CLEANING_INCOME_WEEK = 3.0    # 청소수입 3만원/주 (예약률 비례)
CLEANING_COST = 3.2          # 청소실비 3.2만원/월
UTILITIES = 6.0              # 공과금 6만원/월 고정
DEFAULT_MGMT = 10.0          # 관리비 기본 10만원/월(리포트에 가정 명기, --mgmt로 조정)

SHARE_PRIMARY = 0.60         # 다니엘스테이 배분율 주(主)
SHARE_ALT = 0.50             # 병기

# 보증금 밴드 (신고 월세 원값, 환산 없음) — disjoint
BAND_500 = (300, 700)        # 300~700만 -> 분모 500만
BAND_1000 = (700, 1300)      # 700 초과~1300만 -> 분모 1000만 (하한 배타)
DEPOSIT_500 = 500
DEPOSIT_1000 = 1000
MIN_BAND_SAMPLES = 3         # 표본<3 밴드는 "표본 부족" (추정 금지)

MAX_AREA_SQM = 33.0          # 전용 ≤33㎡

# --------------------------------------------------------------------------- #
# 수집 상수
# --------------------------------------------------------------------------- #
THROTTLE_SEC = 1.0           # 33m2 요청 간 최소 대기(상시 지침: 1초)
DEFAULT_RADIUS_M = 500
DEFAULT_MONTHS = 6
DEFAULT_WEEKS = 8            # 예약률 조사 창(주)
# 예약률 캘린더 표본 수(가격 중위권). 상현역 실측에서 표본 10 → 80.0%,
# 표본 15 → 63.4%로 16.6%p 벌어져 표본 민감도가 크게 확인됨(2026-07-27).
# 매물 간 편차가 큰 시장에서 평균이 흔들리지 않도록 기본 표본을 넓게 잡는다.
DEFAULT_SAMPLES = 30


def ensure_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
