"""대본(=TTS에 넣은 텍스트) 경계 타이밍 → 자막 장면 (오타 0%)

TTS가 돌려준 경계 이벤트의 text는 입력 텍스트(=대본)와 동일하므로,
받아쓰기 오타가 없다. 각 경계(보통 문장)를 읽기 좋은 길이로 더 쪼개고,
경계의 [start,end]를 글자 수 비례로 나눠 각 자막의 시작 시각을 정한다.

장면들은 0부터 음성 끝까지 '빈틈없이 연속'되도록 타일링한다
(각 자막의 끝 = 다음 자막의 시작). 영상·음성 길이를 일치시키기 위함.
"""
import re

MAXLEN = 32  # 자막 한 줄 최대 길이(글자). 넘으면 쉼표 기준으로 분할.

_NORM = re.compile(r"[0-9A-Za-z가-힣]")


def _norm(s: str) -> str:
    return "".join(_NORM.findall(s))


def split_units(text: str) -> list[str]:
    """텍스트를 자막 단위(짧은 문장)로 분할."""
    text = re.sub(r"^#[^\n]*$", "", text, flags=re.M)        # 주석줄 제거
    text = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    units: list[str] = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(s) <= MAXLEN:
            units.append(s)
            continue
        parts = [p for p in re.split(r"(?<=[,·])\s*", s) if p]   # 길면 쉼표 기준
        buf = ""
        for p in parts:
            cand = f"{buf} {p}".strip() if buf else p
            if len(cand) <= MAXLEN:
                buf = cand
            else:
                if buf:
                    units.append(buf)
                buf = p
        if buf:
            units.append(buf)
    return units


def from_boundaries(bounds: list[dict]) -> list[dict]:
    """경계 이벤트 리스트 → 연속 타일링된 자막 장면 리스트."""
    # 1) 각 경계 텍스트를 자막 단위로 쪼개고, 단위별 '시작 시각' 계산
    flat: list[tuple[str, float]] = []
    for b in bounds:
        units = split_units(b["text"])
        if not units:
            continue
        total = sum(len(_norm(u)) for u in units) or 1
        span = max(b["end"] - b["start"], 0.01)
        acc = 0
        for u in units:
            flat.append((u, b["start"] + span * acc / total))
            acc += len(_norm(u))
    if not flat:
        return []

    audio_end = max(b["end"] for b in bounds)

    # 2) 연속 타일링: 자막[i].끝 = 자막[i+1].시작 (마지막은 음성 끝)
    scenes: list[dict] = []
    for i, (u, st) in enumerate(flat):
        start = 0.0 if i == 0 else st
        end = flat[i + 1][1] if i + 1 < len(flat) else audio_end
        if end <= start:
            end = start + 0.4
        scenes.append({"index": i, "text": u,
                       "start": round(start, 2), "end": round(end, 2),
                       "keywords": None, "media_path": None, "clip_path": None})
    return scenes
