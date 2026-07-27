# -*- coding: utf-8 -*-
"""web.py — market-analyzer 로컬 웹 UI (포트 8899).

CLI(analyzer.py) 파이프라인을 브라우저에서 쓸 수 있게 감싼 최소 웹 앱.
의존성 없음(표준 라이브러리 http.server). 로컬 단일 사용자용.

  python web.py            # http://localhost:8899

기능:
  - 메인: 지역명/가동률/반경 입력 폼, 등록역 칩, 최근 리포트 목록, 세션 배지
  - 분석: 폼 제출 → analyzer 파이프라인 직접 호출(동기) → 리포트로 리다이렉트
  - 열람: output/ 리포트 서빙(경로 탐색 방지)
"""
from __future__ import annotations

import html
import os
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import locate
import model  # noqa: F401  (import 시 앵커 자기검증)
import molit
import m33
import report
import rules
import session_auto
import stations
from analyzer import build_caveats, compute_conservative, compute_scenarios

PORT = 8899
SESSION_FILE = os.path.join(config.BASE_DIR, "session.txt")
SESSION_SRC = os.path.join(config.BASE_DIR, "session.src")  # 세션 출처 라벨
_SRC_LABEL = {
    "browser": "세션 자동 감지됨(브라우저)",
    "login": "앱 로그인 세션",
    "paste": "붙여넣은 세션",
}


# --------------------------------------------------------------------------- #
# 세션 저장/조회 (쿠키 문자열만 저장 — 비밀번호는 절대 저장 안 함)
# --------------------------------------------------------------------------- #
def _save_session(cookie_str: str, source: str) -> None:
    """세션 쿠키 문자열을 session.txt에, 출처 라벨을 session.src에 원자적 저장."""
    tmp = SESSION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("Cookie: " + cookie_str.strip() + "\n")
    m33.parse_session_file(tmp)          # 형식 검증(실패 시 SessionError)
    os.replace(tmp, SESSION_FILE)
    try:
        with open(SESSION_SRC, "w", encoding="utf-8") as f:
            f.write(source)
    except OSError:
        pass


def _session_source() -> str:
    try:
        with open(SESSION_SRC, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "paste"


def _session_headers_or_none():
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        return m33.parse_session_file(SESSION_FILE)
    except (OSError, m33.SessionError):
        return None


# --------------------------------------------------------------------------- #
# 분석 파이프라인 (analyzer.main 핵심을 웹용으로 재구성 — html 경로 반환)
# --------------------------------------------------------------------------- #
def run_analysis(region: str, radius: float, window: str = "past"):
    """지역 분석 실행 후 생성된 리포트 html 파일명(basename) 반환.

    예약률은 실측 필수(기본: 지난 8주 확정 실적). 세션 없으면 수익 계산을
    보류하고 공급·월세만 출력. 미등록·수집 실패 등은 사람이 읽을 수 있는
    메시지의 ValueError로 올린다.
    """
    region = (region or "").strip()
    if not region:
        raise ValueError("지역명을 입력하세요.")

    config.ensure_dirs()

    # 1) 위치 해석: 사전 → 자동 해석(locate)
    st, name = stations.resolve(region)
    locate_evidence = None
    if st:
        lat, lon = st["lat"], st["lon"]
        lawd, dongs, desc = st["lawd"], st["dongs"], st["desc"]
        region_name = name
    else:
        try:
            loc = locate.auto_locate(region, radius, config.DEFAULT_MONTHS,
                                     molit.load_service_key(), use_cache=True)
        except locate.LocateError as e:
            raise ValueError(
                f"'{region}' 지역을 해석할 수 없습니다: {e}\n"
                f"등록된 지역: {', '.join(stations.known_names())}")
        lat, lon = loc["lat"], loc["lon"]
        lawd, dongs, desc = loc["lawd"], loc["dongs"], loc["desc"]
        region_name = region
        locate_evidence = loc["evidence"]

    # 세션 확보: session.txt 유효 → 사용 / 없거나 무효 → 브라우저 자동추출 시도
    session_headers = _session_headers_or_none()
    if session_headers is None:
        auto = session_auto.get_session()      # Edge→Chrome, 검증 포함
        if auto:
            try:
                _save_session(auto, "browser")
                session_headers = m33.parse_session_file(SESSION_FILE)
                sys.stderr.write("[세션] 브라우저에서 자동 감지·저장\n")
            except (OSError, m33.SessionError):
                session_headers = None

    # 2) 공급 스캔
    try:
        supply = m33.scan_supply(lat, lon, radius)
    except Exception:
        supply = {"n_total": 0, "n_type_excluded": 0, "n_notroom_excluded": 0,
                  "n_kept": 0, "weekly": {"median": None, "min": None,
                  "max": None, "n": 0}, "rooms": []}

    # 3) 예약률 — 실측 필수(기본: 지난 8주 확정 실적). 가정치 대체 없음.
    occupancy, occ_login_needed = None, False
    if session_headers:
        try:
            occupancy = m33.fetch_occupancy(supply["rooms"], session_headers,
                                            weeks=config.DEFAULT_WEEKS,
                                            samples=config.DEFAULT_SAMPLES,
                                            window=window)
        except m33.SessionError:
            # 만료(401) → 브라우저 자동추출 1회 재시도 후 재조회
            retry = session_auto.get_session()
            if retry:
                try:
                    _save_session(retry, "browser")
                    session_headers = m33.parse_session_file(SESSION_FILE)
                    occupancy = m33.fetch_occupancy(
                        supply["rooms"], session_headers,
                        weeks=config.DEFAULT_WEEKS,
                        samples=config.DEFAULT_SAMPLES, window=window)
                    sys.stderr.write("[세션] 만료 감지 → 자동 재획득 후 재조회\n")
                except (OSError, m33.SessionError):
                    occ_login_needed = True
            else:
                occ_login_needed = True
    else:
        occ_login_needed = True

    occ_used, occ_measured = None, False
    if occupancy and occupancy.get("ok"):
        occ_used, occ_measured = occupancy["combined_occ"], True

    # 4) MOLIT 밴드
    key = molit.load_service_key()
    mo = molit.collect(key, lawd, dongs, config.DEFAULT_MONTHS, use_cache=True)

    conservative = compute_conservative(supply["weekly"]["median"], occ_used,
                                        mo["bands"], config.DEFAULT_MGMT)
    scenarios = compute_scenarios(supply["weekly"]["median"], occ_used,
                                  mo["bands"], config.DEFAULT_MGMT)

    ctx = {
        "region": region_name, "desc": desc, "date": report._today(),
        "radius": radius, "months": config.DEFAULT_MONTHS,
        "weeks": config.DEFAULT_WEEKS, "window": window,
        "mgmt": config.DEFAULT_MGMT,
        "supply": supply, "occupancy": occupancy,
        "occ_login_needed": occ_login_needed, "occ_used": occ_used,
        "occ_measured": occ_measured, "molit": mo,
        "conservative": conservative, "scenarios": scenarios,
        "locate_evidence": locate_evidence,
    }
    ctx["caveats"] = build_caveats(ctx)
    ctx["analysis"] = rules.analyze(ctx)

    md_path, html_path = report.write_reports(ctx)
    return os.path.basename(html_path)


# --------------------------------------------------------------------------- #
# 메인 폼 HTML
# --------------------------------------------------------------------------- #
def _load_tokens():
    try:
        with open(config.TOKENS_CSS, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ":root{--g-800:#0E4633;--paper:#FAF8F5;--n-200:#E6E0D7;}"


def _recent_reports(limit=20):
    try:
        files = [f for f in os.listdir(config.OUTPUT_DIR) if f.endswith(".html")]
    except OSError:
        return []
    files.sort(key=lambda f: os.path.getmtime(os.path.join(config.OUTPUT_DIR, f)),
               reverse=True)
    return files[:limit]


def render_form(error: str = "", radius: str = "500", notice: str = "") -> str:
    tokens = _load_tokens()
    has_session = os.path.exists(SESSION_FILE)
    if has_session:
        src = _session_source()
        label = _SRC_LABEL.get(src, "세션 있음")
        badge = (f'<span class="badge badge-ok">{html.escape(label)} → 예약률 실측(지난 8주)</span>')
    else:
        badge = ('<span class="badge badge-warn">세션 없음 — 로그인 필요 '
                 '(수익 계산 보류·공급/월세만)</span>')

    # 세션 카드: 앱 로그인(폴백) + 고급(쿠키 붙여넣기, 최후 수단)
    if has_session:
        login_card = (
            '<div class="card"><div class="sec-title">33m2 세션</div>'
            f'<p class="muted">{html.escape(_SRC_LABEL.get(_session_source(), "세션 저장됨"))} '
            '— 예약률 실측이 활성화되어 있습니다. 분석 시작 시 만료가 감지되면 '
            '브라우저 세션으로 자동 재획득을 시도합니다.</p>'
            '<form method="post" action="/logout" style="margin-top:12px">'
            '<button type="submit" class="btn-ghost">세션 지우기</button></form></div>')
    else:
        login_card = (
            '<div class="card"><div class="sec-title">33m2 로그인 (예약률 실측용)</div>'
            '<p class="muted" style="margin-bottom:14px">브라우저(Edge/Chrome)에서 33m2에 '
            '로그인돼 있으면 <b>분석 시작만 눌러도</b> 세션이 자동 감지됩니다. '
            '자동 감지가 안 되면 아래로 로그인하세요.</p>'
            '<form method="post" action="/login">'
            '<div class="field"><label for="email">이메일</label>'
            '<input type="text" id="email" name="email" placeholder="33m2 계정 이메일"></div>'
            '<div class="field"><label for="password">비밀번호</label>'
            '<input type="password" id="password" name="password"></div>'
            '<button type="submit" class="btn">33m2 로그인</button>'
            '<div class="hint">🔒 비밀번호는 저장되지 않습니다 — 로그인 요청에만 쓰고 '
            '세션 쿠키만 보관합니다.</div></form>'
            '<details style="margin-top:16px"><summary class="adv">고급 · 쿠키 직접 붙여넣기</summary>'
            '<form method="post" action="/session" style="margin-top:12px">'
            '<textarea name="session" placeholder="Cookie: k=v; k2=v2   또는   '
            'Authorization: Bearer ..."></textarea>'
            '<div class="hint">개발자도구(F12) → Network → 요청 헤더의 Cookie 값. '
            '이 방법은 최후 수단입니다.</div>'
            '<button type="submit" class="btn-ghost" style="margin-top:10px">쿠키 저장</button>'
            '</form></details></div>')

    chips = "".join(
        f'<button type="button" class="chip" '
        f'onclick="document.getElementById(\'region\').value=\'{html.escape(n)}\'">'
        f'{html.escape(n)}</button>'
        for n in stations.known_names())

    reports = _recent_reports()
    if reports:
        items = "".join(
            f'<li><a href="/report?f={urllib.parse.quote(f)}">{html.escape(f)}</a></li>'
            for f in reports)
        recent = f'<ul class="recent">{items}</ul>'
    else:
        recent = '<p class="muted">아직 생성된 리포트가 없습니다.</p>'

    err_html = ""
    if error:
        err_html = f'<div class="err">{html.escape(error).replace(chr(10), "<br>")}</div>'
    notice_html = ""
    if notice:
        notice_html = f'<div class="notice">{html.escape(notice)}</div>'

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>market-analyzer · 단기임대 시장분석</title>
<style>
{tokens}
body {{ background: var(--paper); color: var(--n-800); }}
.page {{ max-width: 760px; margin: 0 auto; padding: 48px 24px 80px; }}
.hero h1 {{ font-size: 30px; color: var(--g-800); font-weight: 800; letter-spacing:-.02em; }}
.hero p {{ color: var(--n-500); margin-top: 6px; }}
.badge {{ display:inline-block; padding:6px 12px; border-radius:999px; font-size:13px;
  font-weight:600; margin-top:14px; }}
.badge-ok {{ background: var(--ok-bg); color: var(--g-700); }}
.badge-warn {{ background: var(--warn-bg); color: #8a6d1a; }}
.card {{ background:#fff; border:1px solid var(--n-200); border-radius:16px;
  padding:28px; margin-top:24px; box-shadow:0 1px 2px rgba(0,0,0,.03); }}
label {{ display:block; font-weight:600; font-size:14px; color:var(--n-700);
  margin-bottom:6px; }}
.field {{ margin-bottom:18px; }}
input[type=text], input[type=number], input[type=password] {{ width:100%; padding:11px 13px;
  font-size:15px; border:1px solid var(--n-300); border-radius:10px; background:var(--paper);
  font-family:var(--font-sans); color:var(--n-800); }}
input:focus {{ outline:none; border-color:var(--g-500); box-shadow:0 0 0 3px var(--g-100); }}
.btn-ghost {{ padding:10px 16px; font-size:14px; font-weight:600; color:var(--g-700);
  background:var(--g-50); border:1px solid var(--g-200); border-radius:10px; cursor:pointer;
  font-family:var(--font-sans); }}
.btn-ghost:hover {{ background:var(--g-100); }}
.adv {{ cursor:pointer; font-size:13px; font-weight:600; color:var(--g-700); }}
summary {{ list-style:revert; }}
.row {{ display:flex; gap:16px; }}
.row .field {{ flex:1; }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }}
.chip {{ padding:7px 13px; border-radius:999px; border:1px solid var(--g-200);
  background:var(--g-50); color:var(--g-700); font-size:13px; font-weight:600;
  cursor:pointer; font-family:var(--font-sans); }}
.chip:hover {{ background:var(--g-100); border-color:var(--g-300); }}
.btn {{ width:100%; padding:14px; font-size:16px; font-weight:700; color:#fff;
  background:var(--g-800); border:none; border-radius:12px; cursor:pointer;
  margin-top:6px; font-family:var(--font-sans); }}
.btn:hover {{ background:var(--g-700); }}
.btn:disabled {{ background:var(--n-400); cursor:wait; }}
.hint {{ font-size:12.5px; color:var(--n-500); margin-top:6px; }}
.err {{ background:var(--danger-bg); color:#9c2b2b; border:1px solid #e8b4b4;
  border-radius:10px; padding:14px 16px; margin-top:20px; font-size:14px; line-height:1.55; }}
.notice {{ background:var(--ok-bg); color:var(--g-700); border:1px solid var(--g-200);
  border-radius:10px; padding:12px 16px; margin-top:20px; font-size:14px; }}
textarea {{ width:100%; min-height:64px; padding:11px 13px; font-size:13px;
  border:1px solid var(--n-300); border-radius:10px; background:var(--paper);
  font-family:var(--font-mono); color:var(--n-800); resize:vertical; }}
textarea:focus {{ outline:none; border-color:var(--g-500); box-shadow:0 0 0 3px var(--g-100); }}
.sec-title {{ font-size:13px; font-weight:700; text-transform:uppercase;
  letter-spacing:.06em; color:var(--n-500); margin-bottom:10px; }}
.recent {{ list-style:none; padding:0; }}
.recent li {{ padding:8px 0; border-bottom:1px solid var(--n-200); }}
.recent a {{ color:var(--g-700); text-decoration:none; font-size:14px; }}
.recent a:hover {{ text-decoration:underline; }}
.muted {{ color:var(--n-500); font-size:14px; }}
#overlay {{ display:none; position:fixed; inset:0; background:rgba(250,248,245,.92);
  z-index:99; align-items:center; justify-content:center; flex-direction:column; }}
#overlay .spin {{ width:44px; height:44px; border:4px solid var(--g-100);
  border-top-color:var(--g-600); border-radius:50%; animation:sp 1s linear infinite; }}
@keyframes sp {{ to {{ transform:rotate(360deg); }} }}
#overlay p {{ margin-top:18px; color:var(--n-600); font-weight:600; }}
</style></head>
<body>
<div id="overlay"><div class="spin"></div><p>분석 중입니다… (수십 초 소요)</p></div>
<div class="page">
  <div class="hero">
    <h1>다니엘스테이 단기임대 시장분석</h1>
    <p>지역명을 입력하면 33㎡ 공급·MOLIT 실거래·수익률을 분석합니다.</p>
    {badge}
  </div>

  {err_html}
  {notice_html}

  <form class="card" method="post" action="/analyze"
        onsubmit="document.getElementById('overlay').style.display='flex';
                  document.getElementById('go').disabled=true;">
    <div class="field">
      <label for="region">지역명</label>
      <input type="text" id="region" name="region" placeholder="예: 동탄역" autofocus>
      <div class="chips">{chips}</div>
    </div>
    <div class="row">
      <div class="field">
        <label for="radius">반경 (m)</label>
        <input type="number" id="radius" name="radius" step="50" min="100" value="{html.escape(radius)}">
      </div>
    </div>
    <button type="submit" id="go" class="btn">분석 시작</button>
    <div class="hint">가동률은 지난 8주 확정 실적(booking+disable ÷ 기간)으로 실측합니다.
      브라우저에 33m2 로그인이 돼 있으면 세션이 자동 감지됩니다. 없으면 수익 계산은
      보류되고 공급·월세만 출력됩니다. 분석은 수십 초 걸릴 수 있습니다.</div>
  </form>

  {login_card}

  <div class="card">
    <div class="sec-title">최근 분석 리포트</div>
    {recent}
  </div>
</div>
</body></html>"""


# --------------------------------------------------------------------------- #
# HTTP 핸들러
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):  # 콘솔 로그 간결화
        sys.stderr.write("  " + (fmt % a) + "\n")

    def _send_html(self, body: str, code: int = 200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            err = qs.get("error", [""])[0]
            radius = qs.get("radius", ["500"])[0]
            notice = qs.get("notice", [""])[0]
            self._send_html(render_form(err, radius, notice))
            return

        if path == "/report":
            fname = qs.get("f", [""])[0]
            self._serve_output(fname)
            return

        self._send_html("<h1>404</h1>", 404)

    def _serve_output(self, fname: str):
        # 경로 탐색 방지: basename만 취하고 OUTPUT_DIR 내부인지 재확인
        safe = os.path.basename(fname)
        full = os.path.realpath(os.path.join(config.OUTPUT_DIR, safe))
        out_root = os.path.realpath(config.OUTPUT_DIR)
        if not full.startswith(out_root + os.sep) or not os.path.isfile(full):
            self._send_html("<h1>404 리포트를 찾을 수 없습니다</h1>", 404)
            return
        ctype = "text/html; charset=utf-8" if full.endswith(".html") \
            else "text/plain; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_form(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        return urllib.parse.parse_qs(body)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/analyze":
            self._post_analyze()
        elif path == "/login":
            self._post_login()
        elif path == "/session":
            self._post_session()
        elif path == "/logout":
            self._post_logout()
        else:
            self._send_html("<h1>404</h1>", 404)

    def _post_login(self):
        """앱 내 로그인: 서버가 33m2에 대신 로그인 → 세션 쿠키만 저장.
        비밀번호는 메모리에서만 사용하고 저장·로깅하지 않는다."""
        form = self._read_form()
        email = form.get("email", [""])[0].strip()
        password = form.get("password", [""])[0]     # 로깅 금지
        try:
            cookie_str = session_auto.app_login(email, password)
            _save_session(cookie_str, "login")
            del password
            sys.stderr.write("[세션] 앱 로그인 성공 → 세션 저장(비밀번호 미저장)\n")
            self._redirect("/?notice=" + urllib.parse.quote(
                "33m2 로그인 성공 — 예약률 실측이 활성화되었습니다."))
        except session_auto.LoginError as e:
            self._redirect("/?error=" + urllib.parse.quote(str(e)))
        except Exception as e:
            traceback.print_exc()
            self._redirect("/?error=" + urllib.parse.quote(f"로그인 오류: {e}"))

    def _post_session(self):
        """고급: 쿠키 붙여넣기 → 형식 검증 후 저장."""
        form = self._read_form()
        text = form.get("session", [""])[0].strip()
        if not text:
            self._redirect("/?error=" + urllib.parse.quote("붙여넣을 쿠키가 비어 있습니다."))
            return
        tmp = SESSION_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            m33.parse_session_file(tmp)
            os.replace(tmp, SESSION_FILE)
            with open(SESSION_SRC, "w", encoding="utf-8") as f:
                f.write("paste")
            self._redirect("/?notice=" + urllib.parse.quote("쿠키 세션 저장됨."))
        except m33.SessionError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            self._redirect("/?error=" + urllib.parse.quote(
                "붙여넣은 세션에서 Cookie/Authorization 을 찾지 못했습니다. "
                "'k=v; k2=v2' 또는 'Bearer <토큰>' 형식으로 넣어주세요."))

    def _post_logout(self):
        for p in (SESSION_FILE, SESSION_SRC):
            try:
                os.remove(p)
            except OSError:
                pass
        self._redirect("/?notice=" + urllib.parse.quote("세션을 지웠습니다."))

    def _post_analyze(self):
        form = self._read_form()
        region = form.get("region", [""])[0]
        radius_raw = form.get("radius", ["500"])[0].strip()
        try:
            radius = float(radius_raw) if radius_raw else config.DEFAULT_RADIUS_M
        except ValueError:
            self._redirect("/?error=" + urllib.parse.quote("반경은 숫자여야 합니다."))
            return

        sys.stderr.write(f"[분석] region={region!r} radius={radius} "
                         f"session={'있음' if os.path.exists(SESSION_FILE) else '없음'}\n")
        try:
            fname = run_analysis(region, radius)
        except ValueError as e:
            q = urllib.parse.urlencode({"error": str(e), "radius": radius_raw})
            self._redirect("/?" + q)
            return
        except Exception as e:
            traceback.print_exc()
            msg = f"분석 중 오류가 발생했습니다: {e}"
            q = urllib.parse.urlencode({"error": msg, "radius": radius_raw})
            self._redirect("/?" + q)
            return

        self._redirect("/report?f=" + urllib.parse.quote(fname))


def main():
    config.ensure_dirs()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"market-analyzer 웹 UI: http://localhost:{PORT}")
    print(f"  세션 파일: {'있음' if os.path.exists(SESSION_FILE) else '없음'} ({SESSION_FILE})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
