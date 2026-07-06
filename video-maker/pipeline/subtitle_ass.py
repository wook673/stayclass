"""④ 장면 + 연출 → ASS 자막 (애니메이션 내장)

SRT와 달리 ASS는 자막 자체에 연출 태그를 넣을 수 있다:
- fadeup: 페이드인하며 아래→위로 살짝 떠오름
- pop:    통통 튀듯 확대→원복
- 하이라이트: 지정 단어만 골드색
FFmpeg(libass)가 그대로 그려주므로 추가 설치가 없다.
"""
from pathlib import Path

from . import direct

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bottom,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,120,120,90,1
Style: Center,{font},{title_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,5,120,120,90,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

HIGHLIGHT = "&H00D7FF&"   # 골드(BGR). RGB FFD700


def _ts(sec: float) -> str:
    h = int(sec // 3600); m = int(sec % 3600 // 60)
    s = int(sec % 60); cs = int(round((sec - int(sec)) * 100))
    if cs == 100:
        s, cs = s + 1, 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _anim_tag(anim: str, position: str) -> str:
    if position == "center":
        base_y, lift = 540, 20
    else:
        base_y, lift = 970, 25
    if anim == "pop":
        return (r"{\fad(80,80)\fscx70\fscy70"
                r"\t(0,140,\fscx108\fscy108)\t(140,260,\fscx100\fscy100)}")
    if anim == "fadeup":
        return (rf"{{\fad(160,120)\move(960,{base_y + lift},960,{base_y},0,200)}}")
    return r"{\fad(100,80)}"          # none/기타: 은은한 페이드만


def _highlight(text: str, words: list[str]) -> str:
    for w in words or []:
        if w and w in text:
            text = text.replace(
                w, rf"{{\1c{HIGHLIGHT}}}{w}{{\1c&HFFFFFF&}}", 1)
    return text


def write_ass(scenes: list[dict], direction: dict, cfg: dict, path: Path):
    size = max(int(cfg.get("font_size", 42) * 1.5), 48)   # 1080p 기준 보정
    lines = [HEADER.format(font=cfg.get("font_name", "Malgun Gothic"),
                           size=size, title_size=int(size * 1.3))]
    for sc in scenes:
        d = direct.scene_direction(direction, sc["index"])["subtitle"]
        style = "Center" if d.get("position") == "center" else "Bottom"
        tag = _anim_tag(d.get("anim", "fadeup"), d.get("position", "bottom"))
        text = _highlight(sc["text"], d.get("highlight"))
        lines.append(f"Dialogue: 0,{_ts(sc['start'])},{_ts(sc['end'])},"
                     f"{style},,0,0,0,,{tag}{text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path
