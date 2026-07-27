# -*- coding: utf-8 -*-
"""get_session.py — 브라우저로 33m2에 로그인하고 세션을 가져오는 반자동 헬퍼.

앱 내 로그인(session_auto.app_login)이 COMN_003("처리중입니다") 등으로 막힐 때
가장 확실한 우회 경로. 브라우저를 열어 사람이 직접 로그인하고, 엔터를 누르면
로컬 쿠키 저장소에서 33m2 세션을 재추출해 session.txt 로 저장한다.

  python get_session.py                # 기본 브라우저로 열고 대화형 진행
  python get_session.py --no-open      # 브라우저 자동 열기 없이 감지만
  python get_session.py --profile      # 전용 프로필로 크롬/엣지 실행(권한문제 우회)

쿠키 추출이 막히는 대표 원인과 대응:
  · Edge/Chrome 앱바운드 암호화 → 브라우저를 완전히 종료한 뒤 재시도하거나,
    --profile 모드(전용 프로필 + 원격 디버깅 포트)로 로그인.
  · 그래도 안 되면 F12 → Network → 요청 헤더의 Cookie 를 복사해
    session.txt 에 붙여넣기(웹 UI '고급' 탭에서도 가능).
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):      # Windows 기본 콘솔(cp949)에서 U+2014 등 출력 크래시 방지
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser

import config
import session_auto

SESSION_FILE = os.path.join(config.BASE_DIR, "session.txt")
SESSION_SRC = os.path.join(config.BASE_DIR, "session.src")
LOGIN_PAGE = "https://web.33m2.co.kr/"
DEBUG_PORT = 9222


def save_session(cookie_str: str, source: str = "browser") -> None:
    tmp = SESSION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("Cookie: " + cookie_str.strip() + "\n")
    os.replace(tmp, SESSION_FILE)
    try:
        with open(SESSION_SRC, "w", encoding="utf-8") as f:
            f.write(source)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# 전용 프로필 + 원격 디버깅 포트 경로 (관리자 권한 불필요)
#   웹 UI(web.py)에서도 그대로 재사용하는 공개 API:
#     find_browser() / launch_profile_browser() / fetch_profile_cookies()
# --------------------------------------------------------------------------- #
class ProfileError(RuntimeError):
    """전용 창 로그인 경로 실패(사람이 읽을 메시지 포함)."""


def find_browser():
    """설치된 크롬/엣지 실행파일 탐색 → (이름, 경로). 없으면 None."""
    cands = [
        ("Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("Chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ("Edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ("Edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for name, path in cands:
        if os.path.exists(path):
            return name, path
    for name, exe in (("Chrome", "chrome"), ("Edge", "msedge")):
        p = shutil.which(exe)
        if p:
            return name, p
    return None


def _cdp(path: str, port: int = DEBUG_PORT, timeout: float = 5.0):
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def debug_port_alive(port: int = DEBUG_PORT) -> bool:
    """전용 창(원격 디버깅)이 살아있는지."""
    try:
        _cdp("/json/version", port=port, timeout=2.0)
        return True
    except Exception:
        return False


def launch_profile_browser(port: int = DEBUG_PORT):
    """임시 전용 프로필로 Chrome/Edge를 띄우고 33m2 로그인 페이지를 연다.

    사용자 기본 프로필을 건드리지 않고 관리자 권한도 필요 없다.
    실패 시 ProfileError(사람이 읽을 메시지).
    """
    if debug_port_alive(port):
        return None                     # 이미 떠 있음 — 재사용

    found = find_browser()
    if not found:
        raise ProfileError(
            "Chrome 또는 Edge 실행 파일을 찾지 못했습니다. "
            "Chrome/Edge를 설치했는지 확인하거나, '고급 · 쿠키 직접 붙여넣기'를 사용하세요.")
    name, exe = found

    # 포트가 다른 프로세스에 점유됐는지(디버깅 응답이 없는데 열려 있는 경우) 확인
    import socket
    with socket.socket() as s:
        s.settimeout(1.0)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise ProfileError(
                f"포트 {port} 가 이미 다른 프로그램에 사용 중입니다. "
                "해당 프로그램을 종료한 뒤 다시 시도하세요.")

    profile_dir = os.path.join(tempfile.gettempdir(), "m33_login_profile")
    os.makedirs(profile_dir, exist_ok=True)
    try:
        proc = subprocess.Popen(
            [exe, f"--remote-debugging-port={port}",
             f"--user-data-dir={profile_dir}", "--no-first-run",
             "--no-default-browser-check", LOGIN_PAGE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise ProfileError(f"{name} 실행에 실패했습니다: {e}")

    # 디버깅 포트가 열릴 때까지 잠깐 대기
    for _ in range(20):
        if debug_port_alive(port):
            return proc
        time.sleep(0.5)
    raise ProfileError(
        f"{name} 전용 창은 실행했지만 디버깅 포트({port})가 열리지 않았습니다. "
        "이미 실행 중인 같은 브라우저가 있으면 모두 종료한 뒤 다시 시도하세요.")


def fetch_profile_cookies(port: int = DEBUG_PORT) -> str:
    """전용 창(CDP)에서 httpOnly 포함 33m2 쿠키를 읽어 문자열로 반환.

    실패 시 ProfileError(로그인 미완료·창 종료 등 이유 포함).
    """
    if not debug_port_alive(port):
        raise ProfileError(
            "전용 로그인 창을 찾을 수 없습니다. 창을 닫았다면 "
            "[전용 창으로 로그인]을 먼저 눌러 다시 열어주세요.")
    try:
        targets = _cdp("/json/list", port=port)
    except Exception as e:
        raise ProfileError(f"전용 창과 통신하지 못했습니다: {e}")

    page = next((t for t in targets if t.get("type") == "page"
                 and "33m2" in (t.get("url") or "")), None)
    if not page:
        raise ProfileError(
            "전용 창에 33m2 페이지가 열려 있지 않습니다. "
            "그 창에서 web.33m2.co.kr 에 접속해 로그인한 뒤 다시 눌러주세요.")

    cookies = _all_cookies_via_cdp(page)
    if cookies is None:
        raise ProfileError("전용 창에서 쿠키를 읽지 못했습니다. 잠시 후 다시 시도해 주세요.")
    pairs = [f"{c['name']}={c['value']}" for c in cookies
             if "33m2" in (c.get("domain") or "")]
    if not pairs:
        raise ProfileError(
            "전용 창에서 33m2 쿠키를 찾지 못했습니다 — 아직 로그인하지 않은 것 같습니다. "
            "그 창에서 로그인을 마친 뒤 다시 눌러주세요.")
    cookie_str = "; ".join(pairs)
    if not session_auto.validate_cookie(cookie_str):
        raise ProfileError(
            "쿠키는 찾았지만 로그인 세션이 아직 유효하지 않습니다 — "
            "전용 창에서 로그인이 완료됐는지 확인한 뒤 다시 눌러주세요.")
    return cookie_str


def _all_cookies_via_cdp(page):
    """CDP Network.getAllCookies (httpOnly 포함). 실패 시 None."""
    try:
        import websocket as ws
    except ImportError:
        raise ProfileError(
            "websocket-client 패키지가 필요합니다: pip install websocket-client")
    try:
        # Chrome DevTools는 Origin 헤더가 붙은 WS 연결을 403으로 거부한다
        # → suppress_origin 필수.
        conn = ws.create_connection(page["webSocketDebuggerUrl"], timeout=10,
                                    suppress_origin=True)
    except Exception as e:
        raise ProfileError(f"전용 창에 연결하지 못했습니다: {e}")
    try:
        conn.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
        deadline = time.time() + 10
        while time.time() < deadline:
            msg = json.loads(conn.recv())
            if msg.get("id") == 1:
                return msg.get("result", {}).get("cookies", [])
        return None
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def profile_login(timeout_sec: int = 300):
    """전용 프로필로 브라우저를 띄워 로그인시키고 CDP로 쿠키를 읽는다(CLI 대화형).

    사용자 기본 프로필을 건드리지 않고, 관리자 권한도 필요 없다.
    """
    try:
        print("[1/3] 전용 프로필로 브라우저 실행 (기본 프로필 영향 없음)")
        launch_profile_browser()
    except ProfileError as e:
        print(f"실패: {e}")
        return None

    print("[2/3] 열린 창에서 33m2에 로그인하세요. 로그인되면 자동으로 감지합니다.")
    print(f"      (최대 {timeout_sec//60}분 대기 · 취소하려면 Ctrl+C)")
    deadline = time.time() + timeout_sec
    try:
        while time.time() < deadline:
            try:
                cookie = fetch_profile_cookies()
                print("[3/3] 로그인 감지 — 세션 저장")
                return cookie
            except ProfileError:
                time.sleep(3)
    except KeyboardInterrupt:
        print("\n취소됨.")
        return None
    print("시간이 초과되었습니다.")
    return None


# --------------------------------------------------------------------------- #
# 기본 경로: 브라우저 열고 → 엔터 → browser_cookie3 재추출
# --------------------------------------------------------------------------- #
def interactive(open_browser: bool = True) -> int:
    existing = None
    if os.path.exists(SESSION_FILE):
        try:
            import m33
            m33.parse_session_file(SESSION_FILE)
            existing = True
        except Exception:
            existing = None
    if existing:
        print(f"기존 세션 파일이 있습니다: {SESSION_FILE}")

    print("먼저 브라우저에서 33m2에 로그인해야 합니다.")
    if open_browser:
        print(f"  → 브라우저를 엽니다: {LOGIN_PAGE}")
        try:
            webbrowser.open(LOGIN_PAGE)
        except Exception:
            print("  (자동으로 열지 못했습니다 — 직접 접속해 주세요)")
    try:
        input("\n로그인을 마친 뒤 이 창에서 [Enter] 를 누르세요... ")
    except (EOFError, KeyboardInterrupt):
        print("\n취소됨.")
        return 1

    print("쿠키 저장소에서 33m2 세션을 찾는 중...")
    cookie = session_auto.get_session()
    if cookie:
        save_session(cookie, "browser")
        print(f"성공 — 세션을 저장했습니다: {SESSION_FILE}")
        print("이제 웹 UI에서 [분석 시작] 을 누르면 선점률이 실측됩니다.")
        return 0

    print("\n브라우저 쿠키를 읽지 못했습니다. 아래를 순서대로 시도해 보세요:")
    print("  1) 브라우저를 완전히 종료(모든 창)한 뒤  python get_session.py --no-open")
    print("  2) 전용 프로필 모드:  python get_session.py --profile")
    print("  3) 최후 수단 — F12 → Network → 아무 요청의 Cookie 헤더를 복사해")
    print(f"     {SESSION_FILE} 에 'Cookie: <붙여넣기>' 한 줄로 저장")
    print("     (웹 UI의 '고급 · 쿠키 직접 붙여넣기' 에서도 가능)")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="브라우저로 33m2 로그인 후 세션 자동 획득")
    ap.add_argument("--no-open", action="store_true",
                    help="브라우저를 자동으로 열지 않음(이미 로그인한 경우)")
    ap.add_argument("--profile", action="store_true",
                    help="전용 프로필+원격 디버깅으로 로그인(관리자 권한 불필요)")
    args = ap.parse_args(argv)

    if args.profile:
        cookie = profile_login()
        if cookie:
            save_session(cookie, "browser")
            print(f"세션 저장 완료: {SESSION_FILE}")
            return 0
        return 1
    return interactive(open_browser=not args.no_open)


if __name__ == "__main__":
    raise SystemExit(main())
