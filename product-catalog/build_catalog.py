# -*- coding: utf-8 -*-
"""catalog.json → 단일 HTML 카탈로그(catalog.html) 생성"""
import json
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

TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>제품 카탈로그</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif; background:#f4f6f8; color:#222; }
header { position:sticky; top:0; z-index:10; background:#fff; border-bottom:1px solid #e0e4e8; padding:12px 16px; }
header h1 { font-size:18px; margin-bottom:10px; }
header h1 small { font-weight:normal; color:#888; font-size:12px; margin-left:8px; }
.controls { display:flex; gap:8px; flex-wrap:wrap; }
.controls input, .controls select { padding:8px 12px; border:1px solid #ccd2d8; border-radius:8px; font-size:14px; }
.controls input { flex:1; min-width:180px; }
#count { font-size:13px; color:#667; align-self:center; white-space:nowrap; }
main { max-width:1280px; margin:0 auto; padding:16px; }
.cat-title { font-size:16px; font-weight:bold; margin:20px 4px 4px; color:#1a4b8c; }
.sub-title { font-size:13px; color:#556; margin:12px 4px 8px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:12px; }
.card { background:#fff; border:1px solid #e4e8ec; border-radius:12px; overflow:hidden; display:flex; flex-direction:column; transition:box-shadow .15s; }
.card:hover { box-shadow:0 4px 14px rgba(0,0,0,.1); }
.card a { text-decoration:none; color:inherit; display:flex; flex-direction:column; height:100%; }
.thumb { aspect-ratio:1; background:#fff; display:flex; align-items:center; justify-content:center; overflow:hidden; }
.thumb img { max-width:100%; max-height:100%; object-fit:contain; }
.thumb .noimg { color:#bbb; font-size:12px; }
.info { padding:10px 12px; flex:1; display:flex; flex-direction:column; gap:4px; }
.model { font-size:11px; color:#99a; word-break:break-all; }
.pname { font-size:13px; line-height:1.35; flex:1; }
.prices { margin-top:6px; }
.p1 { font-size:14px; font-weight:bold; color:#d32; }
.p1 span, .p2 span { font-size:11px; font-weight:normal; color:#889; margin-right:4px; }
.p2 { font-size:12px; color:#357; }
.more { display:block; margin:16px auto; padding:10px 32px; border:1px solid #ccd2d8; background:#fff; border-radius:20px; cursor:pointer; font-size:14px; }
.more:hover { background:#f0f3f6; }
footer { text-align:center; color:#99a; font-size:12px; padding:24px; }
</style>
</head>
<body>
<header>
  <h1>제품 카탈로그 <small id="meta"></small></h1>
  <div class="controls">
    <select id="rootSel"><option value="">전체 카테고리</option></select>
    <select id="subSel"><option value="">전체 하위분류</option></select>
    <input id="q" type="search" placeholder="제품명·모델명 검색 (예: 정수기, 삼성, WD723)">
    <span id="count"></span>
  </div>
</header>
<main id="main"></main>
<footer>출처: tlpcserver.imakeweb.co.kr · 수집일 __DATE__</footer>
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
document.getElementById('meta').textContent = `총 ${totalProducts.toLocaleString()}개 제품 (중복 포함)`;

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

function card(p) {
  const img = p.image ? `<img loading="lazy" src="${p.image}" alt="">` : '<span class="noimg">이미지 없음</span>';
  return `<div class="card"><a href="${p.url}" target="_blank" rel="noopener">
    <div class="thumb">${img}</div>
    <div class="info">
      <div class="model">${p.model||''}</div>
      <div class="pname">${p.name}</div>
      <div class="prices">
        <div class="p1"><span>월</span>${p.price_monthly||'-'}</div>
        <div class="p2"><span>카드할인시</span>${p.price_card||'-'}</div>
      </div>
    </div></a></div>`;
}

function render(reset) {
  if (reset) shown = PAGE;
  const items = collect();
  document.getElementById('count').textContent = `${items.length.toLocaleString()}개`;
  const slice = items.slice(0, shown);
  // 카테고리별 그룹 헤더
  let html = '', lastKey = '';
  for (const p of slice) {
    const key = p._root + '>' + p._sub;
    if (key !== lastKey) {
      if (lastKey) html += '</div>';
      html += `<div class="cat-title">${p._root} <span style="color:#889;font-weight:normal">›</span> ${p._sub}</div><div class="grid">`;
      lastKey = key;
    }
    html += card(p);
  }
  if (lastKey) html += '</div>';
  if (items.length > shown)
    html += `<button class="more" onclick="shown+=${PAGE};render(false)">더 보기 (${(items.length-shown).toLocaleString()}개 남음)</button>`;
  if (!items.length) html = '<p style="text-align:center;color:#99a;padding:60px 0">검색 결과가 없습니다</p>';
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
print(f"OK {out} ({out.stat().st_size/1024/1024:.1f} MB)")
