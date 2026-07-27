# -*- coding: utf-8 -*-
"""model.py — 정본 수익 산식 + 앵커 자기검증.

정본 산식(yield_deposit_bands.md §1, 변형 금지):
  월 순익 = share × [ 주간가중위×4.345×예약률×0.967
                      + 3만×4.345×예약률
                      − 3.2만
                      − (밴드월세 + 관리비 + 공과금) ]
  연 수익률(%) = 월순익 × 12 ÷ 해당 보증금(500 또는 1000) × 100

모듈 로드 시 영통 앵커로 자기검증한다:
  주간 33만 · 통합가동률 69.1% · all-in 60만(밴드월세+관리비) · 공과금 미가산
  → share 60% = 월 24.97만(±0.1), 50% = 20.81만.
검증 실패 시 즉시 예외로 중단(산식 변형 사고 방지 — 실제 청소마진 만실 계산 사고 있었음).
"""
from __future__ import annotations

from config import (
    WEEKS_PER_MONTH, FEE_FACTOR, CLEANING_INCOME_WEEK, CLEANING_COST,
    UTILITIES, SHARE_PRIMARY, SHARE_ALT,
)


def monthly_profit(weekly_price_man: float, occupancy: float,
                   band_rent_man: float, mgmt_man: float,
                   utilities_man: float = UTILITIES,
                   share: float = SHARE_PRIMARY) -> float:
    """월 순익(만원). 모든 금액 만원 단위, occupancy는 0~1.

    - weekly_price_man: 주간가 중위(임대료+관리비, 만원)
    - band_rent_man: 밴드 월세 중위(신고 원값, 만원)
    - mgmt_man: 관리비 가정(만원)
    - utilities_man: 공과금(만원). 앵커 재현 시 0 전달 가능.
    - share: 배분율(0.60 주 / 0.50 병기)
    """
    revenue = (weekly_price_man * WEEKS_PER_MONTH * occupancy * FEE_FACTOR
               + CLEANING_INCOME_WEEK * WEEKS_PER_MONTH * occupancy)
    cost = CLEANING_COST + band_rent_man + mgmt_man + utilities_man
    return share * (revenue - cost)


def annual_yield_pct(monthly_profit_man: float, deposit_man: float) -> float:
    """연 수익률(%) = 월순익×12 ÷ 보증금 × 100."""
    if not deposit_man:
        return float("nan")
    return monthly_profit_man * 12.0 / deposit_man * 100.0


def all_in_cost(band_rent_man: float, mgmt_man: float,
                utilities_man: float = UTILITIES) -> float:
    """all-in 월 고정비(밴드월세+관리비+공과금, 만원)."""
    return band_rent_man + mgmt_man + utilities_man


# --------------------------------------------------------------------------- #
# 앵커 자기검증 (모듈 로드 시 실행)
# --------------------------------------------------------------------------- #
class AnchorError(RuntimeError):
    """정본 산식이 앵커 기대값에서 벗어났을 때."""


def _verify_anchor():
    # 영통 앵커: 주간 33만, 통합가동률 69.1%, all-in 60만(밴드월세+관리비), 공과금 미가산.
    # band_rent_man=60(=all-in 60), mgmt=0, utilities=0 으로 all-in 60·공과금0 재현.
    p60 = monthly_profit(33.0, 0.691, band_rent_man=60.0, mgmt_man=0.0,
                         utilities_man=0.0, share=0.60)
    p50 = monthly_profit(33.0, 0.691, band_rent_man=60.0, mgmt_man=0.0,
                         utilities_man=0.0, share=0.50)
    if abs(p60 - 24.97) > 0.1:
        raise AnchorError(
            f"앵커 60% 검증 실패: {p60:.4f}만 (기대 24.97±0.1). 산식/상수 변형 의심.")
    if abs(p50 - 20.81) > 0.1:
        raise AnchorError(
            f"앵커 50% 검증 실패: {p50:.4f}만 (기대 20.81±0.1). 산식/상수 변형 의심.")
    return p60, p50


ANCHOR = _verify_anchor()   # import 시점에 실행 — 실패하면 여기서 즉시 중단.


if __name__ == "__main__":
    p60, p50 = ANCHOR
    print(f"[앵커 자기검증 통과] 영통 주간33만·69.1%·all-in60·공과금0")
    print(f"  60% = {p60:.2f}만 (기대 24.97)  |  50% = {p50:.2f}만 (기대 20.81)")
