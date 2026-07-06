"""모션그래픽 오버레이 — HTML 템플릿을 프레임 단위로 캡처해 영상에 합성

각 템플릿은 window.seek(t)로 't초의 상태'를 결정적으로 그린다.
Playwright(헤드리스 크롬)로 t를 프레임마다 밀며 투명 PNG를 캡처하고,
FFmpeg overlay로 베이스 영상의 정확한 시각에 얹는다.

overlay 스펙(direction.json scenes[].overlays[]):
  {"type": "lowerthird", "title": "...", "sub": "...", "at": 0.0, "dur": 4.0}
  {"type": "countup", "to": 420, "suffix": "만원", "label": "...", "at": 0.3, "dur": 2.5}
  {"type": "titlecard", "title": "...", "sub": "...", "at": 0.0, "dur": 3.5}
at은 장면 시작 기준 상대 초. Playwright 미설치면 오버레이만 건너뛴다.
"""
import subprocess
import urllib.parse
from pathlib import Path

TEMPLATES = Path(__file__).parent / "templates"
KNOWN = {"lowerthird", "countup", "titlecard"}
OVERLAY_FPS = 30          # 오버레이 캡처 fps (베이스와 독립, 30이면 충분)


def available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def collect(scenes: list[dict], direction: dict) -> list[dict]:
    """장면 상대시간 → 절대시간으로 환산한 오버레이 목록."""
    from .. import direct
    jobs = []
    for sc in scenes:
        d = direct.scene_direction(direction, sc["index"])
        for ov in d.get("overlays", []):
            if ov.get("type") not in KNOWN:
                continue
            start = sc["start"] + float(ov.get("at", 0.0))
            dur = float(ov.get("dur", {"lowerthird": 4.0, "countup": 2.5,
                                       "titlecard": 3.5}[ov["type"]]))
            # 장면을 크게 벗어나지 않게 상한 (다음 장면 침범 1초까지 허용)
            dur = min(dur, sc["end"] - start + 1.0)
            if dur <= 0.2:
                continue
            jobs.append({**ov, "abs_start": round(start, 2), "dur": round(dur, 2)})
    return jobs


def _render_frames(page, job: dict, out_dir: Path) -> int:
    """한 오버레이의 투명 PNG 프레임들 생성. 반환: 프레임 수."""
    params = {k: v for k, v in job.items()
              if k not in ("type", "at", "abs_start")}
    url = (TEMPLATES / f"{job['type']}.html").as_uri() + "?" + \
        urllib.parse.urlencode(params, encoding="utf-8")
    page.goto(url)
    n = max(int(job["dur"] * OVERLAY_FPS), 2)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in range(n):
        page.evaluate(f"seek({f / OVERLAY_FPS})")
        page.screenshot(path=str(out_dir / f"f_{f:04d}.png"),
                        omit_background=True)
    return n


def apply_overlays(base: Path, scenes: list[dict], direction: dict,
                   cfg: dict, work_dir: Path) -> Path:
    """베이스 영상에 모든 오버레이 합성. 오버레이 없으면 base 그대로 반환."""
    jobs = collect(scenes, direction)
    if not jobs:
        return base
    if not available():
        print("   (안내) 오버레이가 있지만 Playwright 미설치 → 건너뜀")
        return base

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        for i, job in enumerate(jobs):
            _render_frames(page, job, work_dir / f"ov_{i}")
        browser.close()

    # FFmpeg 한 번에 전부 합성: 각 PNG시퀀스를 절대시각으로 밀어서 overlay
    out = work_dir / "base_overlaid.mp4"
    inputs = ["-i", str(base)]
    parts = []
    prev = "0:v"
    for i, job in enumerate(jobs):
        inputs += ["-framerate", str(OVERLAY_FPS),
                   "-i", str(work_dir / f"ov_{i}" / "f_%04d.png")]
        st = job["abs_start"]
        parts.append(f"[{i+1}:v]setpts=PTS-STARTPTS+{st}/TB[o{i}]")
        parts.append(f"[{prev}][o{i}]overlay=0:0:eof_action=pass[v{i}]")
        prev = f"v{i}"
    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex", ";".join(parts),
           "-map", f"[{prev}]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(cfg["fps"]),
           str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out
