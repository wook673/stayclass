"""영상메이커 웹 UI 서버 (Flask) — start.bat 더블클릭으로 실행.

브라우저에서: 프로젝트 만들기 → 대본 입력 → 음성(TTS/녹음) → 영상 만들기 → 미리보기/다운로드.
제작은 백그라운드 스레드로 돌리고, 진행상황은 /status 폴링으로 표시.
"""
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

# 콘솔 인코딩이 cp949여도 한글/특수문자 출력이 죽지 않도록
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from flask import Flask, jsonify, request, send_file, abort

import core

app = Flask(__name__)
WEB = Path(__file__).parent / "web"

# 프로젝트별 제작 작업 상태
JOBS: dict[str, dict] = {}


@app.get("/")
def index():
    return send_file(WEB / "index.html")


@app.get("/api/projects")
def api_projects():
    return jsonify([core.project_status(n) for n in core.list_project_names()])


@app.post("/api/projects")
def api_create():
    name = (request.json or {}).get("name", "")
    try:
        core.create_project(name)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(core.project_status(name))


@app.get("/api/project/<name>")
def api_get(name):
    if name not in core.list_project_names():
        abort(404)
    st = core.project_status(name)
    st["script"] = core.get_script(name)
    st["estimate"] = core.estimate_label(st["chars"])
    job = JOBS.get(name)
    st["job"] = {k: job[k] for k in ("state", "step", "label", "error")} if job else None
    return jsonify(st)


@app.post("/api/project/<name>/script")
def api_save_script(name):
    text = (request.json or {}).get("text", "")
    core.save_script(name, text)
    chars = core.count_chars(text)
    return jsonify(chars=chars, estimate=core.estimate_label(chars))


@app.post("/api/project/<name>/tts")
def api_tts(name):
    voice = (request.json or {}).get("voice", "InJoon")
    try:
        core.generate_tts(name, voice)
    except Exception as e:
        return jsonify(error=str(e)), 400
    return jsonify(core.project_status(name))


@app.post("/api/project/<name>/upload")
def api_upload(name):
    f = request.files.get("file")
    if not f:
        return jsonify(error="파일이 없습니다."), 400
    try:
        core.save_recording(name, f.filename, f.read())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(core.project_status(name))


# 프로젝트별 대본 생성 작업 상태
GEN_JOBS: dict[str, dict] = {}


def _gen_worker(name, topic, chars):
    job = GEN_JOBS[name]
    try:
        core.generate_script(name, topic, chars)
        job.update(state="done")
    except Exception as e:
        traceback.print_exc()
        job.update(state="error", error=str(e))


@app.post("/api/project/<name>/gen_script")
def api_gen_script(name):
    if name not in core.list_project_names():
        abort(404)
    cur = GEN_JOBS.get(name)
    if cur and cur["state"] == "running":
        return jsonify(error="이미 생성 중입니다."), 409
    body = request.json or {}
    topic = (body.get("topic") or "").strip()
    if not topic:
        return jsonify(error="주제를 먼저 입력하세요."), 400
    chars = max(100, min(int(body.get("chars", 300)), 2000))
    GEN_JOBS[name] = {"state": "running", "error": None}
    threading.Thread(target=_gen_worker, args=(name, topic, chars), daemon=True).start()
    return jsonify(state="running")


@app.get("/api/project/<name>/gen_status")
def api_gen_status(name):
    job = GEN_JOBS.get(name)
    return jsonify(job or {"state": "idle"})


@app.post("/api/project/<name>/settings")
def api_settings(name):
    if name not in core.list_project_names():
        abort(404)
    return jsonify(core.save_settings(name, request.json or {}))


@app.post("/api/project/<name>/bgm")
def api_bgm(name):
    f = request.files.get("file")
    if not f:
        return jsonify(error="파일이 없습니다."), 400
    try:
        core.save_bgm(name, f.filename, f.read())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(core.project_status(name))


@app.delete("/api/project/<name>/bgm")
def api_bgm_delete(name):
    core.remove_bgm(name)
    return jsonify(core.project_status(name))


def _build_worker(name):
    job = JOBS[name]
    try:
        def on_progress(step, label):
            job.update(step=step, label=label)
        core.run_pipeline(name, on_progress=on_progress)
        job.update(state="done", step=5, label="완료")
    except Exception as e:
        traceback.print_exc()
        job.update(state="error", error=str(e))


@app.post("/api/project/<name>/build")
def api_build(name):
    if name not in core.list_project_names():
        abort(404)
    cur = JOBS.get(name)
    if cur and cur["state"] == "running":
        return jsonify(error="이미 제작 중입니다."), 409
    JOBS[name] = {"state": "running", "step": 0, "label": "준비 중...", "error": None}
    threading.Thread(target=_build_worker, args=(name,), daemon=True).start()
    return jsonify(state="running")


@app.get("/api/project/<name>/status")
def api_status(name):
    job = JOBS.get(name)
    if not job:
        return jsonify(state="idle")
    return jsonify({k: job[k] for k in ("state", "step", "label", "error")})


@app.get("/api/project/<name>/video")
def api_video(name):
    path = core.project_dir(name) / "final.mp4"
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="video/mp4", conditional=True)


def main():
    url = "http://127.0.0.1:5000"
    print(f"\n  [영상메이커] 실행 중 - 브라우저에서 열기: {url}")
    print("  (이 창을 닫으면 종료됩니다)\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=5000, threaded=True)


if __name__ == "__main__":
    main()
