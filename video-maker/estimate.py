"""대본 글자수 → 예상 영상 길이 계산

기준: 한국어 내레이션 분당 300자(초당 5자). 말 속도로 ±10% 차이.
사용법:
  python estimate.py travel-accident   # 해당 프로젝트 대본 분석
  python estimate.py --chars 500       # 500자일 때 예상 길이
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CHARS_PER_MIN = 300


def fmt(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}분 {s}초" if m else f"{s}초"


def estimate(n_chars: int) -> str:
    return fmt(n_chars / CHARS_PER_MIN * 60)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--chars" and sys.argv[2].isdigit():
        n = int(sys.argv[2])
        print(f"{n}자  →  예상 길이 약 {estimate(n)}")
    elif len(sys.argv) >= 2:
        script = ROOT / "projects" / sys.argv[1] / "script.txt"
        if not script.exists():
            raise SystemExit(f"[중단] '{sys.argv[1]}/script.txt' 없음.")
        text = script.read_text(encoding="utf-8")
        total = len(text)
        no_space = len(text.replace(" ", "").replace("\n", ""))
        print(f"공백 포함 글자수 : {total}자")
        print(f"공백 제외 글자수 : {no_space}자")
        print(f"예상 영상 길이   : 약 {estimate(no_space)} (공백 제외 기준)")
    else:
        raise SystemExit("사용법: python estimate.py <프로젝트이름>  또는  python estimate.py --chars 500")
