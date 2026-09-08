# -*- coding: utf-8 -*-
"""supply_scan.py — 지정 시 전역 공급 스캔 → 그리디 500m 클러스터 → JSON 덤프.

사용: python routine/supply_scan.py "용인시" routine/out/용인시_supply.json
바운딩박스는 Nominatim, 실패 시 --bbox s,w,n,e 로 수동 지정.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "market-analyzer"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import m33          # noqa: E402
import scan         # noqa: E402


def main():
    region = sys.argv[1]
    out_path = sys.argv[2]
    bbox = None
    if "--bbox" in sys.argv:
        s, w, n, e = (float(x) for x in
                      sys.argv[sys.argv.index("--bbox") + 1].split(","))
        bbox = {"south": s, "west": w, "north": n, "east": e,
                "lat": (s + n) / 2, "lon": (w + e) / 2, "display": region}
    if bbox is None:
        bbox = scan.geocode_bbox(region)
    if bbox is None:
        print("BBOX_FAIL", flush=True)
        sys.exit(3)
    print(f"bbox {bbox['south']:.4f},{bbox['west']:.4f} ~ "
          f"{bbox['north']:.4f},{bbox['east']:.4f}", flush=True)

    # 원본 타일 수집 결과는 캐시해 재클러스터링 때 재요청하지 않는다.
    raw_path = out_path.replace(".json", "_raw.json")
    if "--cache" in sys.argv and os.path.exists(raw_path):
        cached = json.load(open(raw_path, encoding="utf-8"))
        got = {"items": {int(k): v for k, v in cached["items"].items()},
               "n_tiles": cached["n_tiles"], "n_raw": cached["n_raw"]}
        print("cache hit", raw_path, flush=True)
    else:
        got = scan.collect_tiles(bbox)
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump({"items": got["items"], "n_tiles": got["n_tiles"],
                       "n_raw": got["n_raw"]}, f, ensure_ascii=False)
    items = got["items"]
    print(f"tiles={got['n_tiles']} raw={got['n_raw']}", flush=True)

    # 행정구역 필터 — 바운딩박스가 인접 시를 물고 오므로 province로 잘라낸다.
    prov_filter = None
    if "--province" in sys.argv:
        prov_filter = sys.argv[sys.argv.index("--province") + 1]
        items = {k: v for k, v in items.items()
                 if prov_filter in (v.get("province") or "")}
        print(f"province={prov_filter} -> {len(items)}", flush=True)

    # 제외 집계(상시 지침) — 멀티룸은 세기만 하지 말고 세트로 담는다.
    # 원룸/멀티룸 구분 보고가 상시 지침이므로(2026-08-30), 유형(오피스텔)이 같고
    # 방 수만 다른 매물은 버리지 않고 payload["multi"] 로 넘긴다.
    # 고시원·모텔 등 유형 제외군은 여기 넣지 않는다 — 유형을 고정해야 비교가 선다.
    n_type_excl = n_notroom_excl = 0
    multi = []
    for it in items.values():
        ptype = (it.get("propertyType") or "").strip()
        name = it.get("roomName") or ""
        if any(x in ptype for x in m33._EXCLUDE_TYPES) or any(
                x in name for x in m33._EXCLUDE_TYPES):
            n_type_excl += 1
        elif ptype != m33.KEEP_TYPE:
            n_type_excl += 1
        elif m33._MULTIROOM_RE.search(name) or (it.get("roomCnt") or 1) > 1:
            n_notroom_excl += 1
            ilat, ilon = it.get("lat"), it.get("lng")
            if ilat is None or ilon is None:
                continue
            multi.append({
                "rid": it.get("rid"), "name": name, "type": ptype,
                "weekly": m33._weekly(it), "pyeong": it.get("pyeongSize"),
                "roomCnt": it.get("roomCnt"),
                "lat": float(ilat), "lon": float(ilon),
                "addr": it.get("addrLot"), "town": it.get("town"),
                "province": it.get("province"),
            })

    rooms = scan.filter_supply(items)
    print(f"kept={len(rooms)} type_excl={n_type_excl} "
          f"notroom_excl={n_notroom_excl} (멀티룸 {len(multi)}실 보관)", flush=True)

    clusters = scan.greedy_clusters(rooms, radius_m=500, min_size=3)
    print(f"clusters={len(clusters)}", flush=True)

    payload = {
        "region": region, "bbox": bbox,
        "n_tiles": got["n_tiles"], "n_raw": got["n_raw"],
        "n_type_excluded": n_type_excl, "n_notroom_excluded": n_notroom_excl,
        "n_kept": len(rooms),
        "multi": multi,
        "clusters": [{
            "center": c["center"], "n": c["n"],
            "weekly_median": c["weekly_median"], "weekly_n": c["weekly_n"],
            "towns": dict(c["towns"]), "province": c["province"],
            "complexes": sorted(c["complexes"]),
            "rooms": c["rooms"],
        } for c in clusters[:14]],
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    for i, c in enumerate(clusters[:10]):
        towns = ",".join(list(c["towns"])[:2])
        print(f"#{i+1} n={c['n']} {towns} wk={c['weekly_median']}", flush=True)
    print("DONE", out_path, flush=True)


if __name__ == "__main__":
    main()
