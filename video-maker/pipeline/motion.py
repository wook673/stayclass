"""② 장면 소재 → 모션 입힌 클립 (build_clips의 연출 강화판)

- 영상 소재: 트림 + 해상도 통일 (모자라면 루프)
- 사진 소재: zoompan 켄번스(줌인/줌아웃 + 팬)로 살아있는 클립화
- xfade 겹침 보정: 장면 i(두 번째부터)는 "자기 길이 + 직전 전환 길이"만큼
  렌더해야 전환으로 겹쳐도 전체 길이(=음성 길이)가 유지된다.
"""
import subprocess
from pathlib import Path

from . import direct

PHOTO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def clamp_transition(scenes: list[dict], direction: dict) -> list[float]:
    """장면 i-1 → i 전환 길이 목록(len = n-1). 짧은 장면에선 자동 축소."""
    ts = []
    for i in range(1, len(scenes)):
        want = direct.scene_direction(direction, scenes[i]["index"])["transition"]["dur"]
        d_prev = scenes[i - 1]["end"] - scenes[i - 1]["start"]
        d_cur = scenes[i]["end"] - scenes[i]["start"]
        ts.append(round(max(0.15, min(want, d_prev * 0.5, d_cur * 0.5)), 2))
    return ts


def _kenburns_expr(motion: dict, dur: float, fps: int) -> str:
    """zoompan 필터 문자열. 떨림 방지를 위해 사전에 2배 업스케일 후 적용."""
    n = max(int(dur * fps), 1)
    s = max(1.01, min(float(motion.get("strength", 1.1)), 1.25))
    if motion.get("zoom") == "out":
        z = f"{s}-({s}-1)*on/{n}"
    else:
        z = f"1+({s}-1)*on/{n}"
    # 팬: 프레임 진행(on/n)에 따라 여백 안에서 이동
    pan = motion.get("pan", "none")
    cx, cy = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    if pan == "left":
        x, y = f"(iw-iw/zoom)*(1-on/{n})", cy
    elif pan == "right":
        x, y = f"(iw-iw/zoom)*on/{n}", cy
    elif pan == "up":
        x, y = cx, f"(ih-ih/zoom)*(1-on/{n})"
    elif pan == "down":
        x, y = cx, f"(ih-ih/zoom)*on/{n}"
    else:
        x, y = cx, cy
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:fps={fps}"


def run(scenes: list[dict], direction: dict, cfg: dict, work_dir: Path) -> list[dict]:
    w, h = cfg["resolution"].split("x")
    fps = cfg["fps"]
    trans = clamp_transition(scenes, direction)

    for i, sc in enumerate(scenes):
        dur = round(sc["end"] - sc["start"], 2)
        extra = trans[i - 1] if i > 0 else 0.0     # 앞 전환과 겹칠 여분
        render_dur = round(dur + extra, 2)
        out = work_dir / f"clip_{sc['index']}.mp4"
        d = direct.scene_direction(direction, sc["index"])
        media = sc.get("media_path")
        is_photo = bool(media) and Path(media).suffix.lower() in PHOTO_EXT

        if media and is_photo:
            kb = _kenburns_expr(d["motion"], render_dur, fps)
            vf = (f"scale={int(w)*2}:{int(h)*2}:force_original_aspect_ratio=increase,"
                  f"crop={int(w)*2}:{int(h)*2},{kb},scale={w}:{h}")
            cmd = ["ffmpeg", "-y", "-loop", "1", "-i", media,
                   "-t", str(render_dur), "-vf", vf,
                   "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
        elif media:
            cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", media,
                   "-t", str(render_dur),
                   "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                          f"crop={w}:{h},fps={fps}",
                   "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
        else:
            cmd = ["ffmpeg", "-y", "-f", "lavfi",
                   "-i", f"color=c=0x1a1a2e:s={w}x{h}:d={render_dur}:r={fps}",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
        subprocess.run(cmd, check=True, capture_output=True)
        sc["clip_path"] = str(out)
    return scenes
