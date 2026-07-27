# -*- coding: utf-8 -*-
"""rules.py — 컨설팅 휴리스틱을 결정적 룰로 코드화한 판단 엔진.

정본: plan_src/yield_deposit_bands.md (v3). 이 프로젝트에서 실증·확정된
해석 규칙을 사람 판단 없이 재현 가능한 코드로 옮긴다:

  1. 품질교락 감지  — 저가 밴드 비용이 특정 구축 단지에 쏠렸는데 매출은
                       상위 리스팅급 → 수익률 상향 편향(정자500 사례).
  2. 신뢰등급 A/B/C — 매출·비용 표본 두께 + 교락 여부로 셀별 등급.
  3. 타채널 해석    — 타채널비중(통합−단독)으로 운영전제 문구 자동 부착.
  4. 추천 생성      — 계산 가능한 밴드 셀을 수익률순 정렬 → 등급·경고 반영해
                       1순위/조건부/부적합 + 근거·리스크 1줄.

model.py 의 앵커 자기검증과 동일 철학: 모듈 로드 시 정본 사례로 룰을
자기검증(_selftest)한다. 룰 로직이 드리프트하면 여기서 즉시 중단.
"""
from __future__ import annotations

import statistics
from collections import Counter
from typing import Optional

# --------------------------------------------------------------------------- #
# 임계값 (yield_deposit_bands.md 실증 기준)
# --------------------------------------------------------------------------- #
COMPLEX_DOMINANCE = 0.60     # (a) 단일 단지 점유율 ≥60% = 밴드 비용이 한 단지에 지배됨
AREA_GAP = 0.30             # (b) 밴드 간 면적 중위 괴리 ≥30% (보강 근거)
RENT_GAP_RATIO = 1.30       # (c) 상대 밴드 월세중위 ≥1.3× → 이 밴드가 유의하게 저가
OTHER_CH_MULTI = 0.15       # 타채널비중 ≥15p → 멀티채널 운영 전제
OTHER_CH_SINGLE = 0.05      # 타채널비중 ≤5p → 단일 채널로도 실현
OTHER_CH_EXTREME = 0.25     # 타채널비중 ≥25p → 33m2 단독 미포착(멀티채널 필수)

GRADE_A_COST = 30           # A: 비용표본 ≥30
GRADE_C_COST = 10           # C: 비용표본 <10
REV_MIN_SAMPLES = 5         # 매출표본 ≥5 (A 조건)

_BANDS = ("500", "1000")


# --------------------------------------------------------------------------- #
# 헬퍼
# --------------------------------------------------------------------------- #
def _top_complex_share(rows) -> tuple:
    """비용표본 rows 에서 최빈 단지명과 점유율(0~1). rows 없으면 (None,0)."""
    names = [(r.get("offi") or "").strip() for r in rows if r.get("offi")]
    if not names:
        return None, 0.0
    name, cnt = Counter(names).most_common(1)[0]
    return name, cnt / len(rows)


def _area_median(rows) -> Optional[float]:
    areas = [r.get("area") for r in rows if r.get("area")]
    return round(statistics.median(areas), 1) if areas else None


def _rev_samples(ctx) -> int:
    """매출표본 수: 예약률 측정 시 캘린더 표본 n, 아니면 공급 주간가 표본 n."""
    occ = ctx.get("occupancy")
    if occ and occ.get("ok"):
        return occ.get("n", 0)
    return (ctx.get("supply") or {}).get("weekly", {}).get("n", 0)


# --------------------------------------------------------------------------- #
# 1) 품질교락 감지
# --------------------------------------------------------------------------- #
def detect_confounding(bands: dict) -> dict:
    """밴드별 품질교락(quality confounding) 의심 여부 + 근거.

    저가 밴드의 비용표본이 (a) 단일 단지에 지배되고 (c) 상대 밴드보다
    유의하게 저가면, 그 밴드의 낮은 월세는 특정(대개 구축) 단지값인데
    매출(주간가)은 지역 전체 리스팅에서 나오므로 수익률이 상향 편향된다.
    (b) 면적 괴리가 크면 근거로 추가(정자 사례는 면적 괴리는 작음).

    반환: {"500": {...}, "1000": {...}} 각:
       {"suspected": bool, "evidence": [str], "top_complex": str,
        "top_share": float}
    """
    out = {}
    # 상대 밴드 참조를 위해 먼저 요약
    summ = {}
    for k in _BANDS:
        b = bands.get(k, {})
        rows = b.get("rows") or []
        name, share = _top_complex_share(rows)
        summ[k] = {
            "sufficient": bool(b.get("sufficient")),
            "n": b.get("n", 0),
            "rent_median": b.get("rent_median"),
            "area_median": _area_median(rows),
            "top_complex": name, "top_share": share,
        }

    for k in _BANDS:
        s = summ[k]
        other_k = "1000" if k == "500" else "500"
        o = summ[other_k]
        ev = []
        suspected = False
        if s["sufficient"] and s["rent_median"] is not None:
            cond_a = s["top_share"] >= COMPLEX_DOMINANCE and s["top_complex"]
            # (c): 상대 밴드가 계산 가능하고, 이 밴드가 상대보다 유의하게 저가
            cond_c = (o["sufficient"] and o["rent_median"]
                      and o["rent_median"] >= s["rent_median"] * RENT_GAP_RATIO)
            # (b): 밴드 간 면적 중위 괴리 ≥30% (보강)
            cond_b = False
            if s["area_median"] and o["area_median"]:
                lo, hi = sorted((s["area_median"], o["area_median"]))
                cond_b = (hi - lo) / lo >= AREA_GAP
            # 트리거: (a) 필수 + (c) 또는 (b) 중 하나 이상
            if cond_a and (cond_c or cond_b):
                suspected = True
                ev.append(
                    f"비용표본 {s['n']}건 중 '{s['top_complex']}' "
                    f"{s['top_share']*100:.0f}% 점유(단일단지 지배)")
                if cond_c:
                    ev.append(
                        f"{k}밴드 월세중위 {s['rent_median']:g}만이 "
                        f"{other_k}밴드 {o['rent_median']:g}만보다 "
                        f"{(1 - s['rent_median']/o['rent_median'])*100:.0f}% 저가 "
                        f"→ 저가 밴드 비용은 특정 단지값, 매출 주간가는 지역 전체 리스팅")
                if cond_b:
                    ev.append(
                        f"밴드 간 면적 중위 괴리 "
                        f"{s['area_median']:g}㎡ vs {o['area_median']:g}㎡")
                ev.append(
                    f"의사결정 게이트: {k}밴드에서 매출 앵커급(프라임) 유닛을 실제 "
                    f"보증금 {k}/월세 {s['rent_median']:g}만에 임차 가능한지 실사 필요")
        out[k] = {"suspected": suspected, "evidence": ev,
                  "top_complex": s["top_complex"], "top_share": s["top_share"]}
    return out


# --------------------------------------------------------------------------- #
# 2) 신뢰등급 A/B/C
# --------------------------------------------------------------------------- #
def grade_band(cost_n: int, rev_n: int, confounded: bool) -> tuple:
    """셀 신뢰등급 (grade, 근거문자열).

    A = 매출표본 ≥5 AND 비용표본 ≥30 AND 교락 없음
    C = 비용표본 <10 OR 교락 의심 OR 매출표본 <5
    B = 그 외(비용 10~29, 교락 없음, 매출 ≥5)
    """
    if confounded:
        return "C", f"품질교락 의심(비용n={cost_n})"
    if cost_n < GRADE_C_COST or rev_n < REV_MIN_SAMPLES:
        why = []
        if cost_n < GRADE_C_COST:
            why.append(f"비용표본 부족(n={cost_n}<10)")
        if rev_n < REV_MIN_SAMPLES:
            why.append(f"매출표본 부족(n={rev_n}<5)")
        return "C", " · ".join(why)
    if cost_n >= GRADE_A_COST and rev_n >= REV_MIN_SAMPLES:
        return "A", f"비용표본 두터움(n={cost_n}≥30)·매출표본 {rev_n}·교락 없음"
    return "B", f"비용표본 중간(n={cost_n})·매출표본 {rev_n}·교락 없음"


# --------------------------------------------------------------------------- #
# 3) 타채널 해석
# --------------------------------------------------------------------------- #
def channel_interpretation(other_channel: Optional[float]) -> Optional[dict]:
    """타채널비중(통합−단독, 0~1)을 운영전제 문구로 해석.

    ≥25p → 극단(멀티채널 필수) / ≥15p → 멀티채널 전제 /
    ≤5p → 단일 채널로도 실현 / 그 외 → 혼합.
    측정 안 됐으면(None) None 반환.
    """
    if other_channel is None:
        return None
    p = other_channel * 100
    if other_channel >= OTHER_CH_EXTREME:
        return {"level": "extreme", "points": p,
                "text": (f"타채널비중 +{p:.1f}p(≥25p, 극단) — 33m2 단독 노출로는 "
                         f"수요 미포착, 멀티채널 운영 필수(staySync 대응).")}
    if other_channel >= OTHER_CH_MULTI:
        return {"level": "multi", "points": p,
                "text": (f"타채널비중 +{p:.1f}p(≥15p) — 수요 상당분이 33m2 밖 → "
                         f"멀티채널 운영 전제(staySync로 대응 가능).")}
    if other_channel <= OTHER_CH_SINGLE:
        return {"level": "single", "points": p,
                "text": (f"타채널비중 +{p:.1f}p(≤5p) — 수요 대부분이 33m2 네이티브 → "
                         f"단일 채널로도 그대로 실현(가정 의존 최소).")}
    return {"level": "mixed", "points": p,
            "text": (f"타채널비중 +{p:.1f}p — 단일·멀티 혼합 시장. "
                     f"33m2 단독분 외 상당수가 타 채널 예약.")}


# --------------------------------------------------------------------------- #
# 4) 추천 생성
# --------------------------------------------------------------------------- #
def recommend(scenarios: list, confound: dict, grades: dict,
              channel: Optional[dict]) -> list:
    """계산 가능한 밴드 셀을 수익률(60%)순 정렬 → 판정.

    판정:
      부적합 = 월순익 60% ≤ 0(적자)
      조건부 = 품질교락 의심 OR 등급 C OR 타채널 극단(≥25p)
      1순위/대안 = 그 외(수익률 최상 = 1순위, 이하 = 대안)
    각 셀에 근거(basis)·남은 리스크(risk) 1줄 부착.
    """
    cells = sorted(scenarios, key=lambda s: s["yield60"], reverse=True)
    judged = []
    rank = 0
    for sc in cells:
        band = sc["band"]
        cf = confound.get(band, {})
        gr, gr_reason = grades.get(band, ("C", "미상"))
        confounded = cf.get("suspected", False)
        loss = sc["profit60"] <= 0
        extreme_ch = channel and channel["level"] == "extreme"

        if loss:
            verdict = "부적합"
            basis = f"월순익 60% {sc['profit60']:.1f}만 적자 — all-in 비용이 매출 초과."
            risk = "가격/비용 개선 없이는 진입 부적합."
        elif confounded:
            verdict = "조건부"
            basis = (f"명목 연 {sc['yield60']:.1f}%이나 품질교락 미해소(등급 {gr}). "
                     + (cf["evidence"][0] if cf.get("evidence") else ""))
            risk = "실사로만 해소되는 밴드-품질 불일치 — 프라임 유닛 실제 임차가 확인 필수."
        elif gr == "C":
            verdict = "조건부"
            basis = f"연 {sc['yield60']:.1f}%이나 신뢰등급 C({gr_reason})."
            risk = "표본 재확보 전 참고치 — 추가 실거래/예약 표본으로 검증 권고."
        elif extreme_ch:
            verdict = "조건부"
            basis = (f"연 {sc['yield60']:.1f}%(등급 {gr})이나 {channel['text']}")
            risk = "멀티채널 운영 미도입 시 33m2 단독 수요만으론 미실현 가능."
        else:
            rank += 1
            verdict = "1순위" if rank == 1 else "대안"
            basis = f"연 {sc['yield60']:.1f}% · 월순익 {sc['profit60']:.1f}만 · 등급 {gr}({gr_reason})."
            if channel and channel["level"] == "multi":
                risk = f"{channel['text']} 다니엘스테이 staySync로 대응 가능."
            elif channel and channel["level"] == "single":
                risk = "가정 의존 최소 — 단일 채널로 실현되는 안정 셀."
            else:
                risk = "예약률 가정 민감 — 실측 세션으로 확정 권고." if channel is None \
                       else f"{channel['text']}"
        judged.append({
            "band": band, "deposit": sc["deposit"], "verdict": verdict,
            "grade": gr, "yield60": sc["yield60"], "yield50": sc["yield50"],
            "profit60": sc["profit60"], "profit50": sc["profit50"],
            "basis": basis, "risk": risk, "confounded": confounded,
        })
    return judged


def _principle_note(scenarios: list) -> Optional[str]:
    """500/1000 둘 다 계산 가능하면 '수익률 극대화=500, 현금 극대화=1000' 원칙."""
    bands = {s["band"] for s in scenarios}
    if "500" in bands and "1000" in bands:
        return ("원칙: 수익률(%) 극대화 = 보증금 500밴드(분모↓), "
                "월 현금순익 극대화 = 1000밴드. 둘은 트레이드오프.")
    return None


# --------------------------------------------------------------------------- #
# 통합 진입점
# --------------------------------------------------------------------------- #
def analyze(ctx: dict) -> dict:
    """ctx(analyzer 파이프라인 결과) → 분석·추천 블록.

    ctx 요구: supply, occupancy, molit{bands}, scenarios.
    반환 dict 를 ctx['analysis'] 로 붙이면 report.py 가 렌더.
    """
    bands = ctx["molit"]["bands"]
    scenarios = ctx.get("scenarios") or []
    rev_n = _rev_samples(ctx)

    confound = detect_confounding(bands)
    grades = {}
    for k in _BANDS:
        b = bands.get(k, {})
        grades[k] = grade_band(b.get("n", 0), rev_n,
                               confound.get(k, {}).get("suspected", False))

    occ = ctx.get("occupancy")
    other_ch = occ.get("other_channel") if (occ and occ.get("ok")) else None
    channel = channel_interpretation(other_ch)

    recs = recommend(scenarios, confound, grades, channel)

    # 전체 등급 = 최상위 추천 셀의 등급(없으면 계산 가능 밴드 중 최선, 그것도 없으면 C)
    if recs:
        grade_overall = recs[0]["grade"]
        grade_reason = f"최상위 셀({recs[0]['band']}밴드) 기준: {grades[recs[0]['band']][1]}"
    else:
        computable = [grades[k] for k in _BANDS if bands.get(k, {}).get("sufficient")]
        if computable:
            best = min(computable, key=lambda g: {"A": 0, "B": 1, "C": 2}[g[0]])
            grade_overall, grade_reason = best[0], best[1] + " (예약률 미측정, 셀 판정 보류)"
        else:
            grade_overall = "C"
            grade_reason = "계산 가능한 밴드 없음(표본 부족)"

    confounding_warnings = [
        {"band": k, "evidence": confound[k]["evidence"]}
        for k in _BANDS if confound[k]["suspected"]
    ]

    return {
        "grade_overall": grade_overall,
        "grade_reason": grade_reason,
        "band_grades": {k: {"grade": grades[k][0], "reason": grades[k][1]}
                        for k in _BANDS},
        "confounding": confound,
        "confounding_warnings": confounding_warnings,
        "channel": channel,
        "recommendations": recs,
        "principle": _principle_note(scenarios),
        "rev_samples": rev_n,
    }


# --------------------------------------------------------------------------- #
# 자기검증 (모듈 로드 시 실행) — 정본 사례로 룰 드리프트 방지
# --------------------------------------------------------------------------- #
class RuleError(RuntimeError):
    """룰 로직이 정본 사례 기대치에서 벗어났을 때."""


def _mk_rows(specs):
    """(offi, rent, area, deposit) 리스트 → band rows 형태."""
    return [{"offi": o, "rent": r, "area": a, "deposit": d} for o, r, a, d in specs]


def _selftest():
    # 정자500 사례: 우정오피스텔 71% 지배, 월세중위 60, 상대 1000밴드 95
    jeongja_500_rows = _mk_rows(
        [("우정오피스텔", 60, 25.1, 500)] * 20
        + [("정자동3차 푸르지오 시티", 60, 26, 500)] * 5
        + [("백궁 동양파라곤", 60, 27, 500)] * 3)
    jeongja_1000_rows = _mk_rows(
        [("정자동3차 푸르지오 시티", 95, 27, 1000)] * 100
        + [("정자역 AK 와이즈플레이스", 95, 26, 1000)] * 200)
    jeongja = {
        "500": {"sufficient": True, "n": 28, "rent_median": 60.0,
                "rows": jeongja_500_rows},
        "1000": {"sufficient": True, "n": 302, "rent_median": 95.0,
                 "rows": jeongja_1000_rows},
    }
    cf = detect_confounding(jeongja)
    if not cf["500"]["suspected"]:
        raise RuleError("정자500 품질교락이 감지되지 않음 — (a)/(c) 룰 드리프트 의심.")
    if cf["1000"]["suspected"]:
        raise RuleError("정자1000이 오탐으로 교락 판정됨 — 룰 과민.")
    g500, _ = grade_band(28, 10, cf["500"]["suspected"])
    if g500 != "C":
        raise RuleError(f"정자500 등급 기대 C, 실제 {g500} — 교락→C 룰 드리프트.")

    # 동탄 사례: 최빈 단지 32%(<60), 저가밴드 아님 → 교락 없음, 등급 A
    dt_500_rows = _mk_rows(
        [("동탄센트럴에이스타워", 60, 19.4, 500)] * 28
        + [("스마트리움오피스텔", 60, 20, 500)] * 16
        + [("기타", 60, 21, 500)] * 43)
    dt = {
        "500": {"sufficient": True, "n": 87, "rent_median": 60.0,
                "rows": dt_500_rows},
        "1000": {"sufficient": True, "n": 11, "rent_median": 55.0,
                 "rows": _mk_rows([("스마트리움오피스텔", 55, 22, 1000)] * 11)},
    }
    cf_dt = detect_confounding(dt)
    if cf_dt["500"]["suspected"]:
        raise RuleError("동탄500이 오탐으로 교락 판정됨 — 단일단지 지배 아님인데 발화.")
    g_dt, _ = grade_band(87, 10, False)
    if g_dt != "A":
        raise RuleError(f"동탄500 등급 기대 A, 실제 {g_dt} — 등급 룰 드리프트.")

    # 타채널 해석: 동탄 +2.7p=단일, 상현 +16.8p=멀티, 수원 +25.0p=극단
    if channel_interpretation(0.027)["level"] != "single":
        raise RuleError("동탄 +2.7p 가 '단일 채널'로 해석되지 않음.")
    if channel_interpretation(0.168)["level"] != "multi":
        raise RuleError("상현 +16.8p 가 '멀티채널'로 해석되지 않음.")
    if channel_interpretation(0.250)["level"] != "extreme":
        raise RuleError("수원 +25.0p 가 '극단'으로 해석되지 않음.")
    return True


SELFTEST_OK = _selftest()   # 로드 시 실행 — 실패하면 즉시 중단.


if __name__ == "__main__":
    print("[rules 자기검증 통과]")
    print("  정자500 → 품질교락 감지 + 등급 C")
    print("  동탄500 → 교락 없음 + 등급 A")
    print("  타채널: +2.7p=단일 / +16.8p=멀티 / +25.0p=극단")
