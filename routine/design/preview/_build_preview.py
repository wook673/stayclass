# -*- coding: utf-8 -*-
"""미리보기 배포본 빌더 (A안/C안) — 채택 전 프리뷰 전용.
파이프라인(build_report.py / report_shots.py / seg_rows.py)은 건드리지 않는다.
report_shots.py 는 CLI 로 호출만 한다.
"""
import base64, io, json, os, re, statistics, subprocess, sys
from pathlib import Path

ROOT = Path(r"C:\Users\User\test")
OUT = ROOT / "routine" / "out"
PREV = ROOT / "routine" / "design" / "preview"
SRC = ROOT / "routine" / "design" / "report_concepts_2026-09-07.html"
DATE = "2026-09-07"
PREV.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 데이터
supply = json.load(open(OUT / f"화성시_{DATE}_supply.json", encoding="utf-8"))
occ = json.load(open(OUT / f"화성시_{DATE}_occ.json", encoding="utf-8"))
W = 56


def cstat(ci):
    c = supply["clusters"][ci]
    a = b = 0
    rates = []
    for r in c["rooms"]:
        x, y, _ = map(int, occ[str(r["rid"])].split(":"))
        a += x
        b += y
        rates.append((x + y) / W * 100)
    T = len(c["rooms"]) * W
    return dict(n=len(c["rooms"]), tot=T, m33=a, oth=b, vac=T - a - b,
                comb=(a + b) / T * 100, med=statistics.median(rates),
                rates=sorted(rates, reverse=True),
                weekly=statistics.median([r["weekly"] for r in c["rooms"]]))


S = cstat(4)
PEERS = [(4, "능동"), (3, "송동"), (0, "여울동·오산동"),
         (5, "오산동·여울동"), (1, "영천동"), (2, "반송동")]
peer = [(nm, cstat(i)) for i, nm in PEERS]
assert [round(p[1]["comb"], 1) for p in peer] == [74.0, 67.7, 67.3, 57.3, 57.1, 55.8]
assert (S["n"], S["tot"], S["m33"], S["oth"], S["vac"]) == (20, 1120, 662, 167, 291)

# 지번 구성
lots = {}
for r in supply["clusters"][4]["rooms"]:
    addr = r["addr"].split("능동", 1)[1].strip()
    parts = addr.split()
    lots.setdefault(parts[-1] if len(parts) > 1 else parts[0], 0)
    lots[parts[-1] if len(parts) > 1 else parts[0]] += 1
lots = sorted(lots.items(), key=lambda kv: -kv[1])

MED = f"{S['med']:.1f}"
COMB = f"{S['comb']:.1f}"
PRICE = f"{S['weekly'] / 10000:.1f}"
# 표시값(소수 1자리)끼리의 차이 — 본문 숫자와 어긋나지 않게 반올림 후 계산
GAP_LOW = f"{round(S['comb'], 1) - round(peer[5][1]['comb'], 1):.1f}"
GAP_2ND = f"{round(S['comb'], 1) - round(peer[1][1]['comb'], 1):.1f}"

# ---------------------------------------------------------------- 원본 조각
raw = SRC.read_text(encoding="utf-8")
head_css = raw[raw.index("<style>"):raw.index("</style>") + 8]
# 구분 헤더(.concept-bar) 블록 제거 후 각 시안 섹션만 추출
A_HTML = raw[raw.index('<section class="A">'):raw.index("</section>", raw.index('<section class="A">')) + 10]
C_HTML = raw[raw.index('<section class="C">'):raw.rindex("</section>") + 10]

EXTRA_CSS = """
<style>
/* 배포본 전용 추가(시안 원본 CSS 는 그대로 승계) */
.mapbox{background:#fff;border:1px solid var(--n-200);border-radius:12px;overflow:hidden}
.mapbox img{width:100%;display:block}
.mapcap{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px 16px;
  font-size:12.5px;color:var(--n-500);padding:12px 16px;
  border-top:1px solid var(--n-200);background:var(--n-100)}
.docfoot{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;
  font-size:12px;color:var(--n-400);border-top:1px solid var(--n-200);
  margin-top:36px;padding-top:18px}
</style>
"""

FOOT_A = ('<div class="docfoot">'
          '<span>다니엘스테이 · 능동 시장검증 요약 (전수 조사)</span>'
          f'<span>조사기준일 {DATE} · 측정 창 {DATE} ~ 11-01(56일) · 반경 500m 전수 {S["n"]}실 · 출처: 33m2 실측</span>'
          '</div>')
FOOT_C = ('<div class="docfoot">'
          '<span>다니엘스테이 · 능동 시장검증 보고서 (전수 조사)</span>'
          f'<span>조사기준일 {DATE} · 측정 창 {DATE} ~ 11-01(56일) · 반경 500m 전수 {S["n"]}실 · '
          '출처: 33m2 실측, 지도 © VWorld (국토교통부)</span>'
          '</div>')

# ---------------------------------------------------------------- 문구 교정
FIXES = [
    ("82.1%", f"{MED}%"),          # 중앙값 — 원측정치 재계산값
    ("22.0<span", f"{PRICE}<span"),
    ("22.0만원", f"{PRICE}만원"),
    ("같은 시, 18%p 차이", f"같은 시, {GAP_LOW}%p 차이"),
    ("2위권(67%대)과 6~7%p", f"2위권(67%대)과 {GAP_2ND}%p"),
    ("18.2%p 차이로", f"{GAP_LOW}%p 차이로"),
    ("하위 3실(진한 주황)", "하위 3실(연한 주황)"),   # 실제 막대색은 --terra-300(연한 톤)
]


def fix(h):
    for a, b in FIXES:
        h = h.replace(a, b)
    # 분포 막대 상위 10실 문장의 임계값(중앙값 아님, 10위 실측값 82.1%)은 그대로 둔다
    h = h.replace(f"상위 10실은 모두 {MED}% 이상", "상위 10실은 모두 82% 이상")
    return h


A_HTML = fix(A_HTML)
C_HTML = fix(C_HTML)

# ---------------------------------------------------------------- A안 조립
A_HTML = A_HTML.replace('</div>\n  </div>\n</section>', f'</div>\n    {FOOT_A}\n  </div>\n</section>')
assert "docfoot" in A_HTML, "A안 푸터 삽입 실패"

PRE = ('<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
       '<title>{t}</title>\n'
       '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/pretendard@1.3.9'
       '/dist/web/variable/pretendardvariable-dynamic-subset.min.css">\n')

(PREV / f"미리보기_A_능동_한장요약_{DATE}.html").write_text(
    PRE.format(t=f"다니엘스테이 · 능동 단기임대 실측 한 장 요약 {DATE}")
    + head_css + EXTRA_CSS + "</head>\n<body>\n" + A_HTML + "\n</body>\n</html>\n",
    encoding="utf-8")

# ---------------------------------------------------------------- C안: 지도 섹션 + 번호 재배열
mp = PREV / f"_map_능동_{DATE}.png"
b64 = base64.b64encode(mp.read_bytes()).decode()
lat, lon = supply["clusters"][4]["center"]
MAP_SEC = f"""
  <div class="sec-head"><span class="sec-num">03</span><span class="sec-title">반경 500m 지도</span></div>
  <div class="mapbox">
    <img src="data:image/png;base64,{b64}" alt="능동 반경 500m 조사 범위 지도">
    <div class="mapcap">
      <span>중심 <b>{lat:.4f} / {lon:.4f}</b> · 실선원 반경 500m</span>
      <span>원 안 실측 매물 <b>{S['n']}실</b> · 금색 마커는 선점률 상위 3실</span>
      <span>배경 지도 © VWorld (국토교통부)</span>
    </div>
  </div>
  <p class="note" style="margin-top:12px">
    본 보고서의 모든 수치는 이 원 안에서 수집한 {S['n']}실 전수를 대상으로 한다.
    반경 밖 매물은 집계에 포함하지 않았다.
  </p>
"""

old = '<div class="sec-head"><span class="sec-num">03</span><span class="sec-title">개별 20실 분포 · 지번 구성</span></div>'
new = (MAP_SEC +
       '\n  <div class="sec-head"><span class="sec-num">04</span>'
       '<span class="sec-title">개별 20실 분포 · 지번 구성</span></div>')
assert old in C_HTML
C_HTML = C_HTML.replace(old, new)
C_HTML = C_HTML.replace("</ul>\n</section>", "</ul>\n" + FOOT_C + "\n</section>")
assert "docfoot" in C_HTML, "C안 푸터 삽입 실패"

(PREV / f"미리보기_C_능동_컨설팅리포트_{DATE}.html").write_text(
    PRE.format(t=f"다니엘스테이 · 능동 단기임대 실측 컨설팅 리포트 {DATE}")
    + head_css + EXTRA_CSS + "</head>\n<body>\n" + C_HTML + "\n</body>\n</html>\n",
    encoding="utf-8")

# ---------------------------------------------------------------- C안 표지
cov = (OUT / f"_cover_능동_{DATE}.html").read_text(encoding="utf-8")
cov = cov.replace("통합 가동률 74.0%", f"통합 가동률 {COMB}%").replace(
    "주간가 중위 21.5만", f"주간가 중위 {PRICE}만").replace(
    "전수 조사 20실", f"전수 조사 {S['n']}실")
(PREV / f"_표지_C_능동_{DATE}.html").write_text(cov, encoding="utf-8")

print("HTML 완료")
print(json.dumps({"comb": COMB, "med": MED, "price": PRICE,
                  "m33": S["m33"], "oth": S["oth"], "vac": S["vac"],
                  "tot": S["tot"], "lots": lots}, ensure_ascii=False))
