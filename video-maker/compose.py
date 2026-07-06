"""
최소 동작 버전: 이미지 + 음성 + 자막(SRT)  →  자막이 새겨진 MP4
사용법:  python compose.py
나중에 여기에 Pexels 자동검색 / Whisper 자동자막을 모듈로 붙입니다.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

photo = ASSETS / "photo1.png"
voice = ASSETS / "voice.mp3"
srt = ASSETS / "subtitle.srt"
result = OUT / "result.mp4"

# FFmpeg는 자막 필터 경로에서 콜론/역슬래시를 이스케이프해야 함 (윈도우 주의점)
srt_for_filter = str(srt).replace("\\", "/").replace(":", "\\:")

cmd = [
    "ffmpeg", "-y",
    "-loop", "1", "-i", str(photo),   # 사진을 영상 길이만큼 반복
    "-i", str(voice),                  # 음성
    "-vf", (
        f"subtitles='{srt_for_filter}':"
        "force_style='FontName=Malgun Gothic,FontSize=28,"
        "PrimaryColour=&H00FFFFFF,Outline=2,Shadow=1'"
    ),
    "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "192k",
    "-shortest",                       # 음성 길이에 영상 맞춤
    str(result),
]

print("합성 시작...")
subprocess.run(cmd, check=True)
print(f"완료 → {result}")
