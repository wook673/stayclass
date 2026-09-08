# -*- coding: utf-8 -*-
"""eval_section.py — 실측치만으로 구성한 컨설턴트 평가 섹션(05) HTML 생성.

수익 계산 금지(사용자 확정): 월세 추정·순수익·손익분기·수익률·MOLIT 없음.
등급은 통합 가동률 평균·중앙값만으로 정한다.
"""
from __future__ import annotations

import statistics


def grade_of(mean_c, med_c):
    if mean_c >= 75 and med_c >= 85:
        return "A", "badge-ok", "즉시 진입 검토 대상"
    if mean_c >= 65:
        return "B", "badge-info", "우선 후보 — 조건 확인 후 진입"
    return "C", "badge-warn", "관찰 대상 — 단가·물건별 편차 확인 필요"


def build(rows, sup, cl_idx, mean_c, med_c, wk_med, window, caveat=""):
    n = len(rows)
    combs = [r["comb"] for r in rows]
    n95 = sum(1 for x in combs if x >= 95)
    n100 = sum(1 for x in combs if x >= 99.9)
    nlow = sum(1 for x in combs if x < 25)
    alt_only = sum(1 for r in rows if r["solo"] == 0)
    solo_major = sum(1 for r in rows if r["solo"] >= 50)

    lo = [r["comb"] for r in rows
          if r.get("weekly") and r["weekly"] / 10000 <= wk_med]
    hi = [r["comb"] for r in rows
          if r.get("weekly") and r["weekly"] / 10000 > wk_med]
    lo_m = statistics.mean(lo) if lo else 0.0
    hi_m = statistics.mean(hi) if hi else 0.0

    pys = [r["pyeong"] for r in rows if r.get("pyeong")]
    py_med = statistics.median(pys) if pys else None

    # 같은 회차 상위 클러스터 단가 대비 위치
    peers = [c["weekly_median"] / 10000
             for i, c in enumerate(sup["clusters"][:6])
             if i != cl_idx and c.get("weekly_median")]
    peer_med = statistics.median(peers) if peers else None

    grade, gcls, head = grade_of(mean_c, med_c)

    dist = (f"전수 {n}실 중 {n95}실({n95 / n * 100:.0f}%)이 95% 이상이고 "
            f"그중 {n100}실은 측정창 내내 만실이다. 25% 미만은 {nlow}실뿐이라 "
            f"소수 우량 매물이 끌어올린 평균이 아니라 지역 전반이 차 있는 "
            f"구조다. 중앙값 {med_c:.1f}%가 평균 {mean_c:.1f}%보다 높은 것도 "
            f"같은 신호다.")

    chan = (f"{n}실 중 {alt_only}실({alt_only / n * 100:.0f}%)은 33m2 자체 "
            f"예약이 0이고 전량 타 채널에서 팔린다. 33m2 단독으로 절반 이상을 "
            f"채우는 매물은 {solo_major}실뿐이다. 이 지역의 표준 운영은 "
            f"멀티채널이며, 33m2 한 채널만 붙여서는 이 가동률이 재현되지 않는다.")

    price = (f"주간가 중위({wk_med:.1f}만) 이하 매물의 평균 가동률은 "
             f"{lo_m:.1f}%, 초과 매물은 {hi_m:.1f}%다. {lo_m - hi_m:+.1f}%p "
             f"차이는 수요가 가격에 민감하다는 뜻이고, 중위 언저리가 시장이 "
             f"받아들이는 상단이라는 의미다.")

    pos = ""
    if peer_med:
        rel = ((wk_med - peer_med) / peer_med) * 100
        pos = (f"같은 회차 다른 상위 클러스터의 단가 중위({peer_med:.1f}만) "
               f"대비 {rel:+.0f}%다. ")
    if py_med:
        spec = (pos + f"물건 규격은 중위 {py_med:g}평(약 {py_med * 3.3:.0f}"
                      f"&#13217;)으로 소형 원룸 오피스텔 구간에 들어온다.")
    else:
        spec = pos + "물건 규격 표본이 부족하다."

    cav = (f"측정창은 앞으로의 56일({window}) 예약 상황이라 계절성은 반영되지 "
           f"않는다. 통합 가동률은 예약 + 타채널 차단을 합산한 정본 지표다.")
    if caveat:
        cav = caveat + " " + cav

    card = ('      <div class="card">\n'
            '        <div class="kpi-label">{label}</div>\n'
            '        <p style="margin-top:10px;font-size:14px;line-height:1.7;'
            'color:var(--n-700);">{body}</p>\n'
            '      </div>')
    cards = "\n".join([
        card.format(label=('① 수요의 폭 <span class="badge %s" style="font-size:'
                           '10px;padding:1px 7px;">강함</span>' % gcls),
                    body=dist),
        card.format(label=('② 채널 구조 <span class="badge badge-warn" '
                           'style="font-size:10px;padding:1px 7px;">운영 조건'
                           '</span>'), body=chan),
        card.format(label="③ 가격 민감도", body=price),
        card.format(label="④ 단가 위치와 물건 규격", body=spec),
    ])

    return (
        '<!-- ========== (5) 평가 ========== -->\n'
        '<section class="sec sec-alt">\n'
        '  <div class="wrap">\n'
        '    <div class="sec-head">\n'
        '      <div class="sec-num">05</div>\n'
        '      <div>\n'
        '        <h2 class="sec-title">컨설턴트 평가</h2>\n'
        '        <p class="sec-sub">실측치만으로 내린 판단 — 월세·수익률 '
        '추정은 넣지 않는다</p>\n'
        '      </div>\n'
        '    </div>\n\n'
        '    <div class="verdict" style="margin-bottom:20px;">\n'
        '      <div class="verdict-mark">GRADE</div>\n'
        '      <p class="verdict-text">\n'
        f'        진입 우선순위 <b>{grade}</b> · {head} —\n'
        f'        통합 가동률 <b>{mean_c:.1f}%</b> · '
        f'<span class="hl">중앙값 {med_c:.1f}%</span> ·\n'
        f'        주간가 중위 <b>{wk_med:.1f}만</b>\n'
        '      </p>\n'
        '    </div>\n\n'
        '    <div class="card-grid cols-2">\n'
        f'{cards}\n'
        '    </div>\n\n'
        f'    <p class="chart-note"><span class="dot"></span><b>유의점</b> — '
        f'{cav}</p>\n'
        '  </div>\n'
        '</section>\n\n')
