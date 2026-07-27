# -*- coding: utf-8 -*-
"""session_auto.py — 33m2 세션 자동 획득 (쿠키 자동추출 + 앱 내 로그인).

우선순위 3단 폴백(웹/CLI에서 조합해 사용):
  1) 브라우저 쿠키 자동추출  get_session()  — Edge→Chrome 로그인 세션 재사용
  2) 앱 내 로그인            app_login(username, password)  — 서버가 대신 로그인
  3) 쿠키 붙여넣기(최후 수단) — web.py textarea (여기선 미구현)

엔드포인트(리버스 확정):
  로그인   POST https://web.33m2.co.kr/v1/user/login  JSON {username, password}
           성공→Set-Cookie 세션 / 실패→400 VLD_001(필드누락)·VLD_002(자격증명 오류)
  인증확인 GET  https://web.33m2.co.kr/v1/user/me       200=유효 / 401 AUTH_002=무효

보안: 비밀번호는 메모리에서만 사용하고 파일·로그 어디에도 저장하지 않는다.
쿠키 문자열만 반환(호출측이 session.txt에 저장). 모든 예외는 안전하게 흡수.
"""
from __future__ import annotations

import http.cookiejar
from typing import Optional

import requests

LOGIN_URL = "https://web.33m2.co.kr/v1/user/login"
ME_URL = "https://web.33m2.co.kr/v1/user/me"
COOKIE_DOMAIN = "33m2.co.kr"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_BASE_HEADERS = {"User-Agent": _UA, "Accept": "application/json",
                 "Referer": "https://web.33m2.co.kr/"}
# 세션 판별에 의미있는 쿠키 이름 힌트(있으면 우선). 없어도 전체를 문자열로 사용.
_SESSION_HINTS = ("SESSION", "JSESSIONID", "connect.sid", "access", "token",
                  "refresh", "auth")


class LoginError(RuntimeError):
    """앱 내 로그인 실패(자격증명 오류·네트워크 등). 사람이 읽을 메시지 포함."""


# --------------------------------------------------------------------------- #
# 공통: 쿠키 유효성 확인 (가벼운 인증 API 1콜)
# --------------------------------------------------------------------------- #
def validate_cookie(cookie_str: Optional[str], timeout: float = 12.0) -> bool:
    """Cookie 헤더가 33m2 유효 세션인지 GET /v1/user/me 로 확인(200=유효)."""
    if not cookie_str:
        return False
    try:
        h = dict(_BASE_HEADERS)
        h["Cookie"] = cookie_str
        r = requests.get(ME_URL, headers=h, timeout=timeout)
    except requests.RequestException:
        return False
    return r.status_code == 200


def _jar_to_cookie_str(jar) -> Optional[str]:
    """CookieJar → 'k=v; k2=v2' 문자열 (33m2 도메인만)."""
    pairs = []
    for c in jar:
        if COOKIE_DOMAIN in (c.domain or ""):
            pairs.append(f"{c.name}={c.value}")
    if not pairs:
        return None
    # 세션 힌트 쿠키를 앞으로(가독성용, 서버는 순서 무관)
    pairs.sort(key=lambda p: 0 if any(
        h.lower() in p.split("=", 1)[0].lower() for h in _SESSION_HINTS) else 1)
    return "; ".join(pairs)


# --------------------------------------------------------------------------- #
# 1) 브라우저 쿠키 자동추출
# --------------------------------------------------------------------------- #
def _extract_from_browser(browser: str) -> Optional[str]:
    """단일 브라우저에서 33m2 쿠키 추출 → 문자열. 실패 시 None(예외 흡수)."""
    try:
        import browser_cookie3 as bc
    except ImportError:
        return None
    fn = getattr(bc, browser, None)
    if fn is None:
        return None
    try:
        jar = fn(domain_name=COOKIE_DOMAIN)
    except Exception:
        # 브라우저 미설치·DB 잠금·복호화키 없음·관리자권한 필요 등 모두 스킵
        return None
    return _jar_to_cookie_str(jar)


def get_session(validate: bool = True) -> Optional[str]:
    """브라우저 로그인 세션 재사용: Edge→Chrome 순 쿠키 추출.

    validate=True면 각 후보를 /v1/user/me 로 검증해 유효한 것만 반환.
    아무 것도 못 얻으면 None(호출측이 앱 로그인으로 폴백).
    """
    for browser in ("edge", "chrome"):
        cs = _extract_from_browser(browser)
        if not cs:
            continue
        if validate and not validate_cookie(cs):
            continue
        return cs
    return None


def detect_source(validate: bool = True) -> Optional[str]:
    """유효 세션을 어느 브라우저에서 얻었는지 라벨 반환('edge'/'chrome') 또는 None."""
    for browser in ("edge", "chrome"):
        cs = _extract_from_browser(browser)
        if cs and (not validate or validate_cookie(cs)):
            return browser
    return None


# --------------------------------------------------------------------------- #
# 2) 앱 내 로그인 (서버가 대신 로그인 → 세션 쿠키만 반환)
# --------------------------------------------------------------------------- #
def _humanize_login_error(resp) -> str:
    try:
        j = resp.json()
    except ValueError:
        return f"로그인 실패(HTTP {resp.status_code})."
    code = j.get("code")
    msg = j.get("message")
    content = msg.get("content") if isinstance(msg, dict) else msg
    if code == "VLD_002":
        return "이메일 또는 비밀번호가 올바르지 않습니다."
    if code == "VLD_001":
        return content or "이메일/비밀번호를 입력해 주세요."
    return content or f"로그인 실패(code {code}, HTTP {resp.status_code})."


def app_login(username: str, password: str, timeout: float = 15.0) -> str:
    """이메일/비밀번호로 33m2 로그인 → 세션 쿠키 문자열 반환.

    비밀번호는 이 함수 호출 스택(메모리)에서만 사용하고 저장·로깅하지 않는다.
    실패 시 LoginError(사람이 읽을 메시지).
    """
    username = (username or "").strip()
    if not username or not password:
        raise LoginError("이메일과 비밀번호를 모두 입력해 주세요.")

    sess = requests.Session()
    sess.cookies = requests.cookies.RequestsCookieJar()
    try:
        r = sess.post(LOGIN_URL, json={"username": username, "password": password},
                      headers={**_BASE_HEADERS, "Content-Type": "application/json"},
                      timeout=timeout)
    except requests.RequestException as e:
        raise LoginError(f"로그인 서버에 연결하지 못했습니다: {e}")

    if r.status_code != 200:
        raise LoginError(_humanize_login_error(r))

    # 성공: 세션 쿠키 수집(요청 세션 jar + 응답 Set-Cookie 병합)
    cookie_str = _jar_to_cookie_str(sess.cookies)
    if not cookie_str:
        # 일부 구현은 응답 바디에 토큰만 줄 수 있음 → 방어
        raise LoginError("로그인은 되었으나 세션 쿠키를 받지 못했습니다. "
                         "쿠키 붙여넣기(고급)로 시도해 주세요.")
    # 최종 유효성 확인
    if not validate_cookie(cookie_str, timeout=timeout):
        raise LoginError("로그인 후 세션 검증에 실패했습니다. 잠시 후 다시 시도해 주세요.")
    return cookie_str


if __name__ == "__main__":
    # 자체 점검: 브라우저 추출이 안전하게 None을 반환하는지(로그인 여부 무관).
    src = detect_source(validate=False)
    print("브라우저 33m2 쿠키 감지:", src or "없음")
    s = get_session()
    print("유효 세션 자동획득:", "성공" if s else "실패(None) — 앱 로그인 필요")
