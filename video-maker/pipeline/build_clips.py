"""④ 장면 소재 → 음성 타이밍 길이에 맞춘 클립

각 장면의 길이 = end - start. 그 길이에 맞춰 소재를 트림/루프하고
해상도를 통일한다. 소재가 없으면 단색 배경으로 대체.
"""
import subprocess
from pathlib import Path


def run(scenes: list[dict], cfg: dict, work_dir: Path) -> list[dict]:
    w, h = cfg["resolution"].split("x")
    fps = cfg["fps"]
    for sc in scenes:
        dur = round(sc["end"] - sc["start"], 2)
        out = work_dir / f"clip_{sc['index']}.mp4"
        if sc.get("media_path"):
            # 영상 소재: 길이에 맞춰 트림 + 해상도 통일 (모자라면 루프)
            cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", sc["media_path"],
                   "-t", str(dur),
                   "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                          f"crop={w}:{h},fps={fps}",
                   "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
        else:
            # 소재 없음: 단색 배경
            cmd = ["ffmpeg", "-y", "-f", "lavfi",
                   "-i", f"color=c=0x222222:s={w}x{h}:d={dur}:r={fps}",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
        subprocess.run(cmd, check=True, capture_output=True)
        sc["clip_path"] = str(out)
    return scenes
