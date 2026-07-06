"""③ 장면 클립들 → xfade 전환 체인 → 무음 베이스 영상

전환은 문장 경계 직전 t초 동안 일어나고(offset = 경계 - t),
전환이 끝나는 순간 새 문장 자막이 시작되도록 타이밍을 맞춘다.
클립 여분(motion.py의 extra) 덕에 총 길이 = 음성 길이가 유지된다.
"""
import subprocess
from pathlib import Path

from . import direct, motion

# ffmpeg xfade가 지원하는 전환 이름만 통과, 그 외엔 fade로 폴백
XFADE_OK = {"fade", "fadeblack", "fadewhite", "slideleft", "slideright",
            "slideup", "slidedown", "wipeleft", "wiperight", "circleopen",
            "circleclose", "zoomin", "dissolve", "pixelize", "radial"}


def build_base(scenes: list[dict], direction: dict, cfg: dict,
               work_dir: Path) -> Path:
    out = work_dir / "base.mp4"
    if len(scenes) == 1:
        Path(scenes[0]["clip_path"]).replace(out)
        return out

    trans = motion.clamp_transition(scenes, direction)
    inputs = []
    for sc in scenes:
        inputs += ["-i", sc["clip_path"]]

    # 타임베이스 통일(입력마다 settb) 후 xfade 체인
    parts = [f"[{i}:v]settb=AVTB[s{i}]" for i in range(len(scenes))]
    prev = "s0"
    boundary = 0.0            # 장면 경계의 절대 시각
    for i in range(1, len(scenes)):
        boundary += scenes[i - 1]["end"] - scenes[i - 1]["start"]
        t = trans[i - 1]
        name = direct.scene_direction(direction, scenes[i]["index"])["transition"]["type"]
        if name not in XFADE_OK:
            name = "fade"
        offset = round(boundary - t, 3)
        label = f"x{i}"
        parts.append(f"[{prev}][s{i}]xfade=transition={name}:"
                     f"duration={t}:offset={offset}[{label}]")
        prev = label

    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex", ";".join(parts),
           "-map", f"[{prev}]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(cfg["fps"]),
           str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out
