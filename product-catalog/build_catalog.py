# -*- coding: utf-8 -*-
"""catalog.json → 단일 HTML 카탈로그(catalog.html) 생성"""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
data = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))

# 카테고리 재분류: (원래 루트 이름, 하위분류 이름) -> 옮길 루트 이름
RECATEGORIZE = {
    ("환경가전", "가습기"): "생활가전",
    ("환경가전", "공기청정기"): "생활가전",
    ("환경가전", "제습기"): "생활가전",
    ("환경가전", "비데"): "생활가전",
    ("환경가전", "연수기"): "생활가전",
}

def apply_recategorize(data):
    roots = {r["name"]: r for r in data}
    for (src_name, sub_name), dst_name in RECATEGORIZE.items():
        src, dst = roots.get(src_name), roots.get(dst_name)
        if not src or not dst:
            continue
        moving = [s for s in src["subcategories"] if s["name"] == sub_name]
        src["subcategories"] = [s for s in src["subcategories"] if s["name"] != sub_name]
        dst["subcategories"].extend(moving)
    # 하위분류가 모두 빠져 비게 된 루트는 제거
    data[:] = [r for r in data if r["subcategories"]]

apply_recategorize(data)

# ── 영업 추천멘트(ments.json) 매칭 ─────────────────────────────
def _norm_code(s):
    """모델코드 정규화: 대문자화 + 영숫자만"""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())

def _find_ment(code, code2ment, codes_sorted):
    """정확 일치 우선, 없으면 접두 일치(색상/자가관리 접미 흡수, 길이차 3 이내)"""
    if code in code2ment:
        return code2ment[code]
    if len(code) < 6:
        return None
    for mc, ment in codes_sorted:
        shorter, longer = (mc, code) if len(mc) <= len(code) else (code, mc)
        if len(shorter) >= 6 and len(longer) - len(shorter) <= 3 and longer.startswith(shorter):
            return ment
    return None

def apply_ments(data):
    ments_file = HERE / "ments.json"
    if not ments_file.exists():
        return 0
    ments = json.loads(ments_file.read_text(encoding="utf-8"))
    code2ment = {}
    for m in ments:
        for c in m["models"]:
            code2ment.setdefault(c, m["ment"])
    codes_sorted = sorted(code2ment.items(), key=lambda kv: -len(kv[0]))
    matched = 0
    for r in data:
        for s in r["subcategories"]:
            for p in s["products"]:
                # "WD723RK/WD723RE"처럼 슬래시로 나뉜 경우 각각 비교
                for part in (p.get("model") or "").split("/"):
                    ment = _find_ment(_norm_code(part), code2ment, codes_sorted)
                    if ment:
                        p["ment"] = ment
                        matched += 1
                        break
    return matched

_ment_count = apply_ments(data)

# 파일 크기 절감: url은 goodscode로 JS에서 복원, 이미지 공통 접두 제거
IMG_PREFIX = "https://tlpcserver.imakeweb.co.kr/data/goods/"
for _r in data:
    for _s in _r["subcategories"]:
        for _p in _s["products"]:
            _p.pop("url", None)
            if (_p.get("image") or "").startswith(IMG_PREFIX):
                _p["image"] = _p["image"][len(IMG_PREFIX):]

TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>제품 카탈로그</title>
<style>
:root {
  --bg:#f5f7f6;
  --surface:#ffffff;
  --ink:#182420;
  --muted:#6c7a74;
  --faint:#9aa6a0;
  --line:#e7ece9;
  --line-strong:#dbe3df;
  --point:#12513a;
  --point-2:#0d6b4a;
  --point-soft:#e8f2ec;
  --price:#12513a;
  --shadow:0 1px 2px rgba(20,40,32,.04), 0 6px 18px rgba(20,40,32,.05);
  --shadow-hover:0 4px 10px rgba(20,40,32,.07), 0 16px 32px rgba(20,40,32,.09);
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Cascadia Mono",monospace;
  --ease:cubic-bezier(0.16,1,0.3,1);
}
* { margin:0; padding:0; box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body {
  font-family:"Pretendard Variable",Pretendard,-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic","맑은 고딕",system-ui,sans-serif;
  background:var(--bg); color:var(--ink);
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
  line-height:1.5;
  overflow-x:hidden;
}
a { color:inherit; text-decoration:none; }

/* ── Header ───────────────────────────── */
header {
  position:sticky; top:0; z-index:20;
  background:rgba(255,255,255,.72);
  -webkit-backdrop-filter:saturate(180%) blur(14px);
  backdrop-filter:saturate(180%) blur(14px);
  border-bottom:1px solid var(--line);
}
.header-inner {
  max-width:1440px; margin:0 auto; padding:14px 20px;
  display:flex; align-items:center; gap:16px 20px; flex-wrap:wrap;
}
.brand { display:flex; align-items:baseline; gap:10px; flex-shrink:0; }
.brand h1 {
  font-size:19px; font-weight:800; letter-spacing:-.035em; color:var(--ink);
  display:flex; align-items:center; gap:8px;
}
.brand h1::before {
  content:""; width:9px; height:9px; border-radius:50%;
  background:var(--point); box-shadow:0 0 0 4px var(--point-soft);
}
.brand small {
  font-family:var(--mono); font-variant-numeric:tabular-nums;
  font-size:11px; font-weight:400; color:var(--faint); letter-spacing:0;
}
.controls { display:flex; align-items:center; gap:10px; flex:1; flex-wrap:wrap; justify-content:flex-end; }
.field { position:relative; display:flex; align-items:center; }
.controls select, .controls input {
  font:inherit; font-size:14px; color:var(--ink);
  background:var(--surface); border:1px solid var(--line-strong);
  border-radius:11px; padding:10px 14px; height:42px;
  transition:border-color .25s var(--ease), box-shadow .25s var(--ease);
}
.controls select {
  cursor:pointer; padding-right:34px;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236c7a74' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat:no-repeat; background-position:right 12px center;
  -webkit-appearance:none; appearance:none;
}
.search { flex:1; min-width:220px; max-width:420px; }
.search input { width:100%; padding-left:40px; }
.search svg { position:absolute; left:14px; width:17px; height:17px; color:var(--faint); pointer-events:none; }
.controls select:focus-visible, .controls input:focus-visible {
  outline:none; border-color:var(--point);
  box-shadow:0 0 0 3px var(--point-soft);
}
#count {
  font-size:13px; font-weight:600; color:var(--point);
  font-variant-numeric:tabular-nums;
  background:var(--point-soft); border-radius:999px;
  padding:8px 14px; white-space:nowrap; flex-shrink:0;
}

/* ── Main ─────────────────────────────── */
main { max-width:1440px; margin:0 auto; padding:22px 20px 40px; }

.cat-group { margin-top:38px; }
.cat-group:first-child { margin-top:10px; }
.cat-head { display:flex; align-items:baseline; gap:11px; margin:0 2px 16px; }
.cat-head .idx {
  font-family:var(--mono); font-variant-numeric:tabular-nums;
  font-size:11px; font-weight:500; color:var(--point);
  letter-spacing:.06em; flex-shrink:0;
  padding-bottom:1px; border-bottom:2px solid var(--point);
}
.cat-head .root { font-size:17px; font-weight:800; letter-spacing:-.03em; color:var(--ink); }
.cat-head .chev { color:var(--faint); font-size:13px; }
.cat-head .sub {
  font-size:12.5px; font-weight:600; color:var(--point);
  background:var(--point-soft); border-radius:999px; padding:4px 11px;
  align-self:center;
}
.cat-head .rule { flex:1; height:1px; background:var(--line); align-self:center; }
.cat-head .cnt {
  font-family:var(--mono); font-variant-numeric:tabular-nums;
  font-size:11px; color:var(--faint); flex-shrink:0; letter-spacing:.02em;
}

.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(196px,1fr)); gap:16px; }

@keyframes card-in {
  from { opacity:0; transform:translateY(8px); }
  to { opacity:1; transform:translateY(0); }
}
@keyframes shimmer {
  from { background-position:200% 0; }
  to { background-position:-200% 0; }
}
.card {
  position:relative;
  background:var(--surface); border:1px solid var(--line);
  border-radius:16px; overflow:hidden;
  display:flex; flex-direction:column;
  box-shadow:var(--shadow);
  transition:transform .35s var(--ease), box-shadow .35s var(--ease), border-color .35s var(--ease);
  animation:card-in .5s var(--ease) both;
  animation-delay:calc(var(--i,0) * 25ms);
}
.card:active { transform:scale(.98); }
.feebtn {
  position:absolute; top:10px; right:10px; z-index:2;
  background:rgba(18,81,58,.92); color:#fff; text-decoration:none;
  font-size:11px; font-weight:700; letter-spacing:.02em;
  padding:5px 9px; border-radius:20px;
  opacity:.92; transition:opacity .2s, transform .2s;
}
.feebtn:hover { opacity:1; transform:scale(1.05); }
.card a { display:flex; flex-direction:column; height:100%; }
.card a:focus-visible { outline:2px solid var(--point); outline-offset:2px; border-radius:16px; }

.thumb {
  aspect-ratio:1; background:#fbfcfb;
  border-bottom:1px solid var(--line);
  display:flex; align-items:center; justify-content:center;
  overflow:hidden; padding:16px;
}
.thumb.sk {
  background:linear-gradient(100deg,#f2f5f3 40%,#fbfdfc 50%,#f2f5f3 60%) #fbfcfb;
  background-size:200% 100%;
  animation:shimmer 1.6s linear infinite;
}
.thumb.sk:has(img.ld) { animation:none; background:#fbfcfb; }
.thumb img {
  max-width:100%; max-height:100%; object-fit:contain; mix-blend-mode:multiply;
  opacity:0; transition:opacity .45s var(--ease), transform .35s var(--ease);
}
.thumb img.ld { opacity:1; }
.thumb .noimg { color:var(--faint); font-size:12px; }

.info { padding:13px 14px 15px; flex:1; display:flex; flex-direction:column; gap:5px; }
.model {
  font-size:10.5px; font-weight:600; letter-spacing:.02em;
  color:var(--faint); text-transform:uppercase; word-break:break-all;
}
.pname {
  font-size:13.5px; font-weight:500; line-height:1.4; color:var(--ink);
  flex:1;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
}
.ment {
  margin-top:2px; display:flex; gap:7px; align-items:flex-start;
  font-size:11.5px; line-height:1.45; color:#1e4a37;
  background:var(--point-soft); border-left:3px solid var(--point);
  border-radius:4px 8px 8px 4px; padding:6px 9px 6px 8px;
}
.ment svg { width:12px; height:12px; flex-shrink:0; margin-top:2px; color:var(--point); }
.ment .txt {
  display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical;
  overflow:hidden; white-space:pre-line;
}
.card.has-ment { border-color:#cde0d6; }
.prices { margin-top:8px; padding-top:10px; border-top:1px dashed var(--line-strong); }
.p1 {
  font-size:17px; font-weight:800; color:var(--price); letter-spacing:-.02em;
  font-variant-numeric:tabular-nums;
  display:flex; align-items:baseline; gap:5px;
}
.p1 .lab { font-size:11px; font-weight:700; color:var(--muted); }
.p2 {
  margin-top:6px; display:inline-flex; align-items:center; gap:5px;
  font-size:11.5px; font-weight:600; color:var(--point);
  font-variant-numeric:tabular-nums;
  background:var(--point-soft); border-radius:7px; padding:3px 8px;
}
.p2 .lab { font-weight:700; opacity:.85; }

/* ── More button ──────────────────────── */
.more-wrap { display:flex; justify-content:center; margin:32px 0 8px; }
.more {
  font:inherit; font-size:14px; font-weight:700; color:var(--point);
  font-variant-numeric:tabular-nums;
  background:var(--surface); border:1.5px solid var(--line-strong);
  border-radius:999px; padding:13px 30px; cursor:pointer;
  display:inline-flex; align-items:center; gap:8px;
  transition:background .3s var(--ease), border-color .3s var(--ease), color .3s var(--ease), transform .2s var(--ease), box-shadow .3s var(--ease);
}
.more:active { transform:scale(.98); }
.more:focus-visible { outline:none; box-shadow:0 0 0 3px var(--point-soft); }

/* ── Hover (포인터 기기 전용) ─────────── */
@media (hover:hover) {
  .controls select:hover, .controls input:hover { border-color:var(--faint); }
  .card:hover { transform:translateY(-4px); box-shadow:var(--shadow-hover); border-color:var(--line-strong); }
  .card:hover .thumb img { transform:scale(1.04); }
  .more:hover { background:var(--point); border-color:var(--point); color:#fff; box-shadow:0 8px 20px rgba(18,81,58,.22); }
}

/* ── Empty state ──────────────────────── */
.empty { text-align:center; padding:80px 20px; color:var(--muted); }
.empty svg { width:56px; height:56px; color:var(--line-strong); margin-bottom:16px; }
.empty .t { font-size:16px; font-weight:700; color:var(--ink); margin-bottom:6px; }
.empty .d { font-size:13.5px; color:var(--faint); }

footer {
  max-width:1440px; margin:0 auto; padding:28px 20px 44px;
  display:flex; align-items:center; gap:12px;
  color:var(--faint); font-size:12px;
}
footer::before { content:""; flex:1; height:1px; background:var(--line); }
footer::after { content:""; flex:1; height:1px; background:var(--line); }
footer .src { white-space:nowrap; }
footer a { color:var(--muted); font-weight:600; }
footer .date { font-family:var(--mono); font-variant-numeric:tabular-nums; white-space:nowrap; }

/* ── Reduced motion ───────────────────── */
@media (prefers-reduced-motion:reduce) {
  .card { animation:none; }
  .thumb.sk { animation:none; background:#fbfcfb; }
  .card, .thumb img, .more, .controls select, .controls input { transition:none; }
}

/* ── Tablet (≤768px): 3열 그리드 ──────── */
@media (max-width:768px) {
  main { padding:18px 16px 36px; }
  .grid { grid-template-columns:repeat(3,1fr); gap:14px; }
}

/* ── Mobile header (≤640px): 타이틀 / 검색+개수 / 셀렉트 반반 ── */
@media (max-width:640px) {
  .header-inner { padding:10px 12px 12px; gap:8px; }
  .brand { width:100%; justify-content:space-between; align-items:baseline; }
  .brand h1 { font-size:17px; }
  .brand h1::before { width:8px; height:8px; box-shadow:0 0 0 3px var(--point-soft); }
  .brand small { font-size:11px; }
  .controls { width:100%; gap:8px; min-width:0; }
  .controls select, .controls input {
    height:44px; font-size:16px; border-radius:10px; padding:0 12px;
  }
  .search { order:1; flex:1 1 auto; min-width:0; max-width:none; }
  .search input { padding-left:38px; }
  .search svg { left:12px; }
  #count {
    order:2; flex-shrink:0; font-size:12.5px; padding:0 12px;
    height:44px; display:inline-flex; align-items:center;
  }
  .f-root, .f-sub { order:3; flex:1 1 calc(50% - 4px); min-width:0; }
  .f-root select, .f-sub select {
    width:100%; padding-right:30px; background-position:right 10px center;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  }
}

/* ── Mobile (≤480px): 2열 컴팩트 ──────── */
@media (max-width:480px) {
  main { padding:14px 14px 30px; }
  .grid { grid-template-columns:repeat(2,1fr); gap:10px; }
  .card { border-radius:12px; }
  .card a:focus-visible { border-radius:12px; }
  .thumb { padding:10px; }
  .info { padding:10px 11px 12px; gap:4px; }
  .model { font-size:10px; }
  .pname { font-size:13px; }
  .ment { font-size:11px; gap:6px; padding:5px 8px 5px 7px; }
  .prices { margin-top:6px; padding-top:8px; }
  .p1 { font-size:15.5px; }
  .p2 { font-size:11px; padding:3px 7px; }
  .cat-group { margin-top:26px; }
  .cat-head { gap:8px; margin:0 0 12px; flex-wrap:nowrap; }
  .cat-head .rule { display:none; }
  .cat-head .idx { font-size:10px; }
  .cat-head .cnt { display:none; }
  .cat-head .root { font-size:15px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .cat-head .chev { flex-shrink:0; }
  .cat-head .sub { flex-shrink:0; white-space:nowrap; font-size:11.5px; padding:3px 9px; }
  .more-wrap { margin:24px 2px 4px; }
  .more { width:100%; justify-content:center; padding:14px 20px; }
  .empty { padding:60px 16px; }
  footer { padding:22px 16px 34px; }
}
</style>
</head>
<body>
<header>
  <div class="header-inner">
    <div class="brand">
      <h1>제품 카탈로그</h1>
      <small id="meta"></small>
    </div>
    <div class="controls">
      <div class="field f-root"><select id="rootSel"><option value="">전체 카테고리</option></select></div>
      <div class="field f-sub"><select id="subSel"><option value="">전체 하위분류</option></select></div>
      <div class="field search">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input id="q" type="search" placeholder="제품명·모델명 검색 (예: 정수기, 삼성, WD723)">
      </div>
      <span id="count"></span>
    </div>
  </div>
</header>
<main id="main"></main>
<footer><span class="src">출처: <a href="https://tlpcserver.imakeweb.co.kr" target="_blank" rel="noopener">tlpcserver.imakeweb.co.kr</a></span><span class="date">수집일 __DATE__</span></footer>
<script>
const DATA = __DATA__;
const PAGE = 120;
let shown = PAGE;

const rootSel = document.getElementById('rootSel');
const subSel = document.getElementById('subSel');
const q = document.getElementById('q');
const main = document.getElementById('main');

let totalProducts = 0;
DATA.forEach(r => {
  const opt = document.createElement('option');
  opt.value = r.root; opt.textContent = r.name;
  rootSel.appendChild(opt);
  r.subcategories.forEach(s => totalProducts += s.products.length);
});
document.getElementById('meta').textContent = `총 ${totalProducts.toLocaleString()}개 · 중복 포함`;

function refreshSubs() {
  subSel.innerHTML = '<option value="">전체 하위분류</option>';
  const r = DATA.find(x => x.root === rootSel.value);
  if (r) r.subcategories.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.category || s.name; opt.textContent = `${s.name} (${s.products.length})`;
    subSel.appendChild(opt);
  });
}

function norm(s) { return (s||'').toLowerCase().replace(/\\s+/g,''); }
function esc(s) { return (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function collect() {
  const kw = norm(q.value);
  const out = [];
  for (const r of DATA) {
    if (rootSel.value && r.root !== rootSel.value) continue;
    for (const s of r.subcategories) {
      if (subSel.value && (s.category || s.name) !== subSel.value) continue;
      for (const p of s.products) {
        if (kw && !norm(p.name).includes(kw) && !norm(p.model).includes(kw)) continue;
        out.push({...p, _root:r.name, _sub:s.name});
      }
    }
  }
  return out;
}

const MENT_ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>';

const IMG_BASE = 'https://tlpcserver.imakeweb.co.kr/data/goods/';
const VIEW_BASE = 'https://tlpcserver.imakeweb.co.kr/kor/mall/view.asp?goodscode=';

function card(p, ci) {
  const img = p.image
    ? `<img loading="lazy" src="${esc(p.image.startsWith('http') ? p.image : IMG_BASE + p.image)}" alt="" onload="this.classList.add('ld')" onerror="this.classList.add('ld')">`
    : '<span class="noimg">이미지 준비중</span>';
  const p2 = p.price_card
    ? `<div class="p2"><span class="lab">카드할인</span>${esc(p.price_card)}</div>` : '';
  const ment = p.ment
    ? `<div class="ment">${MENT_ICON}<span class="txt">${esc(p.ment)}</span></div>` : '';
  const stagger = ci < 20 ? ci : 0; // 그리드당 앞 20개만 스태거, 이후 즉시
  const feeBtn = p.model
    ? `<a class="feebtn" href="../chatbot.html?q=${encodeURIComponent(p.model.split('/')[0])}" target="_blank" rel="noopener">수수료</a>` : '';
  return `<div class="card${p.ment ? ' has-ment' : ''}" style="--i:${stagger}">${feeBtn}<a href="${VIEW_BASE}${esc(p.goodscode)}" target="_blank" rel="noopener">
    <div class="thumb${p.image ? ' sk' : ''}">${img}</div>
    <div class="info">
      <div class="model">${esc(p.model)||'&nbsp;'}</div>
      <div class="pname">${esc(p.name)}</div>
      ${ment}
      <div class="prices">
        <div class="p1"><span class="lab">월</span>${esc(p.price_monthly)||'-'}</div>
        ${p2}
      </div>
    </div></a></div>`;
}

function render(reset) {
  if (reset) shown = PAGE;
  const items = collect();
  document.getElementById('count').textContent = `${items.length.toLocaleString()}개`;
  const slice = items.slice(0, shown);
  // 그룹별 전체 개수 (필터 결과 기준)
  const gcounts = {};
  for (const it of items) {
    const k = it._root + '>' + it._sub;
    gcounts[k] = (gcounts[k] || 0) + 1;
  }
  // 카테고리별 그룹 헤더
  let html = '', lastKey = '', gi = 0, ci = 0;
  for (const p of slice) {
    const key = p._root + '>' + p._sub;
    if (key !== lastKey) {
      if (lastKey) html += '</div></section>';
      gi++; ci = 0;
      html += `<section class="cat-group"><div class="cat-head">`
        + `<span class="idx">${String(gi).padStart(2,'0')}</span>`
        + `<span class="root">${esc(p._root)}</span>`
        + `<span class="chev">›</span>`
        + `<span class="sub">${esc(p._sub)}</span>`
        + `<span class="rule"></span>`
        + `<span class="cnt">${gcounts[key].toLocaleString()}개</span></div><div class="grid">`;
      lastKey = key;
    }
    html += card(p, ci++);
  }
  if (lastKey) html += '</div></section>';
  if (items.length > shown)
    html += `<div class="more-wrap"><button class="more" onclick="shown+=${PAGE};render(false)">더 보기 <span style="opacity:.7">(${(items.length-shown).toLocaleString()}개 남음)</span></button></div>`;
  if (!items.length) html = `<div class="empty">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
    <div class="t">검색 결과가 없습니다</div>
    <div class="d">다른 검색어나 카테고리를 선택해 보세요</div>
  </div>`;
  main.innerHTML = html;
}

rootSel.onchange = () => { refreshSubs(); render(true); };
subSel.onchange = () => render(true);
let t; q.oninput = () => { clearTimeout(t); t = setTimeout(() => render(true), 200); };
render(true);
</script>
</body>
</html>
"""

import datetime
html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
html = html.replace("__DATE__", datetime.date.today().isoformat())
out = HERE / "catalog.html"
out.write_text(html, encoding="utf-8")
print(f"OK {out} ({out.stat().st_size/1024/1024:.1f} MB) / 추천멘트 매칭 제품 {_ment_count}개")
