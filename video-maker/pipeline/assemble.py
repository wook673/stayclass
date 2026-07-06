"""⑤ 클립들 + 자막 + 음성(+배경음악) → 최종 MP4

run()          : 레거시 경로 — concat + SRT burn (연출 없음)
run_directed() : 연출 경로 — xfade 베이스 + ASS 애니메이션 자막 + BGM 덕킹
"""
import subprocess
from pathlib import Path

from . import subtitle_ass


def _ts(sec: float) -> str:
    h = int(sec // 3600); m = int(sec % 3600 // 60)
    s = int(sec % 60); ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(scenes: list[dict], path: Path):
    lines = []
    for i, sc in enumerate(scenes, 1):
        lines += [str(i), f"{_ts(sc['start'])} --> {_ts(sc['end'])}", sc["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_directed(base_video: Path, scenes: list[dict], direction: dict,
                 cfg: dict, voice_path: str, work_dir: Path, out_path: Path):
    """연출 경로: xfade 베이스 위에 ASS 자막 burn + 음성(+BGM 덕킹)."""
    ass = work_dir / "subtitle.ass"
    subtitle_ass.write_ass(scenes, direction, cfg, ass)
    ass_f = str(ass).replace("\\", "/").replace(":", "\\:")

    bgm = direction.get("bgm", {})
    inputs = ["-i", str(base_video), "-i", voice_path]
    if bgm.get("path"):
        inputs += ["-stream_loop", "-1", "-i", bgm["path"]]
        vol = bgm.get("volume", 0.12)
        if bgm.get("duck", True):
            # 내레이션이 나올 때 BGM을 자동으로 낮춘다(사이드체인 컴프레서)
            afilter = (f"[2:a]volume={vol}[b];"
                       f"[b][1:a]sidechaincompress=threshold=0.03:ratio=8:"
                       f"attack=50:release=400[bd];"
                       f"[1:a][bd]amix=inputs=2:duration=first:normalize=0[aout]")
        else:
            afilter = (f"[2:a]volume={vol}[b];"
                       f"[1:a][b]amix=inputs=2:duration=first:normalize=0[aout]")
        filt = ["-filter_complex", f"[0:v]subtitles='{ass_f}'[vout];{afilter}",
                "-map", "[vout]", "-map", "[aout]"]
    else:
        filt = ["-vf", f"subtitles='{ass_f}'",
                "-map", "0:v", "-map", "1:a"]

    cmd = ["ffmpeg", "-y", *inputs, *filt,
           "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def run(scenes: list[dict], cfg: dict, voice_path: str, work_dir: Path, out_path: Path):
    # 1) concat 목록
    listfile = work_dir / "concat.txt"
    listfile.write_text(
        "\n".join(f"file '{Path(sc['clip_path']).resolve().as_posix()}'" for sc in scenes),
        encoding="utf-8")
    silent = work_dir / "video_silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(listfile), "-c", "copy", str(silent)], check=True)

    # 2) 자막 SRT
    srt = work_dir / "subtitle.srt"
    write_srt(scenes, srt)
    srt_f = str(srt).replace("\\", "/").replace(":", "\\:")
    style = (f"FontName={cfg['font_name']},FontSize={cfg['font_size']},"
             "PrimaryColour=&H00FFFFFF,Outline=2,Shadow=1")

    # 3) 자막 burn + 음성/배경음악
    inputs = ["-i", str(silent), "-i", voice_path]
    if cfg.get("bgm_path"):
        inputs += ["-i", cfg["bgm_path"]]
        amix = (f"[1:a]volume=1.0[v];[2:a]volume={cfg['bgm_volume']}[b];"
                "[v][b]amix=inputs=2:duration=first[aout]")
        amap = ["-map", "0:v", "-map", "[aout]"]
        filt = ["-filter_complex",
                f"[0:v]subtitles='{srt_f}':force_style='{style}'[vout];{amix}",
                "-map", "[vout]", "-map", "[aout]"]
    else:
        filt = ["-vf", f"subtitles='{srt_f}':force_style='{style}'"]
        amap = ["-map", "0:v", "-map", "1:a"]

    cmd = ["ffmpeg", "-y", *inputs, *filt, *amap,
           "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", str(out_path)]
    subprocess.run(cmd, check=True)
    return out_path
