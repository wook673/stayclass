"""① 녹음(mp3) → 타이밍 박힌 자막 segments

faster-whisper로 음성을 인식해 "문장 + 시작/끝 시간"을 뽑는다.
설치: pip install faster-whisper
"""
from pathlib import Path


def run(voice_path: str, cfg: dict) -> list[dict]:
    """voice.mp3 → [{text, start, end}, ...] 반환"""
    from faster_whisper import WhisperModel

    model = WhisperModel(cfg.get("whisper_model", "small"), compute_type="int8")
    segments, _ = model.transcribe(
        voice_path,
        language=cfg.get("whisper_language", "ko"),
        word_timestamps=False,
    )
    out = []
    for i, s in enumerate(segments):
        out.append({"index": i, "text": s.text.strip(),
                    "start": round(s.start, 2), "end": round(s.end, 2)})
    return out


# --- 아직 faster-whisper 미설치 상태에서 흐름 검증용 더미 ---
def run_stub(voice_path: str, cfg: dict) -> list[dict]:
    return [
        {"index": 0, "text": "안녕하세요. 오늘 주제를 소개합니다.", "start": 0.0, "end": 3.0},
        {"index": 1, "text": "첫 번째 핵심은 이것입니다.", "start": 3.0, "end": 6.0},
    ]
