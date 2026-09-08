# -*- coding: utf-8 -*-
"""build_report.py — 클러스터 전수 실측 → 딥그린 보고서 HTML + 표지 HTML 생성.

수익 계산 금지(사용자 확정): 월세 추정·순수익·손익분기·수익률·MOLIT 없음.
KPI의 '월 기대매출'만 주간가 중위 × 4.345주 × 통합가동률 (비용 미반영)로 넣는다.

사용:
  python routine/build_report.py --supply routine/out/용인시_supply.json \
      --occ routine/out/용인시_occ.json --cluster 0 --city 용인시 \
      --place 상현역 --date 2026-08-26 --out routine/out/리포트.html
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "market-analyzer"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import m33        # noqa: E402
import mapimg     # noqa: E402

import eval_section     # noqa: E402
import segment_section  # noqa: E402

WINDOW_DAYS = 56
TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out",
                   "다니엘스테이_화성시_동탄레이크원_2026-08-22.html")


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def radius_counts(raw_path, lat, lon, radius=500):
    """반경 내 원자료 기준 전체/유형제외/멀티룸제외/유지 건수."""
    raw = json.load(open(raw_path, encoding="utf-8"))["items"]
    n_total = n_type = n_multi = n_keep = 0
    for it in raw.values():
        la, lo = it.get("lat"), it.get("lng")
        if la is None or lo is None:
            continue
        if m33._haversine_m(lat, lon, float(la), float(lo)) > radius:
            continue
        n_total += 1
        ptype = (it.get("propertyType") or "").strip()
        name = it.get("roomName") or ""
        if any(x in ptype for x in m33._EXCLUDE_TYPES) or any(
                x in name for x in m33._EXCLUDE_TYPES) or ptype != m33.KEEP_TYPE:
            n_type += 1
        elif m33._MULTIROOM_RE.search(name) or (it.get("roomCnt") or 1) > 1:
            n_multi += 1
        else:
            n_keep += 1
    return n_total, n_type, n_multi, n_keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--supply", required=True)
    ap.add_argument("--occ", required=True)
    ap.add_argument("--cluster", type=int, default=0)
    ap.add_argument("--city", required=True)
    ap.add_argument("--place", required=True)
    ap.add_argument("--addr", default="")
    ap.add_argument("--date", required=True)
    ap.add_argument("--window", required=True, help="예: 2026-08-26 ~ 10-20")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cover-out", required=True)
    ap.add_argument("--map-sub", default="")
    ap.add_argument("--map-axis", default="")
    ap.add_argument("--map-note", default="")
    ap.add_argument("--seg", default="",
                    help="세그먼트 실측 rows JSON — 넣으면 06 원룸 vs 멀티룸 섹션 추가")
    ap.add_argument("--seg-names", default="",
                    help="클러스터 표시명, 인덱스 순서로 | 구분")
    ap.add_argument("--caveat", default="",
                    help="평가 섹션 유의점에 덧붙일 문장")
    a = ap.parse_args()

    sup = json.load(open(a.supply, encoding="utf-8"))
    occ = json.load(open(a.occ, encoding="utf-8"))
    cl = sup["clusters"][a.cluster]
    lat, lon = cl["center"]

    rows = []
    for r in cl["rooms"]:
        rec = occ.get(str(r["rid"])) or occ.get(r["rid"])
        if not rec or str(rec).startswith("ERR"):
            continue
        b, d, n = (int(x) for x in str(rec).split(":"))
        comb = (b + d) / WINDOW_DAYS * 100
        rows.append({**r, "b": b, "d": d, "n": n,
                     "comb": comb, "solo": b / WINDOW_DAYS * 100,
                     "alt": d / WINDOW_DAYS * 100})
    n_err = cl["n"] - len(rows)
    rows.sort(key=lambda x: (-x["comb"], -x["solo"]))

    combs = [r["comb"] for r in rows]
    mean_c = statistics.mean(combs)
    med_c = statistics.median(combs)
    solo_m = statistics.mean(r["solo"] for r in rows)
    alt_m = statistics.mean(r["alt"] for r in rows)
    wk = sorted(r["weekly"] / 10000 for r in rows if r.get("weekly"))
    wk_med, wk_min, wk_max = statistics.median(wk), min(wk), max(wk)
    revenue = wk_med * 4.345 * mean_c / 100

    raw_path = a.supply.replace(".json", "_raw.json")
    n_total, n_type, n_multi, n_keep = radius_counts(raw_path, lat, lon)

    # ---- 지도 ----
    png = os.path.join(os.path.dirname(a.out), "_map_tmp.png")
    mapimg.render_map(lat, lon, 500,
                      [{"lat": r["lat"], "lon": r["lon"], "rid": r["rid"],
                        "name": r["name"], "weekly": r.get("weekly")}
                       for r in rows], png,
                      top_rooms=[{"rid": r["rid"], "name": r["name"],
                                  "combined": r["comb"]} for r in rows[:3]],
                      date=a.date, lang="ko")
    if os.path.exists(png):
        uri = ("data:image/png;base64,"
               + base64.b64encode(open(png, "rb").read()).decode())
        os.remove(png)
    else:
        uri = ""
        print("[경고] 지도 생성 실패 — 지도 없이 계속", file=sys.stderr)

    # ---- 차트 행 ----
    chart = []
    for i, r in enumerate(rows):
        badge = ""
        if r["comb"] >= 99.9 and r["d"] == 0:
            badge = ('  <span class="badge badge-ok" style="font-size:10px;'
                     'padding:1px 7px;">순수 실예약 만실</span>')
        elif r["b"] == 0 and r["d"] > 0:
            badge = ('  <span class="badge badge-muted" style="font-size:10px;'
                     'padding:1px 7px;">전량 타채널</span>')
        elif r["comb"] == 0:
            badge = ('  <span class="badge badge-danger" style="font-size:10px;'
                     'padding:1px 7px;">완전 공실</span>')
        py = r.get("pyeong")
        py_s = f"{py:g}평 · " if py else ""
        wkv = f"주 {r['weekly']/10000:.1f}만 · " if r.get("weekly") else ""
        chart.append(
            f'      <!-- {i+1} -->\n'
            f'      <div class="row{" top" if i == 0 else ""}">\n'
            f'        <div class="r-name"><div class="nm">{esc(r["name"])}{badge}</div>'
            f'<div class="sub">rid {r["rid"]} · {py_s}{wkv}단독 {r["solo"]:.1f}%</div></div>\n'
            f'        <div class="track"><div class="bar" style="width:{r["comb"]:.1f}%"></div>'
            f'<div class="avgline"></div></div>\n'
            f'        <div class="r-val">{r["comb"]:.1f}%</div>\n'
            f'      </div>')
    chart_html = "\n".join(chart)

    top = rows[0]
    n_over50 = sum(1 for r in rows if r["comb"] >= 50)
    n_zero = sum(1 for r in rows if r["comb"] == 0)
    title = f"{a.place} 단기임대 시장검증"

    # ---- 템플릿 치환 ----
    html = open(TPL, encoding="utf-8").read()
    html = re.sub(r'data:image/png;base64,[A-Za-z0-9+/=]+', uri, html)
    html = html.replace("동탄레이크원 단기임대 시장검증 — 다니엘스테이",
                        f"{title} — 다니엘스테이")
    html = html.replace(
        '<h1 class="doc-title">동탄레이크원 단기임대 시장검증</h1>',
        f'<h1 class="doc-title">{esc(title)}</h1>')

    # 헤더 메타
    html = re.sub(
        r'<div class="doc-meta">.*?</div>\n</header>',
        f'''<div class="doc-meta">
    <span>{esc(a.addr)}</span>
    <span>반경 500m · {lat:.4f} / {lon:.4f}</span>
    <span>실측일 {a.date}</span>
    <span class="ok">✔ 전수 조사 {len(rows)}실 (표본 아님)</span>
    <span class="warn">⚠ 통합 가동률 = 예약 + 타채널 차단 ÷ 56일</span>
  </div>
</header>''', html, flags=re.S)

    # 결론 배너
    html = re.sub(
        r'<p class="verdict-text">.*?</p>',
        f'''<p class="verdict-text">
      반경 500m <b>전수 {len(rows)}실 실측</b> · 통합 가동률 <b>{mean_c:.1f}%</b> ·
      <span class="hl">중앙값 {med_c:.1f}%</span> · 주간가 중위 <b>{wk_med:.1f}만</b>
    </p>''', html, flags=re.S)

    # KPI
    html = re.sub(
        r'<div class="card-grid cols-4">.*?\n  </div>\n</section>',
        f'''<div class="card-grid cols-4">
    <div class="card kpi">
      <div class="kpi-label">반경 500m 전수 공급</div>
      <div class="kpi-value">{len(rows)}<span class="kpi-unit">실</span></div>
      <div class="kpi-note">반경 내 {n_total}건 → 유형 제외 {n_type}건 · 멀티룸 제외 {n_multi}건{f" · 조회 실패 {n_err}실" if n_err else ""}</div>
    </div>
    <div class="card kpi">
      <div class="kpi-label">통합 가동률 (정본)</div>
      <div class="kpi-value">{mean_c:.1f}<span class="kpi-unit">%</span></div>
      <div class="kpi-note">중앙값 {med_c:.1f}% · 분해 참고: 33m2 단독 {solo_m:.1f}% / 타채널 {alt_m:.1f}%</div>
    </div>
    <div class="card kpi">
      <div class="kpi-label">주간가 중위 (임대료+관리비)</div>
      <div class="kpi-value">{wk_med:.1f}<span class="kpi-unit">만</span></div>
      <div class="kpi-note">최저 {wk_min:.1f}만 · 최고 {wk_max:.1f}만</div>
    </div>
    <div class="card kpi">
      <div class="kpi-label">월 기대매출 (실측 기반·비용 미반영)</div>
      <div class="kpi-value">{revenue:.1f}<span class="kpi-unit">만</span></div>
      <div class="kpi-note">주간가 중위 {wk_med:.1f}만 × 4.345주 × 가동률 {mean_c:.1f}%</div>
    </div>
  </div>
</section>''', html, flags=re.S)

    # 지도 섹션
    html = re.sub(r'<p class="sec-sub">반경 내 33m2.*?</p>',
                  f'<p class="sec-sub">{a.map_sub}</p>', html, flags=re.S)
    html = html.replace('alt="동탄레이크원 반경 500m 지도"',
                        f'alt="{esc(a.place)} 반경 500m 지도"')
    html = re.sub(
        r'<div class="mapcap">.*?</div>',
        f'''<div class="mapcap">
        <span>중심 <b>{lat:.4f} / {lon:.4f}</b> · 실선원 500m</span>
        <span>밀집 축 <b>{esc(a.map_axis)}</b></span>
        <span>{esc(a.map_note)}</span>
      </div>''', html, flags=re.S)

    # 차트 섹션
    html = html.replace(
        '<h2 class="sec-title">전 매물 가동률 · 전수 20실</h2>',
        f'<h2 class="sec-title">전 매물 가동률 · 전수 {len(rows)}실</h2>')
    html = html.replace('<span><i class="sw-avg"></i>전수 평균 57.2%</span>',
                        f'<span><i class="sw-avg"></i>전수 평균 {mean_c:.1f}%</span>')
    html = re.sub(r'측정창 2026-08-22 ~ 10-16 \(56일\) · 전수 20실 · 오류 0건',
                  f'측정창 {a.window} (56일) · 전수 {len(rows)}실 · 오류 {n_err}건', html)
    html = re.sub(r'left: 57\.2%;', f'left: {mean_c:.1f}%;', html)
    html = re.sub(r'<div class="chart">.*?(?=<p class="chart-note">)',
                  f'<div class="chart">\n{chart_html}\n    </div>\n\n    ',
                  html, flags=re.S)

    dist = ("평균이 중앙값보다 높아 상위 매물이 끌어올린 분포"
            if mean_c > med_c
            else "중앙값이 평균보다 높아 하위 소수가 평균을 끌어내린 분포")
    html = re.sub(
        r'<p class="chart-note">.*?</p>',
        f'''<p class="chart-note">
      <span class="dot"></span><b>1위 rid {top["rid"]} 「{esc(top["name"])}」</b>
      (주 {top["weekly"]/10000:.1f}만) — 통합 {top["comb"]:.1f}% (실예약 {top["solo"]:.1f}% / 타채널 {top["alt"]:.1f}%) ·
      완전 공실 {n_zero}실 · 전수 {len(rows)}실 중 {n_over50}실이 가동률 50% 이상 ·
      평균({mean_c:.1f}%) 대 중앙값({med_c:.1f}%)로 {dist}다.
      면적은 평 단위 표기(<b>1평 &asymp; 3.3&#13217;</b>) · &ldquo;단독&rdquo;은 33m2 자체 예약분만이다.
    </p>''', html, flags=re.S)

    # 평가 섹션(05) — 푸터 바로 앞에 삽입
    extra = eval_section.build(rows, sup, a.cluster, mean_c, med_c,
                               wk_med, a.window, a.caveat)

    # 원룸 vs 멀티룸 섹션(06) — --seg 로 세그먼트 실측치를 넘겼을 때만
    if a.seg:
        seg_rows = json.load(open(a.seg, encoding="utf-8"))
        # 멀티룸은 '가장 가까운 클러스터'로 묶여 있으므로 반경 500m 안쪽만 센다.
        for r in seg_rows:
            if r["seg_type"] == "원룸":
                r["in_radius"] = True
                continue
            clat, clon = sup["clusters"][r["ci"]]["center"]
            r["in_radius"] = m33._haversine_m(
                clat, clon, float(r["lat"]), float(r["lon"])) <= 500
        names = {i: n for i, n in enumerate(a.seg_names.split("|")) if n}
        extra += segment_section.build(seg_rows, a.cluster, a.place,
                                       names, a.city)

    html = html.replace('<footer class="wrap foot">',
                        extra + '<footer class="wrap foot">', 1)

    # 푸터
    html = re.sub(
        r'<footer class="wrap foot">.*?</footer>',
        f'''<footer class="wrap foot">
  <span>다니엘스테이 · {esc(a.place)} 시장검증 보고서 (전수 조사)</span>
  <span>측정 창 {a.window}(56일) · 반경 500m 전수 {len(rows)}실 · 출처: 33m2 실측, 지도 {mapimg.ATTRIB}</span>
</footer>''', html, flags=re.S)

    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)

    # ---- 표지 ----
    cov = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "cover.html"), encoding="utf-8").read()
    cov = cov.replace("상현역 단기임대 시장검증", esc(title))
    cov = re.sub(r'용인시 수지구 상현동 · 신분당선 상현역 · 반경 500m',
                 esc(a.addr) + " · 반경 500m", cov)
    cov = re.sub(r'전수 조사 \d+실', f'전수 조사 {len(rows)}실', cov)
    cov = re.sub(r'통합 가동률 [\d.]+%', f'통합 가동률 {mean_c:.1f}%', cov)
    cov = re.sub(r'주간가 중위 [\d.]+만', f'주간가 중위 {wk_med:.1f}만', cov)
    cov = re.sub(r'2026-\d\d-\d\d', a.date, cov)
    with open(a.cover_out, "w", encoding="utf-8") as f:
        f.write(cov)

    print(json.dumps({
        "place": a.place, "n": len(rows), "n_err": n_err,
        "mean": round(mean_c, 1), "median": round(med_c, 1),
        "solo": round(solo_m, 1), "alt": round(alt_m, 1),
        "wk_med": round(wk_med, 1), "revenue": round(revenue, 1),
        "out": a.out, "cover": a.cover_out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
