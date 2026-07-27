# -*- coding: utf-8 -*-
"""report.py — 콘솔 요약 + Markdown + HTML 리포트 생성.

HTML은 plan_src/tokens.css 를 인라인하고 다니엘스테이 딥그린 디자인을 사용.
표기월세는 MOLIT 신고 원값, 표본수·캐비앗을 자동 포함.
"""
from __future__ import annotations

import datetime
import html
import os

from config import (
    TOKENS_CSS, OUTPUT_DIR, DEFAULT_MGMT, UTILITIES, DEPOSIT_500, DEPOSIT_1000,
)

# --------------------------------------------------------------------------- #
# 포맷 헬퍼
# --------------------------------------------------------------------------- #
def _won(v):
    return f"{v:,.0f}원" if v is not None else "—"


def _man(v, suffix="만"):
    return f"{v:g}{suffix}" if v is not None else "—"


def _pct(v):
    return f"{v*100:.1f}%" if v is not None else "—"


def _today():
    return datetime.date.today().isoformat()


def _window_label(ctx) -> str:
    """측정 창 라벨 — '향후 8주 선점률 (예약+차단, 측정일 2026-07-27 기준)'."""
    weeks = ctx.get("weeks", 8)
    today = datetime.date.today()
    if ctx.get("window", "future") == "past":     # 하위호환(미지원 경로)
        start = today - datetime.timedelta(days=weeks * 7)
        return (f"지난 {weeks}주 (API 미지원 — 33m2가 과거 날짜 미반환) "
                f"({start.isoformat()} ~ {today.isoformat()} 직전)")
    end = today + datetime.timedelta(days=weeks * 7)
    return (f"향후 {weeks}주 선점률 (예약+차단, 측정일 {today.isoformat()} 기준 "
            f"~ {end.isoformat()} 직전)")


def _top_rooms(occ, n=5):
    """매물별 통합 선점률 상위 n개 (랭킹용)."""
    if not (occ and occ.get("ok")):
        return []
    rooms = sorted(occ.get("rooms", []), key=lambda r: r["combined"],
                   reverse=True)
    return rooms[:n]


# --------------------------------------------------------------------------- #
# 콘솔 요약 (컨설턴트 스타일, ~15줄)
# --------------------------------------------------------------------------- #
def console_summary(ctx) -> str:
    L = []
    r = ctx["region"]
    L.append(f"■ {r} 단기임대 시장분석  ({ctx['date']}, 반경 {ctx['radius']:.0f}m)")
    L.append(f"  {ctx['desc']}")
    if ctx.get("locate_evidence"):
        L.append("[위치 자동해석]")
        for e in ctx["locate_evidence"]:
            L.append(f"  · {e}")
    sup = ctx["supply"]
    w = sup["weekly"]
    L.append(f"[공급] 오피스텔 원룸 {sup['n_kept']}건 "
             f"(반경내 {sup['n_total']}건 중 유형제외 {sup['n_type_excluded']}·비원룸 {sup['n_notroom_excluded']}) "
             f"· 주간가 중위 {_won(w['median'])} (n={w['n']})")
    occ = ctx["occupancy"]
    if occ and occ.get("ok"):
        L.append(f"[선점률] {_pct(occ['combined_occ'])} — {_window_label(ctx)} "
                 f"(33m2단독 {_pct(occ['pure_occ'])}·타채널 "
                 f"+{occ['other_channel']*100:.1f}p, 표본 {occ['n']})")
        top = _top_rooms(occ)
        if top:
            L.append("[선점률 랭킹] 가장 잘 도는 지점 (상위 %d)" % len(top))
            for i, t in enumerate(top, 1):
                mark = "★" if i == 1 else " "
                L.append(f"  {mark}{i}. {t['name']} · {t.get('addr') or '주소 미상'} "
                         f"· {_won(t['weekly'])}/주 · 선점률 {_pct(t['combined'])}")
    else:
        reason = "세션 필요(로그인 세션 없음/만료)" if ctx.get("occ_login_needed") else (
            occ.get("reason") if occ else "미측정")
        L.append(f"[선점률] {reason} — 실측 불가 → 수익 계산 보류(공급·월세만 출력)")
    mo = ctx["molit"]
    L.append(f"[실거래] MOLIT 오피스텔 전월세 {mo['months'][0]}~{mo['months'][-1]} "
             f"· 전용 ≤33㎡ · {'/'.join(mo['dongs'])} · 월세건 {mo['n_filtered']}")
    for band, dep in (("500", DEPOSIT_500), ("1000", DEPOSIT_1000)):
        b = mo["bands"][band]
        if b["sufficient"]:
            L.append(f"  · {band}밴드(보증금 {dep}만): 월세중위 {_man(b['rent_median'])} "
                     f"(n={b['n']}, 보증금중위 {_man(b['deposit_median'])})")
        else:
            L.append(f"  · {band}밴드: {b['note']} — 추정 금지")
    if ctx.get("conservative"):
        L.append(f"[보수 순수익] 기대매출 = 주간가중위 × 4.345 × 실측 선점률 "
                 f"{_pct(ctx['occ_used'])} · 관리비 {_man(ctx['mgmt'])} [가정]")
        for row in ctx["conservative"]:
            tag = "기준" if row["primary"] else "참고"
            L.append(f"  · {row['band']}밴드({tag}): 매출 {row['revenue']:.1f} "
                     f"− 월세 {row['rent']:g} − 관리비 {row['mgmt']:g} "
                     f"= 순수익 {row['net']:.1f}만/월")
    else:
        L.append("[보수 순수익] 세션 필요 — 실측 선점률 없음 → 산출 보류")
    if ctx["scenarios"]:
        L.append(f"[상세 모델·보조] 정본 산식(위탁 60/50%·청소·수수료, "
                 f"공과금 {_man(UTILITIES)} 가정)")
        for sc in ctx["scenarios"]:
            L.append(f"  · {sc['band']}밴드 보증금 {sc['deposit']}만: "
                     f"월순익 {sc['profit60']:.1f}/{sc['profit50']:.1f}만(60/50%) "
                     f"→ 연 {sc['yield60']:.1f}/{sc['yield50']:.1f}%")
    an = ctx.get("analysis")
    if an:
        L.append(f"[분석] 신뢰등급 {an['grade_overall']} — {an['grade_reason']}")
        if an.get("channel"):
            L.append(f"  · 타채널: {an['channel']['text']}")
        for w in an.get("confounding_warnings", []):
            L.append(f"  · ⚠ 품질교락 의심({w['band']}밴드): "
                     f"{w['evidence'][0] if w['evidence'] else ''}")
        if an.get("recommendations"):
            L.append("[추천]")
            for rec in an["recommendations"]:
                L.append(f"  · {rec['verdict']} — {rec['band']}밴드(보증금 {rec['deposit']}만, "
                         f"등급 {rec['grade']}): {rec['basis']}")
                L.append(f"      남은 리스크: {rec['risk']}")
        if an.get("principle"):
            L.append(f"  {an['principle']}")
    L.append(f"[주의] 매출=33m2 실측(현시점 스냅숏)·비용=MOLIT 법정동 실거래로 "
             f"공간단위·시점 불일치. 표기월세는 신고 원값(환산 없음).")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def _md_band_table(mo):
    rows = ["| 밴드 | 보증금 | 월세중위(원값) | 표본수 | 보증금중위 | 비고 |",
            "|---|---|---|---|---|---|"]
    for band, dep in (("500", DEPOSIT_500), ("1000", DEPOSIT_1000)):
        b = mo["bands"][band]
        if b["sufficient"]:
            rows.append(f"| {band} | {dep}만 | {_man(b['rent_median'])} "
                        f"(min {_man(b['rent_min'])}/max {_man(b['rent_max'])}) "
                        f"| {b['n']} | {_man(b['deposit_median'])} | |")
        else:
            rows.append(f"| {band} | {dep}만 | — | {b['n']} | — | {b['note']} |")
    return "\n".join(rows)


def build_md(ctx) -> str:
    r = ctx["region"]
    sup, mo, occ = ctx["supply"], ctx["molit"], ctx["occupancy"]
    w = sup["weekly"]
    out = [f"# {r} 단기임대 시장분석", "",
           f"> 생성 {ctx['date']} · 반경 {ctx['radius']:.0f}m · {ctx['desc']}", ""]
    if ctx.get("locate_evidence"):
        out += ["## 0. 위치 자동 해석 (방법론)", ""]
        out += [f"- {e}" for e in ctx["locate_evidence"]]
        out += [""]
    out += ["## 1. 공급 스캔 (33m2, 오피스텔 원룸)", "",
           f"- 반경 내 {sup['n_total']}건 → 유형제외 {sup['n_type_excluded']} · "
           f"비원룸제외 {sup['n_notroom_excluded']} → **유지 {sup['n_kept']}건**",
           f"- 주간가(임대료+관리비): 중위 **{_won(w['median'])}** / "
           f"최저 {_won(w['min'])} / 최고 {_won(w['max'])} (n={w['n']})", "",
           f"## 2. 선점률 — {_window_label(ctx)}", ""]
    if occ and occ.get("ok"):
        out += [f"- 통합 선점률(booking+disable ÷ 기간) **{_pct(occ['combined_occ'])}** "
                f"· 33m2 단독 {_pct(occ['pure_occ'])} · 타채널비중 +{occ['other_channel']*100:.1f}p "
                f"(표본 {occ['n']})", ""]
        top = _top_rooms(occ)
        if top:
            out += ["### 선점률 최고 지점 랭킹 (가장 잘 도는 지점)", "",
                    "| # | 매물명(건물) | 주소 | 주간가 | 선점률 |",
                    "|---|---|---|---|---|"]
            for i, t in enumerate(top, 1):
                name = f"**{t['name']}** ★" if i == 1 else t["name"]
                out.append(f"| {i} | {name} | {t.get('addr') or '—'} "
                           f"| {_won(t['weekly'])} | {_pct(t['combined'])} |")
            out.append("")
    else:
        reason = ("세션 필요(로그인 세션 없음/만료)" if ctx.get("occ_login_needed")
                  else (occ.get("reason") if occ else "미측정"))
        out += [f"- **{reason}** — 실측 불가. 수익 계산은 보류하고 "
                "공급·월세만 출력.", ""]
    out += ["## 3. 실거래 월세 (MOLIT 오피스텔 전월세, 밴드 분리)", "",
            f"- 조회월: {', '.join(mo['months'])} · 법정동: {'/'.join(mo['dongs'])} "
            f"(LAWD {mo['lawd']})",
            f"- 원자료 {mo['n_raw']}건 → 전용 ≤33㎡·월세건 필터 **{mo['n_filtered']}건**",
            f"- 보증금 밴드: 500=300~700만 / 1000=700초과~1300만 (환산 없음, 신고 원값)", "",
            _md_band_table(mo), ""]
    out += ["## 4. 보수 순수익 (기본)", "",
            "> 산식: 월 기대매출 = 주간가 중위 × 4.345 × 실측 선점률 · "
            "보수 순수익 = 기대매출 − 월세중위 − 관리비 (다른 가감 없음) · "
            f"관리비 {_man(ctx['mgmt'])} [가정]", ""]
    if ctx.get("conservative"):
        out += ["| 밴드 | 기대매출 | − 월세중위 | − 관리비[가정] | = 보수 순수익/월 | 구분 |",
                "|---|---|---|---|---|---|"]
        for row in ctx["conservative"]:
            tag = "**기준**" if row["primary"] else "참고"
            net = f"**{row['net']:.1f}만**" if row["primary"] else f"{row['net']:.1f}만"
            out.append(f"| {row['band']} | {row['revenue']:.1f}만 | {row['rent']:g}만 "
                       f"| {row['mgmt']:g}만 | {net} | {tag} |")
        out.append("")
    else:
        out += ["_**세션 필요** — 실측 선점률이 없어 수익 계산 보류. "
                "33m2 로그인 세션(session.txt)을 주면 산출됩니다._", ""]
    out += ["### 4b. 상세 모델 (보조 — 정본 산식)", "",
            f"> 가정: 관리비 {_man(ctx['mgmt'])}·공과금 {_man(UTILITIES)}·"
            f"청소수입 3만/주·청소실비 3.2만·수수료 3.3% · 선점률 {_pct(ctx['occ_used'])}"
            + (" (실측)" if ctx.get("occ_measured") else ""), ""]
    if ctx["scenarios"]:
        out += ["| 밴드 | 보증금 | 월순익 60% | 월순익 50% | 연수익률 60% | 연수익률 50% |",
                "|---|---|---|---|---|---|"]
        for sc in ctx["scenarios"]:
            out.append(f"| {sc['band']} | {sc['deposit']}만 | {sc['profit60']:.1f}만 "
                       f"| {sc['profit50']:.1f}만 | {sc['yield60']:.1f}% | {sc['yield50']:.1f}% |")
        out.append("")
    else:
        out += ["_세션 필요 — 실측 선점률 없음 → 산출 보류._", ""]
    an = ctx.get("analysis")
    if an:
        out += ["## 5. 분석·추천 (판단룰 엔진)", "",
                f"**신뢰등급 {an['grade_overall']}** — {an['grade_reason']}", ""]
        bg = an.get("band_grades", {})
        if bg:
            out += ["| 밴드 | 등급 | 근거 |", "|---|---|---|"]
            for band in ("500", "1000"):
                if band in bg:
                    out.append(f"| {band} | {bg[band]['grade']} | {bg[band]['reason']} |")
            out.append("")
        if an.get("channel"):
            out += [f"- **타채널 해석**: {an['channel']['text']}", ""]
        for w in an.get("confounding_warnings", []):
            out.append(f"> ⚠ **품질교락 의심({w['band']}밴드)**")
            for e in w["evidence"]:
                out.append(f"> - {e}")
            out.append("")
        if an.get("recommendations"):
            out += ["### 조건별 추천", ""]
            for rec in an["recommendations"]:
                out += [f"**{rec['verdict']} — {rec['band']}밴드 (보증금 {rec['deposit']}만, "
                        f"연 {rec['yield60']:.1f}%/{rec['yield50']:.1f}%, 등급 {rec['grade']})**",
                        f"- 근거: {rec['basis']}",
                        f"- 남은 리스크: {rec['risk']}", ""]
        if an.get("principle"):
            out += [f"_{an['principle']}_", ""]
    out += ["## 6. 캐비앗", ""]
    for c in ctx["caveats"]:
        out.append(f"- {c}")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def _h(s):
    return html.escape(str(s))


def _html_band_rows(mo):
    tr = []
    for band, dep in (("500", DEPOSIT_500), ("1000", DEPOSIT_1000)):
        b = mo["bands"][band]
        if b["sufficient"]:
            note = ""
            tr.append(
                f"<tr><td>{band}</td><td class='num'>{dep}만</td>"
                f"<td class='num'>{_man(b['rent_median'])}</td>"
                f"<td class='num'>{_man(b['rent_min'])}~{_man(b['rent_max'])}</td>"
                f"<td class='num'>{b['n']}</td>"
                f"<td class='num'>{_man(b['deposit_median'])}</td>"
                f"<td>{note}</td></tr>")
        else:
            tr.append(
                f"<tr><td>{band}</td><td class='num'>{dep}만</td>"
                f"<td colspan='4'><span class='badge badge-warn'>{_h(b['note'])}</span> "
                f"— 추정 금지</td><td></td></tr>")
    return "\n".join(tr)


def _html_conservative_rows(rows):
    if not rows:
        return ("<tr><td colspan='6'><span class='badge badge-warn'>세션 필요</span> "
                "— 실측 선점률이 없어 수익 계산 보류(공급·월세만 출력)</td></tr>")
    tr = []
    for row in rows:
        if row["primary"]:
            tag = "<span class='badge badge-ok'>기준</span>"
            net = f"<strong>{row['net']:.1f}만</strong>"
            style = " style='background:var(--g-50)'"
        else:
            tag = "<span class='badge badge-muted'>참고</span>"
            net = f"{row['net']:.1f}만"
            style = ""
        tr.append(
            f"<tr{style}><td>{row['band']}밴드</td>"
            f"<td class='num'>{row['revenue']:.1f}만</td>"
            f"<td class='num'>− {row['rent']:g}만</td>"
            f"<td class='num'>− {row['mgmt']:g}만</td>"
            f"<td class='num'>{net}</td><td>{tag}</td></tr>")
    return "\n".join(tr)


def _html_ranking_rows(top):
    tr = []
    for i, t in enumerate(top, 1):
        if i == 1:
            star = " <span class='badge badge-ok'>★ 1위</span>"
            style = " style='background:var(--g-50);font-weight:700'"
        else:
            star, style = "", ""
        tr.append(
            f"<tr{style}><td class='num'>{i}</td>"
            f"<td>{_h(t['name'])}{star}</td>"
            f"<td>{_h(t.get('addr') or '—')}</td>"
            f"<td class='num'>{_h(_won(t['weekly']))}</td>"
            f"<td class='num'>{_pct(t['combined'])}</td></tr>")
    return "\n".join(tr)


def _html_scenario_rows(scs):
    if not scs:
        return ("<tr><td colspan='6'><span class='badge badge-warn'>세션 필요</span> "
                "— 실측 선점률 없음 → 산출 보류</td></tr>")
    tr = []
    for sc in scs:
        tr.append(
            f"<tr><td>{sc['band']}</td><td class='num'>{sc['deposit']}만</td>"
            f"<td class='num'>{sc['profit60']:.1f}만</td>"
            f"<td class='num'>{sc['profit50']:.1f}만</td>"
            f"<td class='num'>{sc['yield60']:.1f}%</td>"
            f"<td class='num'>{sc['yield50']:.1f}%</td></tr>")
    return "\n".join(tr)


_GRADE_BADGE = {"A": "badge-ok", "B": "badge-muted", "C": "badge-warn"}
_VERDICT_BADGE = {"1순위": "badge-ok", "대안": "badge-muted",
                  "조건부": "badge-warn", "부적합": "badge-warn"}


def _html_analysis(an) -> str:
    if not an:
        return ""
    gb = _GRADE_BADGE.get(an["grade_overall"], "badge-muted")
    parts = [
        f"<div class='card'><span class='badge {gb}'>신뢰등급 {_h(an['grade_overall'])}</span> "
        f"<span style='color:var(--n-500);margin-left:8px'>{_h(an['grade_reason'])}</span>"]
    if an.get("channel"):
        parts.append(f"<p style='margin-top:10px'>{_h(an['channel']['text'])}</p>")
    parts.append("</div>")

    for w in an.get("confounding_warnings", []):
        items = "".join(f"<li>{_h(e)}</li>" for e in w["evidence"])
        parts.append(
            f"<div class='card risk' style='margin-top:14px'>"
            f"<span class='badge badge-warn'>⚠ 품질교락 의심 · {_h(w['band'])}밴드</span>"
            f"<ul style='margin:10px 0 0 18px'>{items}</ul></div>")

    recs = an.get("recommendations") or []
    if recs:
        cards = []
        for rec in recs:
            vb = _VERDICT_BADGE.get(rec["verdict"], "badge-muted")
            cards.append(
                f"<div class='card'>"
                f"<span class='badge {vb}'>{_h(rec['verdict'])}</span> "
                f"<span class='badge {_GRADE_BADGE.get(rec['grade'],'badge-muted')}' "
                f"style='margin-left:6px'>등급 {_h(rec['grade'])}</span>"
                f"<div class='kpi-value' style='font-size:22px;margin-top:8px'>"
                f"{rec['band']}밴드 · 보증금 {rec['deposit']}만</div>"
                f"<div class='kpi-note'>연 {rec['yield60']:.1f}% / {rec['yield50']:.1f}% · "
                f"월순익 {rec['profit60']:.1f} / {rec['profit50']:.1f}만</div>"
                f"<p style='margin-top:10px;font-size:14px'>{_h(rec['basis'])}</p>"
                f"<p style='margin-top:6px;color:var(--n-500);font-size:13px'>"
                f"남은 리스크: {_h(rec['risk'])}</p></div>")
        cols = "cols-2" if len(cards) >= 2 else ""
        parts.append(f"<div class='card-grid {cols}' style='margin-top:14px'>"
                     + "".join(cards) + "</div>")
    if an.get("principle"):
        parts.append(f"<p class='footnote'>{_h(an['principle'])}</p>")
    return "\n".join(parts)


def build_html(ctx) -> str:
    try:
        with open(TOKENS_CSS, encoding="utf-8") as f:
            tokens = f.read()
    except OSError:
        tokens = ":root{--g-800:#0E4633;--paper:#FAF8F5;}"
    r = ctx["region"]
    sup, mo, occ = ctx["supply"], ctx["molit"], ctx["occupancy"]
    w = sup["weekly"]

    wlabel = _window_label(ctx)
    if occ and occ.get("ok"):
        occ_html = (f"<div class='card-grid cols-3'>"
                    f"<div class='card kpi'><span class='kpi-label'>통합 선점률</span>"
                    f"<span class='kpi-value'>{_pct(occ['combined_occ'])}</span>"
                    f"<span class='kpi-note'>booking+disable ÷ 기간, 표본 {occ['n']}</span></div>"
                    f"<div class='card kpi'><span class='kpi-label'>33m2 단독</span>"
                    f"<span class='kpi-value'>{_pct(occ['pure_occ'])}</span>"
                    f"<span class='kpi-note'>booking only</span></div>"
                    f"<div class='card kpi'><span class='kpi-label'>타채널비중</span>"
                    f"<span class='kpi-value'>+{occ['other_channel']*100:.1f}p</span>"
                    f"<span class='kpi-note'>수기차단분</span></div></div>")
        top = _top_rooms(occ)
        if top:
            occ_html += (
                "<div class='sec-head' style='margin-top:32px'>"
                "<div><div class='sec-title' style='font-size:18px'>선점률 최고 지점 랭킹</div>"
                "<div class='sec-sub'>가장 잘 도는 지점 — 매물별 선점률 상위 "
                f"{len(top)}개</div></div></div>"
                "<div class='table-scroll'><table class='ledger'>"
                "<thead><tr><th>#</th><th>매물명(건물)</th><th>주소</th>"
                "<th>주간가</th><th>선점률</th></tr></thead>"
                f"<tbody>{_html_ranking_rows(top)}</tbody></table></div>")
    else:
        reason = "세션 필요 (로그인 세션 없음/만료)" if ctx.get("occ_login_needed") else (
            occ.get("reason") if occ else "미측정")
        occ_html = (f"<div class='card'><span class='badge badge-warn'>선점률 {_h(reason)}</span>"
                    f"<p style='margin-top:8px;color:var(--n-500)'>예약률 실측을 위해 "
                    f"33m2 로그인 세션이 필요합니다. 수익 계산은 보류하고 "
                    f"공급·월세만 출력합니다.</p>"
                    f"<p style='margin-top:6px;color:var(--n-500)'>해결: 메인 화면의 "
                    f"<b>33m2 로그인</b> 칸에 이메일/비밀번호를 입력하세요 (비밀번호 저장 안 됨). "
                    f"Edge/Chrome 자동 감지는 브라우저 보안 정책상 관리자 권한 실행에서만 동작할 수 "
                    f"있습니다.</p></div>")

    caveats = "\n".join(f"<li>{_h(c)}</li>" for c in ctx["caveats"])
    if ctx.get("locate_evidence"):
        items = "\n".join(f"<li>{_h(e)}</li>" for e in ctx["locate_evidence"])
        locate_html = (
            "<section class=\"sec\"><div class=\"wrap\">"
            "<div class=\"sec-head\"><span class=\"sec-num\">00</span>"
            "<div><div class=\"sec-title\">위치 자동 해석</div>"
            "<div class=\"sec-sub\">지오코딩 → 33m2 주소 → LAWD → 단지명 역매칭</div></div></div>"
            f"<div class=\"card\"><ul style=\"margin-left:18px\">{items}</ul></div>"
            "</div></section>")
    else:
        locate_html = ""
    analysis_html = _html_analysis(ctx.get("analysis"))
    occ_note = (f"실측 {_pct(ctx['occ_used'])}" if ctx.get("occ_measured")
                else "미측정(세션 필요)")

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_h(r)} 단기임대 시장분석 · {_h(ctx['date'])}</title>
<style>
{tokens}
.report-head {{ background: var(--g-800); color: var(--paper); padding: 40px 0; }}
.report-head .wrap {{ color: var(--paper); }}
.report-head h1 {{ font-size: 30px; letter-spacing:-0.02em; color:#fff; }}
.report-head .meta {{ color: var(--g-200); font-family: var(--font-data);
  font-size: 13px; margin-top: 8px; }}
.report-head .desc {{ color: var(--g-100); margin-top: 10px; max-width: 780px; }}
.hl {{ color: var(--g-500); font-weight: 700; }}
</style></head>
<body>
<header class="report-head"><div class="wrap">
  <h1>{_h(r)} 단기임대 시장분석</h1>
  <div class="meta">생성 {_h(ctx['date'])} · 반경 {ctx['radius']:.0f}m · LAWD {_h(mo['lawd'])} · {_h('/'.join(mo['dongs']))}</div>
  <div class="desc">{_h(ctx['desc'])}</div>
</div></header>
{locate_html}
<section class="sec"><div class="wrap">
  <div class="sec-head"><span class="sec-num">01</span>
    <div><div class="sec-title">선점률 (실측)</div>
    <div class="sec-sub">측정 창: {_h(wlabel)} · 통합 선점률 = booking+disable ÷ 기간 · 창 후반은 채워지는 중이라 하한 성격</div></div></div>
  {occ_html}
</div></section>

<section class="sec sec-alt"><div class="wrap">
  <div class="sec-head"><span class="sec-num">02</span>
    <div><div class="sec-title">보수 순수익 (기본)</div>
    <div class="sec-sub">기대매출(주간가중위 × 4.345 × 실측선점률) − 월세중위 − 관리비 · 선점률 {_h(occ_note)}</div></div></div>
  <div class="table-scroll"><table class="ledger">
    <thead><tr><th>밴드</th><th>월 기대매출</th><th>− 월세중위</th>
      <th>− 관리비 [가정]</th><th>= 보수 순수익/월</th><th>구분</th></tr></thead>
    <tbody>{_html_conservative_rows(ctx.get('conservative') or [])}</tbody>
  </table></div>
  <p class="footnote">관리비 {_man(ctx['mgmt'])} [가정] · 500밴드(보증금 300~700만) 기준, 1000밴드는 참고.
    다른 가감(공과금·청소·수수료) 없음 — 보수적 단순 산식.</p>
</div></section>

<section class="sec"><div class="wrap">
  <div class="sec-head"><span class="sec-num">03</span>
    <div><div class="sec-title">상세 모델 (보조)</div>
    <div class="sec-sub">정본 산식 · share 60%(주)/50%(병기) · 선점률 {_h(occ_note)}</div></div></div>
  <div class="table-scroll"><table class="ledger">
    <thead><tr><th>밴드</th><th>보증금</th><th>월순익 60%</th><th>월순익 50%</th>
      <th>연수익률 60%</th><th>연수익률 50%</th></tr></thead>
    <tbody>{_html_scenario_rows(ctx['scenarios'])}</tbody>
  </table></div>
  <p class="footnote">가정: 관리비 {_man(ctx['mgmt'])}·공과금 {_man(UTILITIES)}·청소수입 3만/주·청소실비 3.2만·수수료 3.3%.
    연수익률 = 월순익×12÷보증금. 앵커 자기검증(영통 24.97만) 통과 후 산출.</p>
</div></section>

<section class="sec sec-alt"><div class="wrap">
  <div class="sec-head"><span class="sec-num">04</span>
    <div><div class="sec-title">공급 스캔</div>
    <div class="sec-sub">삼삼엠투(33m2) 오피스텔 원룸 · 비로그인 지도 API</div></div></div>
  <div class="card-grid cols-4">
    <div class="card kpi"><span class="kpi-label">유지 매물</span>
      <span class="kpi-value">{sup['n_kept']}</span>
      <span class="kpi-note">반경내 {sup['n_total']}건 중</span></div>
    <div class="card kpi"><span class="kpi-label">주간가 중위</span>
      <span class="kpi-value">{_h(f"{w['median']:,}" if w['median'] else '—')}</span>
      <span class="kpi-note">임대료+관리비 (n={w['n']})</span></div>
    <div class="card kpi"><span class="kpi-label">유형 제외</span>
      <span class="kpi-value">{sup['n_type_excluded']}</span>
      <span class="kpi-note">고시원·모텔·호텔·쉐어 등</span></div>
    <div class="card kpi"><span class="kpi-label">비원룸 제외</span>
      <span class="kpi-value">{sup['n_notroom_excluded']}</span>
      <span class="kpi-note">투룸·N베드·다인</span></div>
  </div>
  <p class="footnote">주간가 범위: {_won(w['min'])} ~ {_won(w['max'])} · 오피스텔 유형만 유지, 원룸만(이름 키워드 필터).</p>
</div></section>

<section class="sec"><div class="wrap">
  <div class="sec-head"><span class="sec-num">05</span>
    <div><div class="sec-title">실거래 월세 (밴드 분리)</div>
    <div class="sec-sub">MOLIT 오피스텔 전월세 · 전용 ≤33㎡ · 신고 원값(환산 없음)</div></div></div>
  <div class="table-scroll"><table class="ledger">
    <thead><tr><th>밴드</th><th>보증금</th><th>월세중위</th><th>월세 min~max</th>
      <th>표본수</th><th>보증금중위</th><th>비고</th></tr></thead>
    <tbody>{_html_band_rows(mo)}</tbody>
  </table></div>
  <p class="footnote">조회월 {_h(', '.join(mo['months']))} · 원자료 {mo['n_raw']} → 필터 {mo['n_filtered']}건.
    500밴드=보증금 300~700만 / 1000밴드=700초과~1300만(경계 700은 500 귀속). 표본&lt;3은 추정 금지.</p>
</div></section>

<section class="sec sec-alt"><div class="wrap">
  <div class="sec-head"><span class="sec-num">06</span>
    <div><div class="sec-title">분석·추천</div>
    <div class="sec-sub">판단룰 엔진 · 신뢰등급·품질교락·타채널·조건별 추천</div></div></div>
  {analysis_html}
</div></section>

<section class="sec"><div class="wrap">
  <div class="sec-head"><span class="sec-num">07</span>
    <div><div class="sec-title">캐비앗</div>
    <div class="sec-sub">해석 한계 · 반드시 함께 읽을 것</div></div></div>
  <div class="card risk"><ul style="margin-left:18px">{caveats}</ul></div>
</div></section>

<footer class="sec"><div class="wrap" style="color:var(--n-500);font-size:13px">
  다니엘스테이 market-analyzer · 자동 생성 리포트 · {_h(ctx['date'])}
</div></footer>
</body></html>"""


def write_reports(ctx):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stem = f"{ctx['region']}_{ctx['date']}"
    md_path = os.path.join(OUTPUT_DIR, stem + ".md")
    html_path = os.path.join(OUTPUT_DIR, stem + ".html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(build_md(ctx))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build_html(ctx))
    return md_path, html_path


# --------------------------------------------------------------------------- #
# 스캔 모드 비교 랭킹 리포트
# --------------------------------------------------------------------------- #
def _cluster_row(cl) -> dict:
    """클러스터 분석결과 → 랭킹 표시용 요약."""
    an = cl.get("analysis") or {}
    recs = an.get("recommendations") or []
    top = recs[0] if recs else None
    b = cl.get("bands") or {}
    def bandcell(k):
        x = (b.get(k) or {}) if b else {}
        return (f"{_man(x.get('rent_median'))}(n={x.get('n',0)})"
                if x.get("sufficient") else f"—(n={(x or {}).get('n',0)})")
    return {
        "loc": f"{cl.get('province') or '?'} {cl.get('dong') or '?'}",
        "n": cl["n"], "weekly": cl.get("weekly_median"),
        "band500": bandcell("500"), "band1000": bandcell("1000"),
        "grade": an.get("grade_overall", "—"),
        "best_yield": top["yield60"] if top else None,
        "verdict": (f"{top['verdict']}({top['band']})" if top else "—"),
        "occ": cl.get("occ_used"), "occ_measured": cl.get("occ_measured"),
        "confounded": bool(an.get("confounding_warnings")),
    }


def _rank_key(cl):
    an = cl.get("analysis") or {}
    recs = an.get("recommendations") or []
    y = recs[0]["yield60"] if recs else None
    return (0, -y) if y is not None else (1, -cl["n"])


def build_scan_md(scan) -> str:
    clusters = sorted(scan["clusters"], key=_rank_key)
    out = [f"# {scan['region']} 단기임대 스캔 랭킹", "",
           f"> 생성 {scan['date']} · 바운딩박스 타일 {scan['n_tiles']}개 · "
           f"고유 매물 {scan['n_raw']} → 오피스텔 원룸 {scan['n_kept']} → "
           f"500m 클러스터 {scan['n_clusters']}개(매물 3+) · 상위 {scan['top']} 분석", "",
           ("예약률: 세션 표본 축소(클러스터당 5개) 측정." if scan["has_session"]
            else "예약률: 세션 없음 → 공급·비용 랭킹 + (지정 시)가정 예약률 수익률."), "",
           "## 클러스터 비교 랭킹", "",
           "| # | 위치(시군구·법정동) | 공급 | 주간가중위 | 500월세(n) | 1000월세(n) "
           "| 연수익률 | 등급 | 추천 |",
           "|---|---|---|---|---|---|---|---|---|"]
    for i, cl in enumerate(clusters, 1):
        r = _cluster_row(cl)
        y = f"{r['best_yield']:.1f}%" if r["best_yield"] is not None else "—"
        flag = " ⚠교락" if r["confounded"] else ""
        out.append(f"| {i} | {r['loc']} | {r['n']} | {_won(r['weekly'])} "
                   f"| {r['band500']} | {r['band1000']} | {y} | {r['grade']}{flag} "
                   f"| {r['verdict']} |")
    out += ["", "## 클러스터별 상세", ""]
    for i, cl in enumerate(clusters, 1):
        r = _cluster_row(cl)
        out += [f"### {i}. {r['loc']} (매물 {cl['n']}, LAWD {cl.get('lawd') or '—'})", ""]
        for e in cl.get("locate_ev", []):
            out.append(f"- {e}")
        an = cl.get("analysis")
        if an:
            out.append(f"- 신뢰등급 **{an['grade_overall']}** — {an['grade_reason']}")
            for w in an.get("confounding_warnings", []):
                out.append(f"- ⚠ 품질교락({w['band']}밴드): "
                           f"{w['evidence'][0] if w['evidence'] else ''}")
            for rec in an.get("recommendations", []):
                out.append(f"- **{rec['verdict']}** {rec['band']}밴드(보증금 {rec['deposit']}만, "
                           f"연 {rec['yield60']:.1f}%): {rec['basis']}")
        elif not cl.get("occ_used"):
            out.append("- 예약률 미측정·미지정 → 수익률 보류(공급·비용만).")
        out.append("")
    out += ["## 캐비앗", "",
            "- 클러스터 중심=그리디 시드(반경 500m). 법정동은 클러스터별 자동 결정(33m2 주소·단지 역매칭).",
            "- 매출=33m2 현시점 스냅숏, 비용=MOLIT 법정동 실거래로 공간단위·시점 불일치.",
            "- 예약률 세션 없으면 가동률 미측정(수익률은 --occ 가정 시에만). 표기월세는 신고 원값.",
            "- 스캔 미커버 범위·표본<3 밴드는 결론에서 제외(추정 금지)."]
    return "\n".join(out) + "\n"


def build_scan_html(scan) -> str:
    try:
        with open(TOKENS_CSS, encoding="utf-8") as f:
            tokens = f.read()
    except OSError:
        tokens = ":root{--g-800:#0E4633;--paper:#FAF8F5;}"
    clusters = sorted(scan["clusters"], key=_rank_key)
    rows = []
    for i, cl in enumerate(clusters, 1):
        r = _cluster_row(cl)
        y = f"{r['best_yield']:.1f}%" if r["best_yield"] is not None else "—"
        gb = _GRADE_BADGE.get(r["grade"], "badge-muted")
        flag = " <span class='badge badge-warn'>교락</span>" if r["confounded"] else ""
        rows.append(
            f"<tr><td class='num'>{i}</td><td>{_h(r['loc'])}</td>"
            f"<td class='num'>{r['n']}</td><td class='num'>{_h(_won(r['weekly']))}</td>"
            f"<td class='num'>{_h(r['band500'])}</td><td class='num'>{_h(r['band1000'])}</td>"
            f"<td class='num'>{y}</td>"
            f"<td><span class='badge {gb}'>{_h(r['grade'])}</span>{flag}</td>"
            f"<td>{_h(r['verdict'])}</td></tr>")
    detail = []
    for i, cl in enumerate(clusters, 1):
        r = _cluster_row(cl)
        an = cl.get("analysis")
        inner = "".join(f"<li>{_h(e)}</li>" for e in cl.get("locate_ev", []))
        recs_html = ""
        if an:
            recs_html += (f"<p><span class='badge {_GRADE_BADGE.get(an['grade_overall'],'badge-muted')}'>"
                          f"등급 {_h(an['grade_overall'])}</span> "
                          f"<span style='color:var(--n-500)'>{_h(an['grade_reason'])}</span></p>")
            for w in an.get("confounding_warnings", []):
                recs_html += (f"<p><span class='badge badge-warn'>⚠ 교락 {_h(w['band'])}밴드</span> "
                              f"{_h(w['evidence'][0] if w['evidence'] else '')}</p>")
            for rec in an.get("recommendations", []):
                vb = _VERDICT_BADGE.get(rec["verdict"], "badge-muted")
                recs_html += (f"<p><span class='badge {vb}'>{_h(rec['verdict'])}</span> "
                              f"{rec['band']}밴드 보증금 {rec['deposit']}만 · 연 {rec['yield60']:.1f}% — "
                              f"{_h(rec['basis'])}</p>")
        detail.append(
            f"<div class='card' style='margin-bottom:14px'>"
            f"<div class='kpi-value' style='font-size:20px'>{i}. {_h(r['loc'])}</div>"
            f"<div class='kpi-note'>매물 {cl['n']} · 주간가중위 {_h(_won(r['weekly']))} · "
            f"LAWD {_h(cl.get('lawd') or '—')}</div>"
            f"<ul style='margin:10px 0 0 18px;font-size:13px;color:var(--n-500)'>{inner}</ul>"
            f"{recs_html}</div>")
    sess = ("세션 표본 축소(클러스터당 5개) 측정" if scan["has_session"]
            else "세션 없음 → 공급·비용 랭킹(가정 예약률 시 수익률)")
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_h(scan['region'])} 단기임대 스캔 랭킹 · {_h(scan['date'])}</title>
<style>
{tokens}
.report-head {{ background: var(--g-800); color: var(--paper); padding: 40px 0; }}
.report-head .wrap {{ color: var(--paper); }}
.report-head h1 {{ font-size: 30px; letter-spacing:-0.02em; color:#fff; }}
.report-head .meta {{ color: var(--g-200); font-family: var(--font-data);
  font-size: 13px; margin-top: 8px; }}
</style></head>
<body>
<header class="report-head"><div class="wrap">
  <h1>{_h(scan['region'])} 단기임대 스캔 랭킹</h1>
  <div class="meta">생성 {_h(scan['date'])} · 타일 {scan['n_tiles']} · 고유 매물 {scan['n_raw']}
    → 오피스텔 원룸 {scan['n_kept']} → 500m 클러스터 {scan['n_clusters']}개 · 상위 {scan['top']} 분석</div>
  <div class="desc" style="color:var(--g-100);margin-top:10px">예약률: {_h(sess)}</div>
</div></header>

<section class="sec"><div class="wrap">
  <div class="sec-head"><span class="sec-num">01</span>
    <div><div class="sec-title">클러스터 비교 랭킹</div>
    <div class="sec-sub">그리디 500m 클러스터 · 연수익률(가능 시)순, 아니면 공급순</div></div></div>
  <div class="table-scroll"><table class="ledger">
    <thead><tr><th>#</th><th>위치(시군구·법정동)</th><th>공급</th><th>주간가중위</th>
      <th>500월세(n)</th><th>1000월세(n)</th><th>연수익률</th><th>등급</th><th>추천</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div>
  <p class="footnote">법정동은 클러스터별 자동 결정(33m2 주소 최빈 + 단지명 역매칭). ⚠교락=품질교락 의심.</p>
</div></section>

<section class="sec sec-alt"><div class="wrap">
  <div class="sec-head"><span class="sec-num">02</span>
    <div><div class="sec-title">클러스터별 상세</div>
    <div class="sec-sub">위치 자동해석 근거 · 신뢰등급 · 추천</div></div></div>
  {''.join(detail)}
</div></section>

<footer class="sec"><div class="wrap" style="color:var(--n-500);font-size:13px">
  다니엘스테이 market-analyzer 스캔 모드 · 자동 생성 · {_h(scan['date'])} ·
  매출=33m2 스냅숏/비용=MOLIT 실거래(공간·시점 불일치) · 표본&lt;3 추정 금지.
</div></footer>
</body></html>"""


def write_scan_reports(scan):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stem = f"scan_{scan['region']}_{scan['date']}"
    md_path = os.path.join(OUTPUT_DIR, stem + ".md")
    html_path = os.path.join(OUTPUT_DIR, stem + ".html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(build_scan_md(scan))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build_scan_html(scan))
    return md_path, html_path
