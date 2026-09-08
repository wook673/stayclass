# -*- coding: utf-8 -*-
"""로컬에서 PDF 등 파일을 첨부해 이메일을 보내는 모듈 (SMTP 직접 발송).

Gmail 커넥터로는 첨부가 불가능하다(첨부 바이트를 모델이 base64 문자열로 옮겨
적어야 하는데 수십만 자를 정확히 재현할 수 없음). 그래서 이 스크립트가
**디스크에서 파일을 직접 읽어** SMTP로 발송한다.

보안 원칙:
    - 앱 비밀번호는 사용자가 직접 routine/email_config.json 에 입력한다.
    - 이 스크립트는 그 값을 읽어 SMTP 로그인에만 쓰고, 콘솔·로그·에러 메시지
      어디에도 출력하지 않는다(마스킹 형태로도 남기지 않는다).
    - 설정 파일은 .gitignore 에 등록되어 있다.

사용:
    python routine/email_send.py --init
    python routine/email_send.py --test
    python routine/email_send.py --subject "제목" --body "본문" \
        --attach routine/out/보고서.pdf --attach routine/out/표지.jpg

모듈:
    from email_send import send_mail
    ok, msg = send_mail("제목", "본문", attachments=["a.pdf"])
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import smtplib
import socket
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Sequence

# ---------------------------------------------------------------- 상수

CONFIG_PATH = Path(__file__).resolve().parent / "email_config.json"

# --init 이 써넣는 안내 문구. 이 문구가 그대로 남아 있으면 "미입력"으로 본다.
PASSWORD_PLACEHOLDER = "여기에 16자리 앱 비밀번호를 붙여넣으세요 (공백 제거)"
USERNAME_PLACEHOLDER = "your@gmail.com"

CONFIG_TEMPLATE: dict[str, Any] = {
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 465,
    "use_ssl": True,
    "username": USERNAME_PLACEHOLDER,
    "app_password": PASSWORD_PLACEHOLDER,
    "from_name": "다니엘스테이",
    "to": [USERNAME_PLACEHOLDER],
}

MAX_TOTAL_ATTACH_BYTES = 25 * 1024 * 1024  # 25MB
SMTP_TIMEOUT = 30

# 확장자 → MIME 타입. 윈도우 레지스트리가 이상한 값을 돌려주는 경우가 있어
# 자주 쓰는 형식은 명시적으로 고정한다.
FORCED_TYPES = {
    ".pdf": ("application", "pdf"),
    ".jpg": ("image", "jpeg"),
    ".jpeg": ("image", "jpeg"),
    ".png": ("image", "png"),
    ".gif": ("image", "gif"),
    ".webp": ("image", "webp"),
    ".html": ("text", "html"),
    ".htm": ("text", "html"),
    ".txt": ("text", "plain"),
    ".csv": ("text", "csv"),
    ".md": ("text", "markdown"),
    ".zip": ("application", "zip"),
    ".json": ("application", "json"),
}

# 종료 코드
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_NOT_CONFIGURED = 2  # 설정 파일 없음 / 앱 비밀번호 미입력 → 조용히 건너뛸 수 있음

SETUP_HINT = (
    "이메일 설정 파일이 없습니다: {path}\n"
    "    python routine/email_send.py --init\n"
    "를 실행해 템플릿을 만든 뒤 값을 채워 넣으세요. "
    "자세한 절차는 routine/EMAIL_SETUP.md 를 참고하세요."
)

NOT_FILLED_HINT = (
    "앱 비밀번호가 아직 입력되지 않았습니다. {path} 를 열어 app_password 항목에 "
    "Google 앱 비밀번호 16자리(공백 제거)를 붙여 넣고 저장하세요. "
    "발급 방법은 routine/EMAIL_SETUP.md 참고."
)

AUTH_HINT = (
    "SMTP 인증에 실패했습니다(535). 앱 비밀번호가 맞는지, 2단계 인증이 켜져 있는지 "
    "확인하세요. 일반 계정 비밀번호가 아니라 myaccount.google.com/apppasswords 에서 "
    "발급한 16자리 앱 비밀번호여야 합니다."
)


class ConfigError(Exception):
    """설정 파일 문제. skippable=True 면 루틴에서 조용히 건너뛰어도 되는 상태."""

    def __init__(self, message: str, skippable: bool = True):
        super().__init__(message)
        self.skippable = skippable


class AttachmentError(Exception):
    """첨부 파일 문제(없음·디렉터리·용량 초과)."""


# ---------------------------------------------------------------- 설정


def init_config(path: Path | str | None = None) -> tuple[bool, str]:
    """설정 템플릿을 만든다. 이미 있으면 덮어쓰지 않는다."""
    target = Path(path) if path else CONFIG_PATH
    if target.exists():
        return False, f"이미 존재합니다(덮어쓰지 않음): {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(CONFIG_TEMPLATE, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return True, (
        f"설정 템플릿을 만들었습니다: {target}\n"
        "이 파일을 열어 username / app_password / to 를 채운 뒤 저장하세요.\n"
        "앱 비밀번호는 누구에게도(작업을 돕는 AI 포함) 알려주지 마세요 — 파일에만 입력합니다."
    )


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """설정을 읽고 검증한다. 문제가 있으면 ConfigError."""
    target = Path(path) if path else CONFIG_PATH
    if not target.exists():
        raise ConfigError(SETUP_HINT.format(path=target), skippable=True)

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(
            f"설정 파일을 읽을 수 없습니다(JSON 형식 오류): {target} — {exc}",
            skippable=False,
        ) from None
    if not isinstance(raw, dict):
        raise ConfigError(f"설정 파일 형식이 올바르지 않습니다: {target}", skippable=False)

    cfg = dict(CONFIG_TEMPLATE)
    cfg.update(raw)

    username = str(cfg.get("username") or "").strip()
    password = str(cfg.get("app_password") or "")

    if not username or username == USERNAME_PLACEHOLDER:
        raise ConfigError(
            f"username 이 아직 입력되지 않았습니다. {target} 를 열어 본인 지메일 주소를 넣으세요.",
            skippable=True,
        )

    # 앱 비밀번호 미입력 판정: 비어 있거나 템플릿 문구 그대로일 때.
    # (여기서도 실제 값은 절대 메시지에 담지 않는다.)
    if not password.strip() or password.strip() == PASSWORD_PLACEHOLDER.strip():
        raise ConfigError(NOT_FILLED_HINT.format(path=target), skippable=True)

    # 사용자가 공백 포함해서 붙여넣는 경우가 흔하다 — 조용히 제거한다.
    cfg["username"] = username
    cfg["app_password"] = "".join(password.split())

    to = cfg.get("to")
    if isinstance(to, str):
        to = [to]
    to = [str(x).strip() for x in (to or []) if str(x).strip()]
    to = [x for x in to if x != USERNAME_PLACEHOLDER]
    if not to:
        to = [username]
    cfg["to"] = to

    try:
        cfg["smtp_port"] = int(cfg.get("smtp_port") or 465)
    except (TypeError, ValueError):
        raise ConfigError(f"smtp_port 값이 숫자가 아닙니다: {target}", skippable=False) from None
    cfg["use_ssl"] = bool(cfg.get("use_ssl", True))
    cfg["smtp_host"] = str(cfg.get("smtp_host") or "smtp.gmail.com").strip()
    cfg["from_name"] = str(cfg.get("from_name") or "").strip()
    return cfg


def _scrub(text: str, secret: str | None) -> str:
    """혹시라도 비밀번호가 섞인 문자열이 밖으로 나가지 않게 제거한다."""
    if not secret:
        return text
    out = text
    for token in (secret, "".join(secret.split())):
        if token:
            out = out.replace(token, "[제거됨]")
    return out


# ---------------------------------------------------------------- 첨부


def _guess_type(path: Path) -> tuple[str, str]:
    ext = path.suffix.lower()
    if ext in FORCED_TYPES:
        return FORCED_TYPES[ext]
    guessed, _ = mimetypes.guess_type(path.name)
    if not guessed or "/" not in guessed:
        return ("application", "octet-stream")
    maintype, _, subtype = guessed.partition("/")
    return (maintype or "application", subtype or "octet-stream")


def resolve_attachments(paths: Sequence[str | Path] | None) -> list[Path]:
    """첨부 경로를 검증한다. 없거나 디렉터리거나 총합 25MB 초과면 AttachmentError."""
    resolved: list[Path] = []
    missing: list[str] = []
    total = 0
    for raw in paths or []:
        p = Path(raw).expanduser()
        if not p.exists():
            missing.append(str(p))
            continue
        if p.is_dir():
            missing.append(f"{p} (디렉터리는 첨부할 수 없습니다)")
            continue
        total += p.stat().st_size
        resolved.append(p)

    if missing:
        raise AttachmentError("첨부 파일을 찾을 수 없습니다:\n  - " + "\n  - ".join(missing))

    if total > MAX_TOTAL_ATTACH_BYTES:
        raise AttachmentError(
            f"첨부 총 용량이 한도를 넘었습니다: {total / 1048576:.1f}MB "
            f"(한도 {MAX_TOTAL_ATTACH_BYTES // 1048576}MB). "
            "파일을 나눠 보내거나 용량을 줄인 뒤 다시 시도하세요."
        )
    return resolved


def build_message(
    subject: str,
    body: str,
    attachments: Sequence[Path],
    to: Sequence[str],
    username: str,
    from_name: str = "",
) -> EmailMessage:
    """한글 제목·본문·한글 파일명이 깨지지 않는 MIME 메시지를 만든다.

    EmailMessage(기본 EmailPolicy)는 제목을 RFC 2047, 비ASCII 첨부 파일명을
    RFC 2231(filename*=utf-8'') 로 인코딩한다.
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{username}>" if from_name else username
    msg["To"] = ", ".join(to)
    # 한글 본문을 8bit 그대로 흘리면 BODY=8BITMIME 을 광고하지 않는 서버에서
    # 깨질 수 있다. 비ASCII면 base64로 감싸 7bit 안전하게 만든다.
    text = body or ""
    msg.set_content(
        text,
        subtype="plain",
        charset="utf-8",
        cte="7bit" if text.isascii() else "base64",
    )

    for path in attachments:
        maintype, subtype = _guess_type(path)
        msg.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )
    return msg


# ---------------------------------------------------------------- 발송


def _connect(cfg: dict[str, Any]) -> smtplib.SMTP:
    """SMTP 연결 + 로그인까지 마친 객체를 돌려준다."""
    host = cfg["smtp_host"]
    port = cfg["smtp_port"]
    context = ssl.create_default_context()
    if cfg["use_ssl"]:
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            host, port, timeout=SMTP_TIMEOUT, context=context
        )
    else:
        server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT)
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
    server.login(cfg["username"], cfg["app_password"])
    return server


def _describe_smtp_error(exc: Exception, secret: str | None) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        code = getattr(exc, "smtp_code", None)
        if code == 535:
            return AUTH_HINT
        return f"SMTP 인증에 실패했습니다(코드 {code}). " + AUTH_HINT
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return f"수신자 주소가 거부되었습니다: {list(exc.recipients)}"
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "발신자 주소가 거부되었습니다. username 이 실제 지메일 주소인지 확인하세요."
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return "SMTP 서버 연결이 끊겼습니다. 잠시 후 다시 시도하세요."
    if isinstance(exc, ssl.SSLError):
        return f"TLS/SSL 오류: {_scrub(str(exc), secret)} — 포트와 use_ssl 설정을 확인하세요."
    if isinstance(exc, socket.gaierror):
        return "네트워크 오류: SMTP 서버 주소를 찾을 수 없습니다(DNS). 인터넷 연결과 smtp_host 를 확인하세요."
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "네트워크 오류: SMTP 서버 응답 시간이 초과되었습니다. 방화벽/포트를 확인하세요."
    if isinstance(exc, OSError):
        return f"네트워크 오류: SMTP 서버에 연결할 수 없습니다 — {_scrub(str(exc), secret)}"
    if isinstance(exc, smtplib.SMTPException):
        return f"SMTP 오류: {_scrub(str(exc), secret)}"
    return f"알 수 없는 오류: {_scrub(str(exc), secret)}"


def send_mail(
    subject: str,
    body: str,
    attachments: Sequence[str | Path] | None = None,
    to: Sequence[str] | str | None = None,
    config_path: Path | str | None = None,
) -> tuple[bool, str]:
    """메일을 보낸다. 반환 (성공여부, 사람이 읽는 메시지).

    비밀번호는 어떤 경로로도 반환 메시지에 담기지 않는다.
    """
    secret: str | None = None
    try:
        cfg = load_config(config_path)
        secret = cfg["app_password"]

        recipients = [to] if isinstance(to, str) else list(to or cfg["to"])
        recipients = [str(x).strip() for x in recipients if str(x).strip()]
        if not recipients:
            return False, "수신자가 없습니다. 설정의 to 항목이나 --to 를 확인하세요."

        files = resolve_attachments(attachments)
        msg = build_message(
            subject, body, files, recipients, cfg["username"], cfg["from_name"]
        )

        server = _connect(cfg)
        try:
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001 - 종료 실패는 발송 결과와 무관
                pass

    except ConfigError as exc:
        return False, str(exc)
    except AttachmentError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - 종류별로 안내 문구를 갈라준다
        return False, _describe_smtp_error(exc, secret)

    attach_note = f", 첨부 {len(files)}건" if files else ""
    return True, f"발송 완료 → {', '.join(recipients)}{attach_note}"


def test_connection(config_path: Path | str | None = None) -> tuple[bool, str]:
    """설정 검증 + 서버 접속·로그인까지만 하고 끝낸다(발송하지 않음)."""
    secret: str | None = None
    try:
        cfg = load_config(config_path)
        secret = cfg["app_password"]
        server = _connect(cfg)
        try:
            server.noop()
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
    except ConfigError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, _describe_smtp_error(exc, secret)

    mode = "SSL" if cfg["use_ssl"] else "STARTTLS"
    return True, (
        f"로그인 성공 — {cfg['smtp_host']}:{cfg['smtp_port']} ({mode}), "
        f"계정 {cfg['username']}, 기본 수신자 {', '.join(cfg['to'])}. 메일은 보내지 않았습니다."
    )


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - 리다이렉트 등으로 불가능하면 그냥 진행
            pass

    parser = argparse.ArgumentParser(
        prog="email_send.py",
        description="로컬 파일을 첨부해 SMTP로 이메일을 보냅니다.",
    )
    parser.add_argument("--subject", default=None, help="메일 제목")
    parser.add_argument("--body", default="", help="메일 본문(평문)")
    parser.add_argument(
        "--attach", action="append", default=[], metavar="PATH",
        help="첨부 파일 경로 (여러 번 지정 가능)",
    )
    parser.add_argument(
        "--to", action="append", default=[], metavar="ADDR",
        help="수신자 (생략 시 설정의 to 사용, 여러 번 지정 가능)",
    )
    parser.add_argument("--config", default=None, help="설정 파일 경로(기본: routine/email_config.json)")
    parser.add_argument("--init", action="store_true", help="설정 템플릿 생성(기존 파일은 덮어쓰지 않음)")
    parser.add_argument("--test", action="store_true", help="설정 검증·로그인까지만 시도하고 종료(발송 안 함)")
    args = parser.parse_args(argv)

    if args.init:
        ok, msg = init_config(args.config)
        print(msg)
        return EXIT_OK if ok else EXIT_FAIL

    if args.test:
        ok, msg = test_connection(args.config)
        if ok:
            print(msg)
            return EXIT_OK
        print(msg, file=sys.stderr)
        return EXIT_NOT_CONFIGURED if _is_skippable(args.config) else EXIT_FAIL

    if not args.subject:
        parser.error("--subject 는 필수입니다 (--init / --test 제외)")

    ok, msg = send_mail(
        args.subject, args.body, args.attach, args.to or None, args.config
    )
    if ok:
        print(msg)
        return EXIT_OK
    print(msg, file=sys.stderr)
    return EXIT_NOT_CONFIGURED if _is_skippable(args.config) else EXIT_FAIL


def _is_skippable(config_path: Path | str | None) -> bool:
    """설정 미비(파일 없음·비밀번호 미입력) 때문인지 판단해 종료코드를 가른다."""
    try:
        load_config(config_path)
    except ConfigError as exc:
        return exc.skippable
    except Exception:  # noqa: BLE001
        return False
    return False


if __name__ == "__main__":
    sys.exit(main())
