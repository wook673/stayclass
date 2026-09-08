# -*- coding: utf-8 -*-
"""카카오톡 '나에게 보내기' 발송 모듈.

루틴(스케줄 태스크) 완료 후 사장님 카톡으로 요약 텍스트와 보고서 이미지를 보낸다.

카카오 API 제약: **파일 첨부(PDF·HTML·ZIP 등)는 지원하지 않는다.**
보낼 수 있는 것은 텍스트 / 링크 / 이미지(업로드 후 URL 참조)뿐이다.
따라서 보고서는 JPG로 렌더링해서 보내고, PDF·HTML 원본은 로컬에만 보관한다.

사용:
    python kakao_notify.py --text "테스트 메시지"
    python kakao_notify.py --text "요약" --link-url "https://..." --link-title "리포트"
    python kakao_notify.py --text "요약" --image 표지.jpg --image 본문.jpg
    python kakao_notify.py --text "요약" --image a.jpg --image-title "표지" \
        --image-desc "다니엘스테이 수원시 리포트"

모듈:
    from kakao_notify import send_text, send_image, send_report
    send_text("스캔 완료")
    send_report("스캔 완료", images=[("cover.jpg", "표지", "수원시")])
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Sequence

try:
    import requests
except ImportError:  # pragma: no cover - 환경 문제
    requests = None  # type: ignore[assignment]

# ---------------------------------------------------------------- 상수

TOKEN_PATH = Path(__file__).resolve().parent / "kakao_token.json"

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
IMAGE_UPLOAD_URL = "https://kapi.kakao.com/v2/api/talk/message/image/upload"

TEXT_LIMIT = 200          # 카카오 text 템플릿 텍스트 상한
FEED_TITLE_LIMIT = 100    # feed content.title 안전 상한
FEED_DESC_LIMIT = 180     # feed content.description 안전 상한
EXPIRY_SKEW_SEC = 300     # 만료 5분 전이면 미리 갱신
HTTP_TIMEOUT = 15
UPLOAD_TIMEOUT = 60       # 이미지 업로드는 본문이 크므로 여유를 준다

IMAGE_MAX_BYTES = 5 * 1024 * 1024   # 이 크기를 넘으면 재인코딩 후 업로드
IMAGE_RESIZE_WIDTH = 1280           # 재인코딩 시 최대 폭 (세로 길이는 그대로 비율 유지)
IMAGE_RESIZE_QUALITY = 80
SEND_INTERVAL_SEC = 1.0             # 연속 발송 사이 대기(카카오 스로틀 배려)

CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}

SETUP_HINT = (
    "카카오 토큰 파일이 없습니다: {path}\n"
    "먼저 아래를 실행해 토큰을 발급하세요.\n"
    "    python routine/kakao_setup.py\n"
    "자세한 준비 절차는 routine/KAKAO_SETUP.md 를 참고하세요."
)


class SendResult(NamedTuple):
    ok: bool
    message: str


class ReportResult(NamedTuple):
    """send_report 집계 결과. details = [(라벨, 성공여부, 메시지), ...]"""

    ok: bool          # 시도한 건이 전부 성공했는가
    sent: int
    failed: int
    message: str      # 사람이 읽는 한 줄 요약
    details: list[tuple[str, bool, str]]


class TokenMissing(Exception):
    """토큰 파일이 없거나 형식이 깨진 경우."""


class ImageUploadError(Exception):
    """이미지 업로드 실패. 메시지는 사람이 읽을 수 있는 안내문."""


# ---------------------------------------------------------------- 유틸


def mask(value: str | None) -> str:
    """토큰을 앞 4자만 남기고 마스킹. 로그/콘솔 출력 전용."""
    if not value:
        return "(none)"
    head = value[:4]
    return f"{head}{'*' * 8}({len(value)}자)"


def truncate(text: str, limit: int = TEXT_LIMIT) -> str:
    """카카오 text 템플릿 상한에 맞춰 말줄임 처리."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------- 토큰 I/O


def load_token(path: Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else TOKEN_PATH
    if not path.exists():
        raise TokenMissing(SETUP_HINT.format(path=path))
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        raise TokenMissing(
            f"토큰 파일을 읽을 수 없습니다 ({path}): {exc}\n"
            "파일을 지우고 python routine/kakao_setup.py 를 다시 실행하세요."
        ) from exc
    if not isinstance(data, dict) or not data.get("access_token"):
        raise TokenMissing(
            f"토큰 파일에 access_token이 없습니다 ({path}).\n"
            "python routine/kakao_setup.py 를 다시 실행하세요."
        )
    return data


def save_token(data: dict[str, Any], path: Path | None = None) -> Path:
    path = Path(path) if path else TOKEN_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    try:  # 윈도우에서는 사실상 무의미하지만 POSIX 대비
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def build_token_record(
    payload: dict[str, Any],
    rest_api_key: str,
    previous: dict[str, Any] | None = None,
    now: float | None = None,
    client_secret: str | None = None,
) -> dict[str, Any]:
    """카카오 토큰 응답 → 저장용 레코드. refresh_token은 새로 오면 교체.

    client_id(REST 키)와 client_secret은 갱신(refresh) 때 다시 필요하므로
    함께 저장한다. 구버전 호환을 위해 rest_api_key 키도 유지한다.
    """
    now = time.time() if now is None else now
    prev = previous or {}
    record: dict[str, Any] = dict(prev)
    record["rest_api_key"] = rest_api_key or prev.get("rest_api_key", "")
    record["client_id"] = (
        rest_api_key or prev.get("client_id") or prev.get("rest_api_key", "")
    )
    secret = client_secret if client_secret else prev.get("client_secret")
    if secret:
        record["client_secret"] = secret
    record["access_token"] = payload["access_token"]
    record["token_type"] = payload.get("token_type", "bearer")
    record["expires_at"] = now + float(payload.get("expires_in", 21600))
    record["obtained_at"] = now
    if payload.get("refresh_token"):
        record["refresh_token"] = payload["refresh_token"]
        record["refresh_token_expires_at"] = now + float(
            payload.get("refresh_token_expires_in", 60 * 60 * 24 * 60)
        )
    elif payload.get("refresh_token_expires_in"):
        record["refresh_token_expires_at"] = now + float(
            payload["refresh_token_expires_in"]
        )
    if payload.get("scope"):
        record["scope"] = payload["scope"]
    return record


def token_credentials(token: dict[str, Any]) -> tuple[str, str | None]:
    """토큰 파일에서 (client_id, client_secret)을 뽑는다.

    구버전 파일에는 client_id가 없고 rest_api_key만 있으므로 폴백한다.
    client_secret은 시크릿이 꺼진 앱이면 아예 없을 수 있다(정상).
    """
    client_id = token.get("client_id") or token.get("rest_api_key") or ""
    client_secret = token.get("client_secret") or None
    return client_id, client_secret


def is_expired(token: dict[str, Any], now: float | None = None) -> bool:
    now = time.time() if now is None else now
    expires_at = token.get("expires_at")
    if not expires_at:
        return True
    return now >= float(expires_at) - EXPIRY_SKEW_SEC


# ---------------------------------------------------------------- 에러 해석


def explain_token_error(
    status: int, body: dict[str, Any], sent_secret: bool = False
) -> str:
    code = str(body.get("error") or "")
    desc = str(body.get("error_description") or "")
    if code == "invalid_grant" or "KOE322" in desc or "expired" in desc.lower():
        return (
            f"[HTTP {status}/{code}] refresh_token이 만료·폐기되었습니다"
            " (2개월 이상 미사용 시 발생).\n"
            "→ python routine/kakao_setup.py 를 다시 실행해 재인증하세요."
        )
    if code == "invalid_client" or "KOE101" in desc:
        if sent_secret:
            return (
                f"[HTTP {status}/{code}] client_id 또는 client_secret이 앱과 맞지 않습니다.\n"
                "→ developers.kakao.com > 앱 > 플랫폼 키 > REST API 키 / 클라이언트 시크릿을"
                " 확인하고\n"
                "  python routine/kakao_setup.py --secret <CLIENT_SECRET> 로 다시 저장하세요."
            )
        return (
            f"[HTTP {status}/{code}] REST API 키가 잘못됐거나, 앱에 '클라이언트 시크릿'이"
            " 활성화돼 있는데 저장된 시크릿이 없습니다.\n"
            "→ setup을 다시 실행해 client_id/secret을 저장하세요:\n"
            "  python routine/kakao_setup.py --secret <CLIENT_SECRET>\n"
            "  (콘솔 경로: 앱 > 플랫폼 키 > REST API 키 > 클라이언트 시크릿)"
        )
    return f"[HTTP {status}/{code}] 토큰 갱신 실패: {desc or body}"


def explain_send_error(status: int, body: dict[str, Any]) -> str:
    code = body.get("code")
    msg = str(body.get("msg") or body)
    mapping = {
        -401: (
            "액세스 토큰이 유효하지 않습니다(만료·폐기).\n"
            "→ 자동 갱신도 실패했다면 python routine/kakao_setup.py 재실행이 필요합니다."
        ),
        -402: (
            "권한(scope)이 없습니다 — 카카오톡 메시지 전송(talk_message) 동의항목이 빠졌습니다.\n"
            "→ developers.kakao.com > 동의항목에서 talk_message를 '이용 중 동의'로 켜고"
            " setup을 다시 실행하세요."
        ),
        -403: "요청 권한이 없습니다. 앱 설정(카카오 로그인/동의항목)을 확인하세요.",
        -2: "요청 파라미터 오류입니다(template_object 형식 확인).",
        -1: "카카오 플랫폼 일시 장애·점검입니다. 잠시 후 재시도하세요.",
        -10: "일일 메시지 발송 한도를 초과했습니다.",
    }
    if status == 401 and code is None:
        return f"[HTTP 401] 인증 실패: {msg}"
    hint = mapping.get(code)
    if hint:
        return f"[HTTP {status}/code {code}] {hint}"
    return f"[HTTP {status}/code {code}] 카카오 전송 실패: {msg}"


# ---------------------------------------------------------------- 핵심 로직


def refresh_access_token(
    token: dict[str, Any], path: Path | None = None
) -> tuple[dict[str, Any] | None, str]:
    """refresh_token으로 access_token 갱신 후 파일 갱신.

    반환: (갱신된 토큰 dict | None, 사람이 읽는 메시지)
    """
    refresh_token = token.get("refresh_token")
    client_id, client_secret = token_credentials(token)
    if not refresh_token:
        return None, (
            "refresh_token이 없어 자동 갱신할 수 없습니다.\n"
            "→ python routine/kakao_setup.py 를 실행하세요."
        )
    if not client_id:
        return None, (
            "토큰 파일에 client_id(REST API 키)가 없어 갱신할 수 없습니다.\n"
            "→ setup을 다시 실행해 client_id/secret을 저장하세요:\n"
            "  python routine/kakao_setup.py"
        )

    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }
    if client_secret:
        data["client_secret"] = client_secret

    try:
        resp = requests.post(TOKEN_URL, data=data, timeout=HTTP_TIMEOUT)
    except Exception as exc:  # 네트워크 장애
        return None, f"토큰 갱신 요청 실패(네트워크): {exc}"

    body = _json_or_empty(resp)
    if resp.status_code != 200 or not body.get("access_token"):
        return None, explain_token_error(
            resp.status_code, body, sent_secret=bool(client_secret)
        )

    updated = build_token_record(
        body, client_id, previous=token, client_secret=client_secret
    )
    save_token(updated, path)
    return updated, f"access_token 갱신 완료 {mask(updated['access_token'])}"


def build_template(
    text: str, link_url: str | None = None, link_title: str | None = None
) -> dict[str, Any]:
    link: dict[str, Any] = {}
    if link_url:
        link = {"web_url": link_url, "mobile_web_url": link_url}
    template: dict[str, Any] = {
        "object_type": "text",
        "text": truncate(text),
        # 카카오 요구사항: link 필드는 필수. URL이 없으면 빈 객체로 둔다.
        "link": link,
    }
    if link_url and link_title:
        template["button_title"] = truncate(link_title, 14)
    return template


def send(
    text: str,
    link_url: str | None = None,
    link_title: str | None = None,
    path: Path | None = None,
) -> SendResult:
    """카톡 나에게 보내기. (성공여부, 사람이 읽는 메시지) 반환."""
    if requests is None:
        return SendResult(False, "requests 패키지가 없습니다: pip install requests")

    try:
        token = load_token(path)
    except TokenMissing as exc:
        return SendResult(False, str(exc))

    notes: list[str] = []
    if is_expired(token):
        refreshed, msg = refresh_access_token(token, path)
        notes.append(msg)
        if refreshed is None:
            return SendResult(False, msg)
        token = refreshed

    template = build_template(text, link_url, link_title)
    ok, msg = _post_memo(token, template)
    if ok:
        return SendResult(True, msg)

    # 만료 판정이 어긋난 경우(-401) 한 번만 갱신 후 재시도
    if is_auth_failure(msg):
        refreshed, rmsg = refresh_access_token(token, path)
        notes.append(rmsg)
        if refreshed is None:
            return SendResult(False, rmsg)
        ok, msg = _post_memo(refreshed, template)
    return SendResult(ok, msg)


def _post_memo(token: dict[str, Any], template: dict[str, Any]) -> tuple[bool, str]:
    try:
        resp = requests.post(
            MEMO_URL,
            headers={"Authorization": f"Bearer {token['access_token']}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            timeout=HTTP_TIMEOUT,
        )
    except Exception as exc:
        return False, f"카카오 전송 요청 실패(네트워크): {exc}"

    body = _json_or_empty(resp)
    if resp.status_code == 200 and body.get("result_code") in (0, "0", None):
        return True, "카카오톡 발송 성공"
    return False, explain_send_error(resp.status_code, body)


def _json_or_empty(resp: Any) -> dict[str, Any]:
    try:
        data = resp.json()
    except Exception:
        return {"raw": getattr(resp, "text", "")[:300]}
    return data if isinstance(data, dict) else {"raw": data}


def is_auth_failure(message: str) -> bool:
    """전송/업로드 실패 메시지가 '토큰 문제'인지 판정(→ 1회 갱신 후 재시도)."""
    return "-401" in message or "HTTP 401" in message


# ---------------------------------------------------------------- 이미지


def content_type_for(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def prepare_image(
    image_path: Path | str, max_bytes: int | None = None
) -> tuple[Path, str | None]:
    """업로드 전 용량 가드. (업로드에 쓸 경로, 안내 메시지 | None) 반환.

    파일이 max_bytes를 넘으면 Pillow로 폭·품질을 낮춘 **임시 JPG**를 새로 만든다.
    원본 파일은 절대 건드리지 않는다. 세로가 아주 긴 이미지도 비율을 유지한 채
    그대로 보낸다(2995px 발송 성공 확인됨).

    반환된 경로가 원본과 다르면 호출자가 사용 후 지워야 한다(cleanup_temp 사용).
    """
    max_bytes = IMAGE_MAX_BYTES if max_bytes is None else max_bytes
    src = Path(image_path)
    if not src.exists():
        raise ImageUploadError(f"이미지 파일이 없습니다: {src}")
    size = src.stat().st_size
    if size <= max_bytes:
        return src, None

    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return src, (
            f"경고: {src.name} 이(가) {size / 1048576:.1f}MB로 큽니다."
            " Pillow가 없어 원본 그대로 업로드합니다 (pip install pillow)."
        )

    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            width, height = im.size
            if width > IMAGE_RESIZE_WIDTH:
                new_height = max(1, round(height * IMAGE_RESIZE_WIDTH / width))
                im = im.resize((IMAGE_RESIZE_WIDTH, new_height), Image.LANCZOS)
            fd, tmp_name = tempfile.mkstemp(prefix="kakao_img_", suffix=".jpg")
            os.close(fd)
            tmp = Path(tmp_name)
            im.save(tmp, format="JPEG", quality=IMAGE_RESIZE_QUALITY, optimize=True)
    except Exception as exc:  # 손상된 파일·인코딩 실패 등
        return src, (
            f"경고: {src.name} 재인코딩 실패({exc}). 원본 그대로 업로드합니다."
        )

    new_size = tmp.stat().st_size
    return tmp, (
        f"{src.name}: {size / 1048576:.1f}MB → {new_size / 1048576:.1f}MB 로 재인코딩"
        f" (최대 폭 {IMAGE_RESIZE_WIDTH}px, 품질 {IMAGE_RESIZE_QUALITY}). 원본은 그대로 보존."
    )


def cleanup_temp(original: Path | str, used: Path) -> None:
    """prepare_image가 임시 파일을 만들었다면 지운다."""
    if Path(original) == Path(used):
        return
    try:
        Path(used).unlink()
    except OSError:
        pass


def _post_image_upload(
    token: dict[str, Any], image_path: Path
) -> tuple[bool, str, dict[str, Any] | None]:
    try:
        with open(image_path, "rb") as fp:
            resp = requests.post(
                IMAGE_UPLOAD_URL,
                headers={"Authorization": f"Bearer {token['access_token']}"},
                files={"file": (image_path.name, fp, content_type_for(image_path))},
                timeout=UPLOAD_TIMEOUT,
            )
    except OSError as exc:
        return False, f"이미지 파일을 열 수 없습니다 ({image_path}): {exc}", None
    except Exception as exc:
        return False, f"이미지 업로드 요청 실패(네트워크): {exc}", None

    body = _json_or_empty(resp)
    if resp.status_code == 200:
        original = (body.get("infos") or {}).get("original") or {}
        if original.get("url"):
            return (
                True,
                f"이미지 업로드 성공 ({original.get('width')}x{original.get('height')})",
                {
                    "url": original["url"],
                    "width": int(original.get("width") or 0),
                    "height": int(original.get("height") or 0),
                    "length": original.get("length"),
                    "content_type": original.get("content_type"),
                },
            )
        return False, f"이미지 업로드 응답에 url이 없습니다: {body}", None
    return False, explain_send_error(resp.status_code, body), None


def upload_image(
    image_path: Path | str, path: Path | None = None
) -> dict[str, Any]:
    """이미지를 카카오 서버에 올리고 {'url','width','height', ...} 반환.

    실패하면 ImageUploadError(사람이 읽는 안내문)를 던진다.
    토큰이 만료돼 있으면 미리 갱신하고, 발송 중 401이 나면 1회 갱신 후 재시도한다.
    """
    if requests is None:
        raise ImageUploadError("requests 패키지가 없습니다: pip install requests")

    try:
        token = load_token(path)
    except TokenMissing as exc:
        raise ImageUploadError(str(exc)) from exc

    if is_expired(token):
        refreshed, msg = refresh_access_token(token, path)
        if refreshed is None:
            raise ImageUploadError(msg)
        token = refreshed

    src = Path(image_path)
    upload_path, note = prepare_image(src)
    try:
        ok, msg, info = _post_image_upload(token, upload_path)
        if not ok and is_auth_failure(msg):
            refreshed, rmsg = refresh_access_token(token, path)
            if refreshed is None:
                raise ImageUploadError(rmsg)
            ok, msg, info = _post_image_upload(refreshed, upload_path)
        if not ok or info is None:
            raise ImageUploadError(f"{src.name} 업로드 실패: {msg}")
    finally:
        cleanup_temp(src, upload_path)

    if note:
        info["note"] = note
    return info


def build_image_template(
    info: dict[str, Any],
    title: str,
    description: str = "",
    link_url: str | None = None,
) -> dict[str, Any]:
    """업로드 결과 → feed 템플릿(실측으로 발송 확인된 형태)."""
    link: dict[str, Any] = {}
    if link_url:
        link = {"web_url": link_url, "mobile_web_url": link_url}
    return {
        "object_type": "feed",
        "content": {
            "title": truncate(title, FEED_TITLE_LIMIT),
            "description": truncate(description or "", FEED_DESC_LIMIT),
            "image_url": info["url"],
            "image_width": info["width"],
            "image_height": info["height"],
            # 카카오 요구사항: link 필드는 필수. URL이 없으면 빈 객체(최소값)로 둔다.
            "link": link,
        },
    }


def send_image(
    image_path: Path | str,
    title: str | None = None,
    description: str = "",
    link_url: str | None = None,
    path: Path | None = None,
) -> SendResult:
    """이미지 1장을 업로드해 feed 템플릿으로 '나에게 보내기'."""
    if requests is None:
        return SendResult(False, "requests 패키지가 없습니다: pip install requests")

    src = Path(image_path)
    label = title or src.stem

    try:
        info = upload_image(src, path)
    except (ImageUploadError, TokenMissing) as exc:
        return SendResult(False, str(exc))

    try:
        token = load_token(path)
    except TokenMissing as exc:
        return SendResult(False, str(exc))

    template = build_image_template(info, label, description, link_url)
    ok, msg = _post_memo(token, template)
    if not ok and is_auth_failure(msg):
        refreshed, rmsg = refresh_access_token(token, path)
        if refreshed is None:
            return SendResult(False, rmsg)
        ok, msg = _post_memo(refreshed, template)

    if not ok:
        return SendResult(False, f"{src.name} 발송 실패: {msg}")
    note = f" ({info['note']})" if info.get("note") else ""
    return SendResult(
        True, f"이미지 발송 성공: {src.name} {info['width']}x{info['height']}{note}"
    )


def normalize_images(
    images: Iterable[Any] | None,
) -> list[tuple[Path, str, str]]:
    """(path, title, desc) / (path, title) / path 를 모두 받아 3-튜플로 정규화."""
    out: list[tuple[Path, str, str]] = []
    for item in images or []:
        if isinstance(item, (str, Path)):
            item = (item,)
        parts: Sequence[Any] = tuple(item)
        src = Path(parts[0])
        title = str(parts[1]) if len(parts) > 1 and parts[1] else src.stem
        desc = str(parts[2]) if len(parts) > 2 and parts[2] else ""
        out.append((src, title, desc))
    return out


def send_report(
    text: str | None,
    images: Iterable[Any] | None = None,
    link_url: str | None = None,
    link_title: str | None = None,
    path: Path | None = None,
    interval: float = SEND_INTERVAL_SEC,
) -> ReportResult:
    """요약 텍스트 1건 → 이미지들을 순서대로 발송.

    요청 사이에 interval초 대기하고, 일부가 실패해도 나머지는 계속 보낸다.
    """
    details: list[tuple[str, bool, str]] = []
    first = True

    if text:
        result = send(text, link_url, link_title, path)
        details.append(("텍스트 요약", result.ok, result.message))
        first = False

    for src, title, desc in normalize_images(images):
        if not first:
            time.sleep(interval)
        first = False
        result = send_image(src, title, desc, path=path)
        details.append((src.name, result.ok, result.message))

    sent = sum(1 for _, ok, _ in details if ok)
    failed = len(details) - sent
    if not details:
        return ReportResult(False, 0, 0, "보낼 내용이 없습니다(텍스트·이미지 모두 없음).", [])

    lines = [f"{'OK ' if ok else 'FAIL'} {label}: {msg}" for label, ok, msg in details]
    summary = f"발송 {sent}건 성공 / {failed}건 실패\n" + "\n".join(lines)
    return ReportResult(failed == 0, sent, failed, summary, details)


def send_text(
    text: str, link_url: str | None = None, link_title: str | None = None
) -> bool:
    """단순 불리언 인터페이스. 실패 사유는 stderr로 출력."""
    result = send(text, link_url, link_title)
    if not result.ok:
        print(result.message, file=sys.stderr)
    return result.ok


# ---------------------------------------------------------------- CLI


def pair_image_args(
    paths: Sequence[str],
    titles: Sequence[str] | None,
    descs: Sequence[str] | None,
) -> list[tuple[Path, str, str]]:
    """--image / --image-title / --image-desc 를 순서대로 짝짓는다.

    제목·설명이 모자라면 제목은 파일명(확장자 제외), 설명은 빈 문자열로 채운다.
    """
    titles = list(titles or [])
    descs = list(descs or [])
    out: list[tuple[Path, str, str]] = []
    for i, raw in enumerate(paths):
        src = Path(raw)
        title = titles[i] if i < len(titles) and titles[i] else src.stem
        desc = descs[i] if i < len(descs) and descs[i] else ""
        out.append((src, title, desc))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kakao_notify.py",
        description=(
            "카카오톡 '나에게 보내기'로 텍스트와 보고서 이미지를 발송합니다. "
            "카카오 API는 PDF 등 파일 첨부를 지원하지 않으므로 이미지·텍스트·링크만 보낼 수 있습니다."
        ),
    )
    parser.add_argument("--text", required=True, help="보낼 텍스트 (200자 초과 시 말줄임)")
    parser.add_argument("--link-url", default=None, help="버튼/링크 URL (선택)")
    parser.add_argument("--link-title", default=None, help="버튼 문구 (선택, 14자 이내)")
    parser.add_argument(
        "--image",
        action="append",
        default=None,
        metavar="PATH",
        help="보낼 이미지 경로. 여러 번 지정하면 지정한 순서대로 발송합니다.",
    )
    parser.add_argument(
        "--image-title",
        action="append",
        default=None,
        metavar="TITLE",
        help="이미지 제목. --image 와 순서대로 짝지어집니다(부족하면 파일명 사용).",
    )
    parser.add_argument(
        "--image-desc",
        action="append",
        default=None,
        metavar="DESC",
        help="이미지 설명. --image 와 순서대로 짝지어집니다(부족하면 비움).",
    )
    parser.add_argument(
        "--token-file", default=None, help=f"토큰 파일 경로 (기본: {TOKEN_PATH})"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="성공 메시지를 출력하지 않음"
    )
    args = parser.parse_args(argv)

    path = Path(args.token_file) if args.token_file else None
    try:
        load_token(path)
    except TokenMissing as exc:
        print(str(exc), file=sys.stderr)
        return 2  # 토큰 없음 = 조용히 건너뛸 수 있는 코드

    if args.image:
        images = pair_image_args(args.image, args.image_title, args.image_desc)
        report = send_report(args.text, images, args.link_url, args.link_title, path)
        stream = sys.stdout if report.ok else sys.stderr
        if not (report.ok and args.quiet):
            print(report.message, file=stream)
        return 0 if report.ok else 1

    result = send(args.text, args.link_url, args.link_title, path)
    if result.ok:
        if not args.quiet:
            print(result.message)
        return 0
    print(result.message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
