"""② 자막 segments → 장면(scene) + 검색 키워드

각 자막 문장을 하나의 장면으로 보고, 문장에서 명사 위주 키워드를 뽑아
스톡 검색어로 쓴다. (지금은 간단한 규칙기반; 나중에 형태소 분석/LLM으로 교체 가능)
"""
import re

# 검색어로 쓸모없는 흔한 단어 제거용
STOP = {"이것", "저것", "그것", "오늘", "정말", "그리고", "하지만", "그래서",
        "입니다", "습니다", "합니다", "소개", "핵심", "번째", "안녕하세요"}


def extract_keywords(text: str, k: int = 2) -> list[str]:
    # 한글 2글자 이상 단어 추출 → 불용어 제거 → 상위 k개
    words = re.findall(r"[가-힣]{2,}", text)
    words = [w for w in words if w not in STOP]
    return words[:k] if words else ["nature"]


def run(segments: list[dict], cfg: dict) -> list[dict]:
    scenes = []
    for s in segments:
        scenes.append({
            **s,
            "keywords": extract_keywords(s["text"]),
            "media_path": None,
            "clip_path": None,
        })
    return scenes


def add_keywords(scenes: list[dict], cfg: dict) -> list[dict]:
    """이미 만들어진 장면(대본 자막 기반)에 키워드만 채운다."""
    for sc in scenes:
        if not sc.get("keywords"):
            sc["keywords"] = extract_keywords(sc["text"])
    return scenes
