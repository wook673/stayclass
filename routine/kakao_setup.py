# -*- coding: utf-8 -*-
"""카카오 토큰 발급 헬퍼 (1회 실행).

REST API 키만 있으면 브라우저 로그인·동의 한 번으로
routine/kakao_token.json 에 access/refresh 토큰을 저장한다.

사용:
    python kakao_setup.py                 # 실행 후 키 입력 프롬프트
    python kakao_setup.py --key <REST_API_KEY>
    python kakao_setup.py --key <REST_API_KEY> --secret <CLIENT_SECRET>

앱에 '클라이언트 시크릿'이 활성화돼 있으면 --secret 이 필요하다
(콘솔 경로: 앱 > 플랫폼 키 > REST API 키 > 클라이언트 시크릿).

사전 준비(developers.kakao.com)는 routine/KAKAO_SETUP.md 참고.
"""
from __future__ import annotations

import argparse
import http.server
import re
import socket
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kakao_notify import TOKEN_PATH, build_token_record, mask, save_token  # noqa: E402

AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SCOPE = "talk_message"
DEFAULT_PORT = 8950
DEFAULT_HOST = "127.0.0.1"
WAIT_TIMEOUT_SEC = 300

KEY_RE = re.compile(r"^[0-9a-zA-Z]{20,64}$")

PAGE_OK = """<!doctype html><meta charset="utf-8">
<title>카카오 연동 완료</title>
<style>body{font-family:system-ui,'Malgun Gothic',sans-serif;background:#f6f7f9;
margin:0;display:flex;align-items:center;justify-content:center;height:100vh}
.card{background:#fff;border-radius:16px;padding:40px 48px;box-shadow:0 8px 30px rgba(0,0,0,.08);
text-align:center;max-width:420px}h1{font-size:20px;margin:0 0 12px;color:#14532d}
p{color:#475569;line-height:1.6;margin:0;font-size:14px}</style>
<div class="card"><h1>카카오 연동이 완료되었습니다</h1>
<p>이 창을 닫으셔도 됩니다.<br>이제 루틴이 끝나면 카카오톡으로 요약이 전송됩니다.</p></div>
"""

PAGE_FAIL = """<!doctype html><meta charset="utf-8">
<title>카카오 연동 실패</title>
<style>body{font-family:system-ui,'Malgun Gothic',sans-serif;background:#f6f7f9;
margin:0;display:flex;align-items:center;justify-content:center;height:100vh}
.card{background:#fff;border-radius:16px;padding:40px 48px;box-shadow:0 8px 30px rgba(0,0,0,.08);
text-align:center;max-width:460px}h1{font-size:20px;margin:0 0 12px;color:#991b1b}
p{color:#475569;line-height:1.6;margin:0;font-size:14px}</style>
<div class="card"><h1>연동에 실패했습니다</h1><p>{reason}</p></div>
"""


class _Callback:
    """콜백에서 받은 code/에러를 담아두는 공유 상자."""

    def __init__(self) -> None:
        self.code: str | None = None
        self.error: str | None = None
        self.done = threading.Event()


def _make_handler(box: _Callback):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self._respond(404, "<h1>404</h1>")
                return
            params = urllib.parse.parse_qs(parsed.query)
            code = (params.get("code") or [None])[0]
            error = (params.get("error_description") or params.get("error") or [None])[0]
            if code:
                box.code = code
                self._respond(200, PAGE_OK)
            else:
                box.error = error or "인가 코드를 받지 못했습니다."
                self._respond(400, PAGE_FAIL.replace("{reason}", box.error))
            box.done.set()

        def _respond(self, status: int, html: str) -> None:
            payload = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args) -> None:  # 콘솔 소음·토큰 노출 방지
            return

    return Handler


def _validate_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        raise SystemExit("오류: REST API 키가 비어 있습니다. developers.kakao.com > 앱 키에서 복사하세요.")
    if not KEY_RE.match(key):
        raise SystemExit(
            "오류: REST API 키 형식이 올바르지 않습니다 (영숫자 32자 내외).\n"
            "  - 'JavaScript 키'나 '네이티브 앱 키'가 아닌 'REST API 키'인지 확인하세요.\n"
            f"  - 입력값 길이: {len(key)}자"
        )
    return key


def _auth_url(key: str, redirect_uri: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": key,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
        }
    )
    return f"{AUTH_URL}?{query}"


SECRET_HINT = (
    "\n→ 이 앱은 '클라이언트 시크릿'이 활성화된 것으로 보입니다."
    " --secret 값을 넣어 다시 실행하세요.\n"
    "  python routine/kakao_setup.py --key <REST_API_KEY> --secret <CLIENT_SECRET>\n"
    "  (콘솔 경로: 앱 > 플랫폼 키 > REST API 키 > 클라이언트 시크릿)"
)


def _exchange(
    key: str, code: str, redirect_uri: str, secret: str | None = None
) -> dict:
    data = {
        "grant_type": "authorization_code",
        "client_id": key,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    if secret:
        data["client_secret"] = secret

    resp = requests.post(TOKEN_URL, data=data, timeout=20)
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text[:300]}
    if resp.status_code != 200 or not body.get("access_token"):
        desc = str(body.get("error_description") or body)
        error = str(body.get("error") or "")
        hint = ""
        if error == "invalid_client" or "invalid_client" in desc:
            # secret 없이 시도했다가 막힌 전형적인 케이스 → 자동 폴백 안내.
            hint = (
                SECRET_HINT
                if not secret
                else (
                    "\n→ client_id 또는 client_secret이 앱과 맞지 않습니다."
                    " 콘솔에서 값을 다시 복사하세요.\n"
                    "  (콘솔 경로: 앱 > 플랫폼 키 > REST API 키 > 클라이언트 시크릿)"
                )
            )
        elif "KOE006" in desc:
            hint = (
                "\n→ Redirect URI 불일치입니다. 카카오 로그인 > Redirect URI에 "
                f"{redirect_uri} 를 정확히 등록하세요."
            )
        elif "KOE101" in desc:
            hint = "\n→ REST API 키가 잘못되었거나 앱이 존재하지 않습니다."
        elif "KOE205" in desc or "scope" in desc.lower():
            hint = "\n→ 동의항목에서 '카카오톡 메시지 전송(talk_message)'을 켜세요."
        raise SystemExit(
            f"오류: 토큰 교환 실패 [HTTP {resp.status_code}] "
            f"{body.get('error', '')} {desc}{hint}"
        )
    return body


def run(
    key: str,
    port: int,
    host: str,
    no_browser: bool,
    path: Path | None,
    secret: str | None = None,
) -> int:
    redirect_uri = f"http://localhost:{port}/callback"
    box = _Callback()

    try:
        server = http.server.HTTPServer((host, port), _make_handler(box))
    except OSError as exc:
        print(
            f"오류: {host}:{port} 포트를 열 수 없습니다 ({exc}).\n"
            "  다른 프로그램이 포트를 쓰고 있는지 확인하거나 잠시 후 다시 실행하세요.",
            file=sys.stderr,
        )
        return 1

    server.timeout = 1
    url = _auth_url(key, redirect_uri)

    print(f"[1/3] 로컬 콜백 서버 시작: http://{host}:{port}/callback")
    print("[2/3] 브라우저에서 카카오 로그인·동의를 진행하세요.")
    if no_browser:
        print(f"      아래 주소를 브라우저에 붙여넣으세요:\n      {url}")
    else:
        opened = webbrowser.open(url)
        if not opened:
            print(f"      브라우저 자동 실행 실패. 아래 주소를 붙여넣으세요:\n      {url}")

    deadline = threading.Event()
    timer = threading.Timer(WAIT_TIMEOUT_SEC, deadline.set)
    timer.daemon = True
    timer.start()
    try:
        while not box.done.is_set() and not deadline.is_set():
            server.handle_request()
    except KeyboardInterrupt:
        print("\n중단되었습니다.", file=sys.stderr)
        return 130
    finally:
        timer.cancel()
        server.server_close()

    if box.error:
        print(f"오류: 카카오 인증 거부·실패 — {box.error}", file=sys.stderr)
        return 1
    if not box.code:
        print(
            f"오류: {WAIT_TIMEOUT_SEC}초 안에 인증이 완료되지 않았습니다. 다시 실행하세요.",
            file=sys.stderr,
        )
        return 1

    print("[3/3] 인가 코드 수신 — 토큰 교환 중...")
    if secret:
        print("      client_secret 포함하여 요청합니다.")
    payload = _exchange(key, box.code, redirect_uri, secret)
    record = build_token_record(payload, key, client_secret=secret)
    saved = save_token(record, path)

    print("\n완료: 카카오 토큰을 저장했습니다.")
    print(f"  파일        : {saved}")
    print(f"  access_token: {mask(record['access_token'])}")
    print(f"  refresh_token: {mask(record.get('refresh_token'))}")
    print(f"  client_id   : {mask(record.get('client_id'))}")
    print(f"  client_secret: {mask(record.get('client_secret'))}")
    print(f"  scope       : {record.get('scope', SCOPE)}")
    print("\n테스트: python routine/kakao_notify.py --text \"연동 테스트\"")
    print("주의: 이 파일은 비밀입니다. 커밋·공유 금지(.gitignore 등록됨).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kakao_setup.py",
        description="카카오톡 '나에게 보내기' 토큰을 1회 발급해 routine/kakao_token.json에 저장합니다.",
        epilog="사전 준비(앱 생성·플랫폼·동의항목)는 routine/KAKAO_SETUP.md 를 먼저 읽으세요.",
    )
    parser.add_argument(
        "--key", default=None, help="카카오 REST API 키 (생략 시 실행 후 입력받음)"
    )
    parser.add_argument(
        "--secret",
        default=None,
        help=(
            "카카오 클라이언트 시크릿 (선택). 앱 > 플랫폼 키 > REST API 키 > "
            "클라이언트 시크릿이 '사용함'이면 필수"
        ),
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"콜백 포트 (기본 {DEFAULT_PORT})")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"콜백 바인드 주소 (기본 {DEFAULT_HOST})")
    parser.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    parser.add_argument(
        "--token-file", default=None, help=f"토큰 저장 경로 (기본 {TOKEN_PATH})"
    )
    args = parser.parse_args(argv)

    if requests is None:
        print("오류: requests 패키지가 필요합니다 — pip install requests", file=sys.stderr)
        return 1

    key = args.key
    if not key:
        try:
            key = input("카카오 REST API 키를 붙여넣고 Enter: ")
        except (EOFError, KeyboardInterrupt):
            print("\n입력이 취소되었습니다.", file=sys.stderr)
            return 1
    key = _validate_key(key)
    secret = (args.secret or "").strip() or None

    path = Path(args.token_file) if args.token_file else None
    return run(key, args.port, args.host, args.no_browser, path, secret)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except socket.error as exc:  # pragma: no cover
        print(f"오류: 네트워크 문제 — {exc}", file=sys.stderr)
        sys.exit(1)
