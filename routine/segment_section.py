# -*- coding: utf-8 -*-
"""segment_section.py — 원룸 vs 원룸 이상(멀티룸) 비교 섹션(06) HTML 생성.

상시 지침상 33m2 스코프는 원룸 오피스텔이라 멀티룸(투룸·N베드·N인)은 공급
집계에서 제외된다. 이 섹션은 그 제외군을 **같은 반경에서 따로 실측**해
"제외한 게 맞는가"를 숫자로 보여준다. 유형은 오피스텔로 고정한다.

수익 계산 금지(사용자 확정): 월세 추정·순수익·손익분기·수익률 없음.
월 기대매출만 주간가 중위 × 4.345주 × 통합가동률(비용 미반영)로 병기한다.

seg_rows JSON 스키마(build_report 가 넘겨준다):
  [{rid, seg_type: '원룸'|'멀티룸', ci: int, comb, solo, wk, py}, ...]
  ci 는 해당 매물이 속한(멀티룸은 가장 가까운) 상위 클러스터 인덱스.
"""
from __future__ import annotations

import statistics

MIN_N = 4          # 이 미만이면 평균을 추세로 읽지 않는다(상시 수칙)
WEEKS = 4.345


def _agg(rs):
    if not rs:
        return None
    c = [r["comb"] for r in rs]
    w = [r["wk"] / 10000 for r in rs if r.get("wk")]
    wk = statistics.median(w) if w else 0.0
    mean = statistics.mean(c)
    return {
        "n": len(rs), "mean": mean, "med": statistics.median(c),
        "solo": statistics.mean(r["solo"] for r in rs), "wk": wk,
        "rev": wk * WEEKS * mean / 100,
        "n95": sum(1 for x in c if x >= 95),
    }


def _card(label, a, tone):
    """세그먼트 1장. a 는 _agg 결과."""
    thin = ('  <span class="badge badge-warn" style="font-size:10px;'
            'padding:1px 7px;">표본 %d실</span>' % a["n"]) if a["n"] < MIN_N else ""
    return (
        '      <div class="card kpi">\n'
        f'        <div class="kpi-label">{label}{thin}</div>\n'
        f'        <div class="kpi-value" style="color:var(--{tone});">'
        f'{a["mean"]:.1f}<span class="kpi-unit">%</span></div>\n'
        f'        <div class="kpi-note">전수 {a["n"]}실 · 중앙값 {a["med"]:.1f}% · '
        f'95% 이상 {a["n95"]}실 · 33m2 단독 {a["solo"]:.1f}%<br>'
        f'주간가 중위 {a["wk"]:.1f}만 · 월 기대매출 {a["rev"]:.1f}만</div>\n'
        '      </div>')


def _rowbar(name, one, mul):
    """권역 1행 — 원룸/멀티룸 막대를 위아래로 쌓는다.

    .track 은 height 20px + overflow:hidden 이라 중첩하면 둘째 막대가 잘린다.
    바깥은 클래스 없는 div 로 감싸고 .track 은 형제로 둔다.
    """
    def bar(a, color):
        if not a:
            return ('<div class="track" style="height:13px;"></div>')
        return (
            f'<div class="track" style="height:13px;">'
            f'<div class="bar" style="width:{a["mean"]:.1f}%;background:{color};">'
            f'</div></div>')
    o_txt = f'{one["mean"]:.1f}%' if one else "—"
    m_txt = (f'{mul["mean"]:.1f}%' + (" ⚠" if mul and mul["n"] < MIN_N else "")) if mul else "—"
    gap = f'{mul["mean"] - one["mean"]:+.1f}%p' if (one and mul) else "—"
    sub = (f'원룸 {one["n"]}실 · 멀티룸 {mul["n"] if mul else 0}실 · '
           f'주간가 {one["wk"]:.1f}만 vs {mul["wk"]:.1f}만' if mul else
           f'원룸 {one["n"]}실 · 반경 내 멀티룸 없음')
    return (
        '      <div class="row">\n'
        f'        <div class="r-name"><div class="nm">{name}</div>'
        f'<div class="sub">{sub}</div></div>\n'
        '        <div style="display:grid;gap:4px;">\n'
        f'          {bar(one, "var(--g-600)")}\n'
        f'          {bar(mul, "var(--terra-500)")}\n'
        '        </div>\n'
        f'        <div class="r-val" style="white-space:nowrap;">{o_txt}<br>'
        f'<span style="color:var(--terra-600);">{m_txt}</span><br>'
        f'<span style="font-size:11px;color:var(--n-500);">{gap}</span></div>\n'
        '      </div>')


def build(seg_rows, cl_idx, place, cluster_names, city):
    """cl_idx 클러스터(반경 500m)를 주역으로, 나머지 권역은 대조로 붙인다."""
    here_one = _agg([r for r in seg_rows
                     if r["seg_type"] == "원룸" and r["ci"] == cl_idx])
    here_mul = _agg([r for r in seg_rows
                     if r["seg_type"] == "멀티룸" and r["ci"] == cl_idx
                     and r.get("in_radius")])
    all_one = _agg([r for r in seg_rows if r["seg_type"] == "원룸"])
    all_mul = _agg([r for r in seg_rows if r["seg_type"] == "멀티룸"])

    if not here_mul:
        lead = (f'{place} 반경 500m 안에는 멀티룸 매물이 없다. '
                f'아래는 {city} 전역 비교다.')
        cards = _card("원룸 (반경 500m)", here_one, "g-600") + "\n" + \
            _card(f"{city} 전역 멀티룸", all_mul, "terra-600")
    else:
        d = here_mul["mean"] - here_one["mean"]
        wkd = ((here_mul["wk"] / here_one["wk"] - 1) * 100) if here_one["wk"] else 0
        same_price = abs(wkd) < 5
        lead = (
            f'{place} 반경 500m 기준 <b>원룸 {here_one["n"]}실 '
            f'{here_one["mean"]:.1f}%</b> 대 <b>멀티룸 {here_mul["n"]}실 '
            f'{here_mul["mean"]:.1f}%</b> — 멀티룸이 <b>{abs(d):.1f}%p '
            f'{"낮다" if d < 0 else "높다"}</b>. '
            + (f'주간가는 {here_one["wk"]:.1f}만 대 {here_mul["wk"]:.1f}만으로 '
               f'사실상 같은 값이라, 이 격차는 단가 차이가 아니라 '
               f'<b>수요 두께의 차이</b>다.'
               if same_price else
               f'주간가는 {here_one["wk"]:.1f}만 대 {here_mul["wk"]:.1f}만'
               f'({wkd:+.0f}%)이라 단가 차이가 함께 작용한다.'))
        cards = _card("원룸 (반경 500m)", here_one, "g-600") + "\n" + \
            _card("원룸 이상 · 멀티룸 (반경 500m)", here_mul, "terra-600")

    bars = "\n".join(
        _rowbar(cluster_names[ci],
                _agg([r for r in seg_rows
                      if r["seg_type"] == "원룸" and r["ci"] == ci]),
                _agg([r for r in seg_rows
                      if r["seg_type"] == "멀티룸" and r["ci"] == ci
                      and r.get("in_radius")]))
        for ci in sorted(cluster_names)
        if any(r["seg_type"] == "원룸" and r["ci"] == ci for r in seg_rows))

    rev_gap = ((all_mul["rev"] / all_one["rev"] - 1) * 100) if all_one["rev"] else 0
    occ_gap = all_mul["mean"] - all_one["mean"]
    wk_gap = ((all_mul["wk"] / all_one["wk"] - 1) * 100) if all_one["wk"] else 0
    solo_gap = all_mul["solo"] - all_one["solo"]

    # 문장은 회차 데이터에서 만든다 — 방향을 고정해 쓰면 결과가 뒤집힌 회차에서
    # 표와 어긋난 해석이 나간다(2026-08-31 양천구에서 발견).
    if abs(wk_gap) < 5:
        wk_txt = (f'멀티룸 단가는 {all_mul["wk"]:.1f}만으로 '
                  f'원룸({all_one["wk"]:.1f}만)과 사실상 같고')
    else:
        wk_txt = (f'멀티룸 단가가 {all_mul["wk"]:.1f}만으로 '
                  f'원룸({all_one["wk"]:.1f}만)보다 '
                  f'{"높고" if wk_gap > 0 else "낮고"}')
    if abs(rev_gap) < 10:
        rev_txt = (f'<b>월 기대매출은 {all_one["rev"]:.1f}만 대 '
                   f'{all_mul["rev"]:.1f}만({rev_gap:+.1f}%)으로 거의 같다</b>')
    else:
        rev_txt = (f'<b>월 기대매출은 {all_one["rev"]:.1f}만 대 '
                   f'{all_mul["rev"]:.1f}만으로 멀티룸이 {abs(rev_gap):.1f}% '
                   f'{"높다" if rev_gap > 0 else "낮다"}</b>')
    if abs(occ_gap) < 3:
        head_txt = '두 세그먼트의 가동률은 사실상 같다'
    elif occ_gap > 0:
        head_txt = f'멀티룸이 {abs(occ_gap):.1f}%p 더 차 있다'
    else:
        head_txt = f'멀티룸이 {abs(occ_gap):.1f}%p 덜 차 있다'
    if abs(solo_gap) < 5:
        ch_txt = (f'채널 구조는 비슷하다: 33m2 단독 비중이 멀티룸 '
                  f'{all_mul["solo"]:.1f}%, 원룸 {all_one["solo"]:.1f}%다. ')
    else:
        hi, lo = ('멀티룸', '원룸') if solo_gap > 0 else ('원룸', '멀티룸')
        ch_txt = (f'채널 구조는 갈린다: 33m2 단독 비중이 멀티룸 '
                  f'{all_mul["solo"]:.1f}%, 원룸 {all_one["solo"]:.1f}%로, '
                  f'{hi}이 {lo}보다 33m2 의존도가 높다. ')

    note = (
        f'{city} 전역으로 넓히면 원룸 {all_one["n"]}실 {all_one["mean"]:.1f}% 대 '
        f'멀티룸 {all_mul["n"]}실 {all_mul["mean"]:.1f}%로 {head_txt}. '
        f'{wk_txt} {rev_txt}. {ch_txt}'
        f'표본 {MIN_N}실 미만 셀(⚠)은 평균을 추세로 읽지 말 것.')

    return (
        '<!-- ========== (6) 원룸 vs 멀티룸 ========== -->\n'
        '<section class="sec">\n'
        '  <div class="wrap">\n'
        '    <div class="sec-head">\n'
        '      <div class="sec-num">06</div>\n'
        '      <div>\n'
        '        <h2 class="sec-title">원룸 vs 원룸 이상(멀티룸)</h2>\n'
        '        <p class="sec-sub">공급 집계에서 제외한 멀티룸(투룸·N베드·N인)을 '
        '같은 반경에서 따로 실측했다 — 유형은 오피스텔로 고정</p>\n'
        '      </div>\n'
        '    </div>\n\n'
        '    <div class="verdict" style="margin-bottom:20px;">\n'
        '      <div class="verdict-mark">SPLIT</div>\n'
        f'      <p class="verdict-text">{lead}</p>\n'
        '    </div>\n\n'
        '    <div class="card-grid cols-2">\n'
        f'{cards}\n'
        '    </div>\n\n'
        '    <div class="chart-legend" style="margin-top:24px;">\n'
        '      <span><i class="sw-occ"></i>원룸</span>\n'
        '      <span><i class="sw-top" style="background:var(--terra-500);"></i>'
        '멀티룸</span>\n'
        '      <span style="margin-left:auto;font-family:var(--font-data);">'
        '권역별 통합 가동률 · 각 권역 반경 500m 전수</span>\n'
        '    </div>\n'
        '    <div class="chart">\n'
        f'{bars}\n'
        '    </div>\n\n'
        f'    <p class="chart-note"><span class="dot"></span><b>해석</b> — {note}</p>\n'
        '  </div>\n'
        '</section>\n\n')
