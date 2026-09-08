# -*- coding: utf-8 -*-
"""seg_rows.py — supply + occ → 원룸/멀티룸 세그먼트 rows JSON.

`build_report.py --seg` 가 먹는 파일을 만든다. 이게 없으면 06 섹션이 손으로
만든 파일에 의존하게 되므로, 회차마다 이 스크립트를 거치도록 한다.

  1) 조회 대상 뽑기 — 아직 안 잰 rid 목록을 내보낸다(브라우저 측정용)
     python routine/seg_rows.py --supply ..._supply.json --occ ..._occ.json \
         --clusters 0,1,2,3 --todo
  2) rows 만들기 — 측정 끝난 occ 로 rows 를 굽는다
     python routine/seg_rows.py --supply ..._supply.json --occ ..._occ.json \
         --clusters 0,1,2,3 --out ..._seg_rows.json

occ 스키마: {"<rid>": "booking:disable:days"}  (build_report 와 동일)
멀티룸의 ci 는 '가장 가까운 클러스터' — 반경 500m 판정은 build_report 가 한다.
캘린더가 창 안에서 0일을 돌려준 매물(n=0)은 가동률을 낼 수 없으므로 제외한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "market-analyzer"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import m33  # noqa: E402

WINDOW_DAYS = 56


def nearest_cluster(lat, lon, centers):
    return min(range(len(centers)),
               key=lambda i: m33._haversine_m(centers[i][0], centers[i][1],
                                              lat, lon))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--supply", required=True)
    ap.add_argument("--occ", required=True)
    ap.add_argument("--clusters", default="0",
                    help="원룸 대조군으로 쓸 클러스터 인덱스, 쉼표 구분")
    ap.add_argument("--out", default="")
    ap.add_argument("--todo", action="store_true",
                    help="rows 대신 '아직 안 잰 rid' 목록만 출력")
    a = ap.parse_args()

    sup = json.load(open(a.supply, encoding="utf-8"))
    occ = (json.load(open(a.occ, encoding="utf-8"))
           if os.path.exists(a.occ) else {})
    idxs = [int(x) for x in a.clusters.split(",") if x.strip() != ""]
    centers = [c["center"] for c in sup["clusters"]]

    # 원룸 — 지정 클러스터 소속 전수
    cand = []
    for ci in idxs:
        for r in sup["clusters"][ci]["rooms"]:
            cand.append({"rid": r["rid"], "seg_type": "원룸", "ci": ci,
                         "wk": r.get("weekly"), "py": r.get("pyeong"),
                         "name": r.get("name"),
                         "lat": r["lat"], "lon": r["lon"]})

    # 멀티룸 — 가장 가까운 클러스터가 대상 클러스터인 것만
    for m in sup.get("multi", []):
        ci = nearest_cluster(m["lat"], m["lon"], centers)
        if ci not in idxs:
            continue
        cand.append({"rid": m["rid"], "seg_type": "멀티룸", "ci": ci,
                     "wk": m.get("weekly"), "py": m.get("pyeong"),
                     "name": m.get("name"),
                     "lat": m["lat"], "lon": m["lon"]})

    if a.todo:
        todo = [c["rid"] for c in cand if str(c["rid"]) not in occ]
        print(f"# 대상 {len(cand)}실 · 미측정 {len(todo)}실 · "
              f"예상 {len(todo) * 3}콜", file=sys.stderr)
        print(json.dumps(todo, separators=(",", ":")))
        return

    rows, skipped = [], []
    for c in cand:
        rec = occ.get(str(c["rid"]))
        if not rec or str(rec).startswith("ERR"):
            skipped.append((c["rid"], "미측정"))
            continue
        b, d, n = (int(x) for x in str(rec).split(":"))
        if n == 0:                       # 캘린더가 창 안에서 아무 날도 안 준 매물
            skipped.append((c["rid"], "캘린더 0일"))
            continue
        rows.append({**c, "b": b, "d": d, "n": n,
                     "comb": (b + d) / WINDOW_DAYS * 100,
                     "solo": b / WINDOW_DAYS * 100,
                     "alt": d / WINDOW_DAYS * 100})

    out = a.out or a.supply.replace("_supply.json", "_seg_rows.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)

    n_one = sum(1 for r in rows if r["seg_type"] == "원룸")
    print(json.dumps({
        "out": out, "rows": len(rows),
        "원룸": n_one, "멀티룸": len(rows) - n_one,
        "skipped": [{"rid": r, "why": w} for r, w in skipped],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
