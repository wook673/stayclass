# -*- coding: utf-8 -*-
"""session_auto.py — 33m2 세션 자동 획득 (쿠키 자동추출 + 앱 내 로그인).

우선순위 3단 폴백(웹/CLI에서 조합해 사용):
  1) 브라우저 쿠키 자동추출  get_session()  — Edge→Chrome 로그인 세션 재사용
  2) 앱 내 로그인            app_login(username, password)  — 서버가 대신 로그인
  3) 쿠키 붙여넣기(최후 수단) — web.py textarea (여기선 미구현)

엔드포인트(JS 번들 정적분석으로 리버스 확정, 2026-07):
  로그인은 REST가 아니라 **Next.js 서버액션(signIn)** 이다.
    POST https://web.33m2.co.kr/ko
      헤더 Next-Action: 7f57b50f3cdf6f3d306c1dede3730e44df51d5d1e2
           Content-Type: text/plain;charset=UTF-8
      바디 [{"username": <이메일>, "password": <평문>, "rememberMe": bool}]
      응답 RSC 플라이트 스트림. 실패 시 한 줄에
           {"serverError":{"code":"AUTH_001","content":"이메일 주소 또는 비밀번호가 일치하지 않습니다"}}
      성공 시 Next 서버가 Set-Cookie 로 세션 쿠키를 내려준다.
    · 비밀번호는 클라이언트 암호화·해시 없음(HTTPS 평문). RSA/공개키 발급 선행요청 없음.
    · CSRF 토큰·캡차 없음. 워밍업 GET이 uuid(디바이스) 쿠키를 심어주나 필수는 아님.
  인증확인 GET https://web.33m2.co.kr/v1/use-auth/user/me  200=유효 / 401 AUTH_002=무효

  ※ 이전 버그: `/v1/user/me`(use-auth 없음)를 썼다 — 이 경로는 **로그인된 브라우저
    세션으로도 항상 401 AUTH_002** 를 돌려주므로 유효한 세션을 전부 무효로 판정했다.
    33m2 API 클라이언트(번들 chunk 4122)의 URL 빌더가 근거다:
        getUrl(endpoint, queryParams, "NONE" !== auth, option)
        -> baseUrl + "/" + version + (authNeeded ? "/use-auth" : "") + endpoint
    즉 auth 가 REQUIRED/OPTIONAL 인 엔드포인트는 **경로에 /use-auth 세그먼트가
    반드시 들어간다**. 번들(chunk 5755)의 실제 호출은
        uE.get({endpoint: "/user/me", auth: Nj.REQUIRED})
    이므로 최종 URL은 `/v1/use-auth/user/me` 다. use-auth 가 없는 `/v1/user/me` 는
    세션을 붙여 검증하는 라우트 자체가 아니므로 자격증명과 무관하게 401이다.

  ※ 직접 REST(POST /v1/user/login)는 필드검증만 통과하고 항상 VLD_002("잘못된 요청입니다")를
    돌려준다 — 자격증명이 맞아도 실패. VLD_002는 '자격증명 오류'가 아니라 '요청 거부'이며,
    실제 자격증명 오류 코드는 AUTH_001 이다. (이전 버그의 원인)

보안: 비밀번호는 메모리에서만 사용하고 파일·로그 어디에도 저장하지 않는다.
쿠키 문자열만 반환(호출측이 session.txt에 저장). 모든 예외는 안전하게 흡수.
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):      # Windows 기본 콘솔(cp949)에서 U+2014 등 출력 크래시 방지
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import json
import re
from typing import Optional

import requests

# Next.js 서버액션(signIn) — 클라이언트 번들의 createServerReference(...,"signIn") id
SIGNIN_ACTION_ID = "7f57b50f3cdf6f3d306c1dede3730e44df51d5d1e2"
# Next.js 앱라우터가 서버액션 호출 시 함께 보내는 라우터 상태 트리(/ko 기준)
NEXT_ROUTER_STATE_TREE = (
    '["",{"children":["(web)",{"children":[["locale","ko","d"],'
    '{"children":["__PAGE__",{}]}]}]},null,null,true]')
ACTION_URL = "https://web.33m2.co.kr/ko"      # 로케일 루트(한국어 에러 메시지)
WARMUP_URL = "https://web.33m2.co.kr/ko"
# 인증확인 엔드포인트. /use-auth 세그먼트가 있어야 세션을 실제로 검증한다(위 주석 참조).
ME_URL = "https://web.33m2.co.kr/v1/use-auth/user/me"
COOKIE_DOMAIN = "33m2.co.kr"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_BASE_HEADERS = {"User-Agent": _UA, "Accept": "application/json",
                 "Referer": "https://web.33m2.co.kr/"}
# 소셜 전용 계정 안내(웹 번들에 소셜 로그인 UI는 없으나 앱 가입 계정 대비)
_SOCIAL_HINT = ("카카오·네이버·애플 등 소셜 계정으로 가입했다면 이메일/비밀번호 "
                "로그인이 안 됩니다 — 브라우저에서 소셜로 로그인한 뒤 "
                "'분석 시작'(브라우저 세션 자동 감지)을 이용하세요.")
# 세션 판별에 의미있는 쿠키 이름 힌트(있으면 우선). 없어도 전체를 문자열로 사용.
_SESSION_HINTS = ("SESSION", "JSESSIONID", "connect.sid", "access", "token",
                  "refresh", "auth")


class LoginError(RuntimeError):
    """앱 내 로그인 실패(자격증명 오류·네트워크 등). 사람이 읽을 메시지 포함."""


# --------------------------------------------------------------------------- #
# 공통: 쿠키 유효성 확인 (가벼운 인증 API 1콜)
# --------------------------------------------------------------------------- #
def validate_cookie(cookie_str: Optional[str], timeout: float = 12.0) -> bool:
    """Cookie 헤더가 33m2 유효 세션인지 GET /v1/use-auth/user/me 로 확인(200=유효).

    401(AUTH_002)=무효. use-auth 없는 `/v1/user/me` 는 로그인 상태에서도 항상 401이라
    세션 판별에 쓸 수 없다(모듈 상단 주석 참조).
    """
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

    validate=True면 각 후보를 /v1/use-auth/user/me 로 검증해 유효한 것만 반환.
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
_SERVER_ERROR_RE = re.compile(r'\{"serverError":\s*(\{.*?\})\}\s*$', re.M)


def _find_action_error(flight_text: str) -> Optional[dict]:
    """RSC 플라이트 응답에서 액션 에러 추출. 없으면 None(성공).

    반환: {"kind":"server", ...serverError}  (백엔드 인증 실패 등)
          {"kind":"validation", "messages":[...]}  (zod 입력 검증 실패)
    """
    for line in flight_text.splitlines():
        if '"serverError"' not in line and '"validationErrors"' not in line:
            continue
        _, _, payload = line.partition(":")   # 'N:{...}' 형태
        try:
            obj = json.loads(payload)
        except ValueError:
            m = _SERVER_ERROR_RE.search(line)
            if not m:
                continue
            try:
                obj = {"serverError": json.loads(m.group(1))}
            except ValueError:
                continue
        if not isinstance(obj, dict):
            continue
        se = obj.get("serverError")
        if isinstance(se, dict):
            return {"kind": "server", **se}
        ve = obj.get("validationErrors")
        if isinstance(ve, dict):
            msgs = []
            for field, detail in ve.items():
                if isinstance(detail, dict):
                    msgs.extend(detail.get("_errors") or [])
            return {"kind": "validation", "messages": msgs}
    return None


def _humanize_login_error(err: dict) -> str:
    """서버가 준 사람이 읽을 메시지를 그대로 쓰고, 필요 시 안내를 덧붙인다."""
    if err.get("kind") == "validation":
        msgs = err.get("messages") or []
        return " / ".join(msgs) if msgs else "입력값을 확인해 주세요."
    code = err.get("code")
    content = err.get("content") or ""
    if code == "AUTH_001":
        base = content or "이메일 주소 또는 비밀번호가 일치하지 않습니다."
        return base + "\n" + _SOCIAL_HINT
    # COMN_003("처리중입니다.") — 웹 클라이언트 번들에 없는 백엔드 전용 코드.
    # 계정별 로그인 처리 잠금/레이트리밋으로 보이며 재시도로는 풀리지 않는 경우가 많다.
    if code == "COMN_003" or "처리중" in content:
        return ("33m2 서버가 \"처리중입니다\"(COMN_003)를 반환했습니다 — 계정에 로그인 "
                "처리 잠금이 걸린 상태입니다.\n"
                "잠시(수 분) 후 다시 시도하시고, 계속 같은 응답이면 앱 로그인 대신 "
                "아래 [브라우저로 로그인하기] → [세션 다시 감지] 경로를 사용하세요.")
    if content:
        return f"{content} (code {code})"
    return f"로그인 실패(code {code})."


def app_login(username: str, password: str, timeout: float = 25.0) -> str:
    """이메일/비밀번호로 33m2 로그인 → 세션 쿠키 문자열 반환.

    브라우저와 동일한 Next.js 서버액션(signIn) 플로우를 사용한다.
    비밀번호는 이 함수 호출 스택(메모리)에서만 사용하고 저장·로깅하지 않는다.
    실패 시 LoginError(사람이 읽을 메시지).
    """
    username = (username or "").strip()
    if not username or not password:
        raise LoginError("이메일과 비밀번호를 모두 입력해 주세요.")

    sess = requests.Session()
    # 워밍업: uuid(디바이스) 쿠키 확보. 본문은 받지 않고 헤더만(대용량 페이지 회피).
    try:
        w = sess.get(WARMUP_URL, headers={"User-Agent": _UA}, timeout=timeout,
                     stream=True)
        w.close()
    except requests.RequestException:
        pass                       # 워밍업 실패는 치명적이지 않음

    # 브라우저 XHR과 최대한 동일한 헤더 세트(서버액션이 헤더 부족 시 처리 미완으로 빠짐)
    headers = {
        "User-Agent": _UA,
        "Accept": "text/x-component",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "text/plain;charset=UTF-8",
        "Next-Action": SIGNIN_ACTION_ID,
        "Next-Router-State-Tree": NEXT_ROUTER_STATE_TREE,
        "Next-Url": "/ko",
        "Origin": "https://web.33m2.co.kr",
        "Referer": "https://web.33m2.co.kr/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", '
                     '"Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    payload = json.dumps([{"username": username, "password": password,
                           "rememberMe": True}], ensure_ascii=False)
    try:
        r = sess.post(ACTION_URL, data=payload.encode("utf-8"), headers=headers,
                      timeout=timeout)
    except requests.RequestException as e:
        raise LoginError(f"로그인 서버에 연결하지 못했습니다: {e}")
    finally:
        del password               # 메모리에서 조기 제거(저장·로깅 없음)
    r.encoding = "utf-8"

    if r.status_code != 200:
        raise LoginError(f"로그인 요청이 거부되었습니다(HTTP {r.status_code}). "
                         "잠시 후 다시 시도해 주세요.")

    err = _find_action_error(r.text)
    if err:
        raise LoginError(_humanize_login_error(err))

    # 성공: Next 서버가 Set-Cookie 로 내려준 세션 쿠키 수집
    cookie_str = _jar_to_cookie_str(sess.cookies)
    if not cookie_str or not validate_cookie(cookie_str, timeout=timeout):
        raise LoginError(
            "로그인은 처리되었으나 유효한 세션 쿠키를 받지 못했습니다.\n"
            + _SOCIAL_HINT)
    return cookie_str


if __name__ == "__main__":
    # 자체 점검: 브라우저 추출이 안전하게 None을 반환하는지(로그인 여부 무관).
    src = detect_source(validate=False)
    print("브라우저 33m2 쿠키 감지:", src or "없음")
    s = get_session()
    print("유효 세션 자동획득:", "성공" if s else "실패(None) — 앱 로그인 필요")
