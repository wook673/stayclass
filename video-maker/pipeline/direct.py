"""연출(direction) 관리 — DESIGN_MOTION.md의 direction.json 계약 구현

projects/<이름>/direction.json 이 있으면 로드하고, 없으면 style 프리셋으로
기본 연출을 자동 생성한다. 렌더러(motion/transitions/subtitle_ass/assemble)는
여기서 나온 dict만 보고 그린다.
"""
import json
from pathlib import Path

# 스타일 프리셋: direction.json이 없을 때 장면마다 적용할 기본값
PRESETS = {
    "docu":  {"zoom": "in",  "pan": "none",  "strength": 1.08,
              "transition": {"type": "fadeblack", "dur": 0.6},
              "subtitle": {"anim": "fadeup", "highlight": [], "position": "bottom"}},
    "vlog":  {"zoom": "none", "pan": "left", "strength": 1.12,
              "transition": {"type": "slideleft", "dur": 0.35},
              "subtitle": {"anim": "pop", "highlight": [], "position": "bottom"}},
    "info":  {"zoom": "out", "pan": "none", "strength": 1.10,
              "transition": {"type": "fade", "dur": 0.4},
              "subtitle": {"anim": "fadeup", "highlight": [], "position": "bottom"}},
    "brand": {"zoom": "in",  "pan": "none", "strength": 1.05,
              "transition": {"type": "circleopen", "dur": 0.7},
              "subtitle": {"anim": "fadeup", "highlight": [], "position": "bottom"}},
}

# 켄번스 팬 방향을 장면마다 번갈아 써서 단조로움을 줄인다
PAN_CYCLE = ["left", "right", "up", "down"]


def default_direction(scenes: list[dict], style: str = "docu") -> dict:
    p = PRESETS.get(style, PRESETS["docu"])
    out = {"style": style, "bgm": {"path": "", "volume": 0.12, "duck": True}, "scenes": []}
    for i, sc in enumerate(scenes):
        pan = p["pan"] if p["pan"] != "none" else PAN_CYCLE[i % len(PAN_CYCLE)]
        out["scenes"].append({
            "index": sc["index"],
            "media": {"type": "stock"},
            "motion": {"type": "kenburns",
                       "zoom": "in" if (p["zoom"] == "none") else p["zoom"],
                       "pan": pan, "strength": p["strength"]},
            "transition": dict(p["transition"]),
            "subtitle": {**p["subtitle"], "highlight": []},
            "overlays": [],
        })
    return out


def load(proj: Path, scenes: list[dict], style: str = "docu") -> dict:
    """direction.json 로드. 없거나 장면이 모자라면 기본연출로 채운다."""
    base = default_direction(scenes, style)
    f = proj / "direction.json"
    if not f.exists():
        return base
    user = json.loads(f.read_text(encoding="utf-8"))
    if "style" in user:
        base = default_direction(scenes, user["style"])
    if "bgm" in user:
        base["bgm"].update(user["bgm"])
    by_idx = {s["index"]: s for s in user.get("scenes", [])}
    for sc in base["scenes"]:
        ov = by_idx.get(sc["index"])
        if not ov:
            continue
        for key in ("media", "motion", "transition", "subtitle"):
            if key in ov:
                sc[key].update(ov[key])
        if "overlays" in ov:
            sc["overlays"] = ov["overlays"]
    return base


def scene_direction(direction: dict, index: int) -> dict:
    for sc in direction["scenes"]:
        if sc["index"] == index:
            return sc
    return direction["scenes"][min(index, len(direction["scenes"]) - 1)]
