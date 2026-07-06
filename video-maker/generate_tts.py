"""대본 → 무료 TTS 음성 + 단어별 타이밍 (프로젝트 기반)

projects/<이름>/script.txt 를 읽어 같은 폴더에:
  - voice.mp3        : TTS 음성
  - voice.words.json : 단어별 [{w,start,end}] 타이밍 (자막 정확 정렬용)
을 만든다. 본인 녹음을 쓰면 이 단계는 건너뛴다.

사용법:
  python generate_tts.py daniel-intro            기본 여성 목소리
  python generate_tts.py daniel-intro InJoon     남성 목소리
목소리: SunHi(여), InJoon(남)
"""
import json
import sys
from pathlib import Path

import edge_tts

ROOT = Path(__file__).parent
VOICES = {"SunHi": "ko-KR-SunHiNeural", "InJoon": "ko-KR-InJoonNeural"}


def main():
    if len(sys.argv) < 2:
        raise SystemExit("사용법: python generate_tts.py <프로젝트이름> [SunHi|InJoon]")
    proj = ROOT / "projects" / sys.argv[1]
    if not proj.is_dir():
        raise SystemExit(f"[중단] 프로젝트 '{sys.argv[1]}' 없음.")
    pick = sys.argv[2] if len(sys.argv) > 2 else "SunHi"
    voice = VOICES.get(pick, VOICES["SunHi"])

    text = (proj / "script.txt").read_text(encoding="utf-8").strip()
    out = proj / "voice.mp3"
    words_path = proj / "voice.words.json"
    print(f"목소리: {voice}  →  {out}")
    print("TTS 생성 중...")

    # 경계 이벤트(문장/단어)의 텍스트+타이밍 수집. 한국어 음성은 보통 SentenceBoundary.
    bounds = []
    with open(out, "wb") as f:
        for chunk in edge_tts.Communicate(text, voice).stream_sync():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                start = chunk["offset"] / 1e7
                end = (chunk["offset"] + chunk["duration"]) / 1e7
                bounds.append({"text": chunk["text"],
                               "start": round(start, 3), "end": round(end, 3)})

    words_path.write_text(json.dumps(bounds, ensure_ascii=False), encoding="utf-8")
    print(f"완료 (경계 {len(bounds)}개 타이밍 저장)")


if __name__ == "__main__":
    main()
