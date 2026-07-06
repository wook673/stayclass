"""핵심 엔진 — CLI(make_video.py)와 웹 UI(app.py)가 공유.

프로젝트 관리 + 대본/음성/추정 + 영상 제작 파이프라인을 함수로 노출한다.
진행 상황은 on_progress(step:int, label:str) 콜백으로 알린다.
"""
import json
import re
from pathlib import Path

from pipeline import (transcribe, segment, fetch_media, assemble, subtitle,
                      direct, motion, transitions, mograph)

ROOT = Path(__file__).parent
PROJECTS = ROOT / "projects"
PROJECTS.mkdir(exist_ok=True)

AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus"}
TTS_VOICES = {"SunHi": "ko-KR-SunHiNeural", "InJoon": "ko-KR-InJoonNeural"}
CHARS_PER_MIN = 300


# ---------- 설정 ----------
def load_cfg() -> dict:
    p = ROOT / "config.json"
    if not p.exists():
        p = ROOT / "config.example.json"
    return json.loads(p.read_text(encoding="utf-8"))


# ---------- 프로젝트 ----------
def list_project_names() -> list[str]:
    return sorted(d.name for d in PROJECTS.iterdir() if d.is_dir())


def project_dir(name: str) -> Path:
    return PROJECTS / name


def create_project(name: str) -> Path:
    name = name.strip()
    if not name or not re.match(r"^[\w가-힣 \-]+$", name):
        raise ValueError("이름은 한글·영문·숫자·하이픈만 가능합니다.")
    proj = PROJECTS / name
    if proj.exists():
        raise ValueError(f"'{name}'는 이미 있습니다.")
    proj.mkdir(parents=True)
    (proj / "script.txt").write_text("", encoding="utf-8")
    return proj


def get_script(name: str) -> str:
    f = PROJECTS / name / "script.txt"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def save_script(name: str, text: str):
    (PROJECTS / name / "script.txt").write_text(text, encoding="utf-8")


STYLES = ["docu", "vlog", "info", "brand"]
BGM_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}
DEFAULT_SETTINGS = {"style": "docu", "highlights": [], "topic": "", "bgm_track": ""}


def get_settings(name: str) -> dict:
    f = PROJECTS / name / "settings.json"
    s = dict(DEFAULT_SETTINGS)
    if f.exists():
        s.update(json.loads(f.read_text(encoding="utf-8")))
    return s


def save_settings(name: str, data: dict) -> dict:
    s = get_settings(name)
    if "style" in data and data["style"] in STYLES:
        s["style"] = data["style"]
    if "highlights" in data:
        s["highlights"] = [w.strip() for w in data["highlights"] if w.strip()][:30]
    if "topic" in data:
        s["topic"] = str(data["topic"])[:200]
    if "bgm_track" in data:
        t = str(data["bgm_track"])
        s["bgm_track"] = t if (t == "" or (MUSIC_DIR / t).exists()) else s.get("bgm_track", "")
    (PROJECTS / name / "settings.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    return s


MUSIC_DIR = ROOT / "music"          # 공용 BGM 라이브러리 (한 번 넣으면 전 프로젝트에서 선택)
MUSIC_DIR.mkdir(exist_ok=True)


def list_music() -> list[str]:
    """공용 라이브러리의 음악 파일 이름 목록."""
    return sorted(p.name for p in MUSIC_DIR.iterdir()
                  if p.suffix.lower() in BGM_EXT)


def find_bgm(proj: Path):
    """프로젝트의 배경음악 파일(bgm.*)을 찾는다. 없으면 None."""
    for p in proj.glob("bgm.*"):
        if p.suffix.lower() in BGM_EXT:
            return p
    return None


def resolve_bgm(name: str):
    """실제 사용할 BGM 경로 결정. 우선순위: 프로젝트 업로드 > 라이브러리 선택 > 없음."""
    proj = PROJECTS / name
    up = find_bgm(proj)
    if up:
        return up
    track = get_settings(name).get("bgm_track", "")
    if track:
        p = MUSIC_DIR / track
        if p.exists():
            return p
    return None


def save_bgm(name: str, filename: str, data: bytes):
    proj = PROJECTS / name
    ext = Path(filename).suffix.lower()
    if ext not in BGM_EXT:
        raise ValueError(f"지원하지 않는 음악 형식입니다. ({', '.join(sorted(BGM_EXT))})")
    old = find_bgm(proj)
    if old:
        old.unlink()
    dest = proj / f"bgm{ext}"
    dest.write_bytes(data)
    return dest


def remove_bgm(name: str):
    old = find_bgm(PROJECTS / name)
    if old:
        old.unlink()


def find_voice(proj: Path):
    """프로젝트 폴더에서 음성 파일(이름 자유)을 찾는다. 여러개면 최신. 없으면 None."""
    cands = [p for p in proj.iterdir() if p.suffix.lower() in AUDIO_EXT]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def project_status(name: str) -> dict:
    proj = PROJECTS / name
    voice = find_voice(proj)
    bgm = find_bgm(proj)
    return {
        "name": name,
        "has_voice": voice is not None,
        "voice_name": voice.name if voice else None,
        "has_video": (proj / "final.mp4").exists(),
        "chars": count_chars(get_script(name)),
        "bgm_name": bgm.name if bgm else None,
        "bgm_resolved": (resolve_bgm(name).name if resolve_bgm(name) else None),
        "music_library": list_music(),
        "has_direction": (proj / "direction.json").exists(),
        "mograph_ready": mograph.available(),
        "settings": get_settings(name),
    }


# ---------- 추정 ----------
def count_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", re.sub(r"^#[^\n]*$", "", text, flags=re.M)))


def estimate_label(n_chars: int) -> str:
    sec = round(n_chars / CHARS_PER_MIN * 60)
    m, s = divmod(sec, 60)
    return f"{m}분 {s}초" if m else f"{s}초"


# ---------- 대본 자동 생성 (Claude Code CLI = Max 구독 포함, 추가비용 0원) ----------
def generate_script(name: str, topic: str, target_chars: int = 300) -> str:
    """주제 → Claude CLI 헤드리스 호출 → script.txt 저장. 반환: 대본 텍스트."""
    import shutil
    import subprocess
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("주제를 먼저 입력하세요.")
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("Claude Code CLI(claude)를 찾을 수 없습니다. "
                           "0번 카드의 '요청문 복사' 방식으로 진행하세요.")
    prompt = (
        "당신은 유튜브 롱폼 내레이션 대본 작가입니다. 아래 조건으로 대본을 쓰세요.\n"
        f"주제: {topic}\n"
        f"분량: 공백 포함 {target_chars}자 내외 (한국어)\n"
        "조건: 문장 하나가 자막 한 줄이 되므로 문장은 짧고 리듬감 있게. "
        "첫 문장은 시선을 잡는 훅. 기승전결 후 마무리 멘트 한 줄. "
        "숫자는 '92%', '420만 원'처럼 아라비아 숫자 표기. "
        "TTS가 읽으므로 이모지·특수기호 금지.\n"
        "출력: 대본 본문만. 제목·설명·마크다운·따옴표 없이 순수 텍스트로만."
    )
    # 실행 환경 정리:
    # - CLAUDE*  : 중첩 세션 가드 회피
    # - ANTHROPIC*: PC에 API 키가 있으면 CLI가 Max 구독 대신 그 키(크레딧 과금)를
    #   우선 사용해 "Credit balance is too low"로 실패한다 → 걷어내서 구독 로그인 사용
    import os
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "ANTHROPIC"))}
    r = subprocess.run([exe, "-p", prompt, "--output-format", "text"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300,
                       stdin=subprocess.DEVNULL, env=env,
                       cwd=str(PROJECTS / name))
    text = (r.stdout or "").strip()
    if r.returncode != 0 or not text:
        # 진단 로그를 남겨 원인 추적을 쉽게
        dbg = PROJECTS / name / "gen_debug.log"
        dbg.write_text(f"rc={r.returncode}\n--- stderr ---\n{r.stderr}\n"
                       f"--- stdout ---\n{r.stdout}", encoding="utf-8")
        detail = (r.stderr or "").strip()[:300] or f"빈 응답 (rc={r.returncode})"
        raise RuntimeError(f"대본 생성 실패: {detail}")
    # 혹시 모를 코드펜스/머리말 제거
    text = re.sub(r"^```[^\n]*\n|\n```$", "", text).strip()
    save_script(name, text)
    save_settings(name, {"topic": topic})
    return text


# ---------- TTS ----------
def generate_tts(name: str, voice_key: str = "InJoon", on_progress=None):
    import edge_tts
    proj = PROJECTS / name
    voice = TTS_VOICES.get(voice_key, TTS_VOICES["InJoon"])
    text = (proj / "script.txt").read_text(encoding="utf-8").strip()
    if not count_chars(text):
        raise ValueError("대본이 비어 있습니다. 먼저 대본을 작성하세요.")
    if on_progress:
        on_progress(0, f"TTS 음성 생성 중 ({voice_key})...")

    out = proj / "voice.mp3"
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
    (proj / "voice.words.json").write_text(json.dumps(bounds, ensure_ascii=False), encoding="utf-8")
    return out


def save_recording(name: str, filename: str, data: bytes):
    """업로드된 녹음 파일을 프로젝트 폴더에 저장. 반환: 저장 경로."""
    proj = PROJECTS / name
    ext = Path(filename).suffix.lower()
    if ext not in AUDIO_EXT:
        raise ValueError(f"지원하지 않는 형식입니다. ({', '.join(sorted(AUDIO_EXT))})")
    # 녹음을 쓰면 TTS 자막모드를 끄기 위해 기존 voice.mp3/words를 치움
    for stale in ("voice.mp3", "voice.words.json"):
        sp = proj / stale
        if sp.exists():
            sp.unlink()
    dest = proj / f"recording{ext}"
    dest.write_bytes(data)
    return dest


# ---------- 파이프라인 ----------
STEP_LABELS = {
    1: "자막 만들기",
    2: "장면 분할·키워드",
    3: "스톡 영상 다운로드",
    4: "장면 클립 생성",
    5: "자막·음성 합성",
}


def run_pipeline(name: str, on_progress=None, start: int = 1):
    """영상 제작. 실패 시 RuntimeError(한국어 메시지). 성공 시 final.mp4 경로 반환."""
    def report(step, label):
        if on_progress:
            on_progress(step, label)

    proj = PROJECTS / name
    if not proj.is_dir():
        raise RuntimeError(f"프로젝트 '{name}'가 없습니다.")
    work = proj / "work"; work.mkdir(exist_ok=True)
    assets = proj / "assets"; assets.mkdir(exist_ok=True)
    state_file = work / "state.json"
    out_path = proj / "final.mp4"

    cfg = load_cfg()
    voice = find_voice(proj)
    if voice is None:
        raise RuntimeError("음성이 없습니다. TTS로 만들거나 녹음 파일을 올려주세요.")
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}

    def save():
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    words_file = proj / "voice.words.json"
    use_script_sub = words_file.exists() and voice.name == "voice.mp3"

    if start <= 1:
        report(1, STEP_LABELS[1])
        if use_script_sub:
            bounds = json.loads(words_file.read_text(encoding="utf-8"))
            state["scenes"] = subtitle.from_boundaries(bounds)
            state["segments"] = None
        else:
            segs = transcribe.run(str(voice), cfg)
            if not segs:
                raise RuntimeError("음성에서 인식된 말이 없습니다. 무음/잡음이 아닌지 확인하세요.")
            state["segments"] = segs
        save()

    if start <= 2:
        report(2, STEP_LABELS[2])
        if state.get("scenes"):
            segment.add_keywords(state["scenes"], cfg)
        else:
            state["scenes"] = segment.run(state["segments"], cfg)
        save()

    if start <= 3:
        report(3, STEP_LABELS[3])
        state["scenes"] = fetch_media.run(state["scenes"], cfg, assets); save()

    # 연출 로드: 프리셋(style) ← settings.json ← direction.json(최우선) 순으로 겹침
    settings = get_settings(name)
    direction = direct.load(proj, state["scenes"], settings.get("style", "docu"))

    # UI에서 입력한 강조 단어를, 그 단어가 나오는 장면 자막에 자동 배정
    for sc_d in direction["scenes"]:
        sc = next((s for s in state["scenes"] if s["index"] == sc_d["index"]), None)
        if not sc:
            continue
        for w in settings.get("highlights", []):
            if w in sc["text"] and w not in sc_d["subtitle"].get("highlight", []):
                sc_d["subtitle"].setdefault("highlight", []).append(w)

    # 배경음악: direction.json 지정 > 프로젝트 업로드 > 라이브러리 선택 순
    bgm = resolve_bgm(name)
    if bgm and not direction["bgm"].get("path"):
        direction["bgm"]["path"] = str(bgm)

    if start <= 4:
        report(4, STEP_LABELS[4])
        state["scenes"] = motion.run(state["scenes"], direction, cfg, work); save()

    if start <= 5:
        report(5, STEP_LABELS[5])
        base = transitions.build_base(state["scenes"], direction, cfg, work)
        base = mograph.apply_overlays(base, state["scenes"], direction, cfg, work)
        assemble.run_directed(base, state["scenes"], direction, cfg,
                              str(voice), work, out_path)

    return out_path
