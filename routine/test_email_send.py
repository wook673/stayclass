# -*- coding: utf-8 -*-
"""email_send 단위 테스트 (SMTP 전면 모킹 — 실제 발송 없음).

실행: python routine/test_email_send.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from email import message_from_bytes
from email import policy
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import email_send as es  # noqa: E402

REAL_PASSWORD = "abcdefghijklmnop"


def write_config(path: Path, **over) -> dict:
    data = {
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
        "use_ssl": True,
        "username": "boss@gmail.com",
        "app_password": REAL_PASSWORD,
        "from_name": "다니엘스테이",
        "to": ["boss@gmail.com"],
    }
    data.update(over)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


class FakeSMTP:
    """smtplib.SMTP_SSL / SMTP 대역. 마지막 인스턴스를 클래스에 기록한다."""

    last: "FakeSMTP | None" = None
    login_error: Exception | None = None
    send_error: Exception | None = None
    connect_error: Exception | None = None

    def __init__(self, host, port, timeout=None, context=None):
        if FakeSMTP.connect_error:
            raise FakeSMTP.connect_error
        self.host, self.port = host, port
        self.logged_in: tuple[str, str] | None = None
        self.sent: list = []
        self.started_tls = False
        self.quit_called = False
        self.noop_called = False
        FakeSMTP.last = self

    def ehlo(self, *a):
        return (250, b"ok")

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        if FakeSMTP.login_error:
            raise FakeSMTP.login_error
        self.logged_in = (user, password)

    def send_message(self, msg):
        if FakeSMTP.send_error:
            raise FakeSMTP.send_error
        self.sent.append(msg)

    def noop(self):
        self.noop_called = True
        return (250, b"ok")

    def quit(self):
        self.quit_called = True

    @classmethod
    def reset(cls):
        cls.last = None
        cls.login_error = None
        cls.send_error = None
        cls.connect_error = None


class Base(unittest.TestCase):
    def setUp(self):
        FakeSMTP.reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = self.dir / "email_config.json"
        self.patches = [
            mock.patch.object(es.smtplib, "SMTP_SSL", FakeSMTP),
            mock.patch.object(es.smtplib, "SMTP", FakeSMTP),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def make_pdf(self, name="보고서.pdf", size=1024) -> Path:
        p = self.dir / name
        p.write_bytes(b"%PDF-1.4\n" + b"x" * size)
        return p


# ---------------------------------------------------------------- --init


class InitTests(Base):
    def test_creates_template(self):
        ok, msg = es.init_config(self.cfg)
        self.assertTrue(ok)
        data = json.loads(self.cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["smtp_host"], "smtp.gmail.com")
        self.assertEqual(data["smtp_port"], 465)
        self.assertIs(data["use_ssl"], True)
        self.assertEqual(data["app_password"], es.PASSWORD_PLACEHOLDER)
        self.assertIn("email_config.json", msg)

    def test_does_not_overwrite(self):
        self.cfg.write_text('{"username": "keep@me.com"}', encoding="utf-8")
        ok, msg = es.init_config(self.cfg)
        self.assertFalse(ok)
        self.assertIn("덮어쓰지 않음", msg)
        self.assertIn("keep@me.com", self.cfg.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 설정 오류


class ConfigTests(Base):
    def test_missing_file(self):
        ok, msg = es.send_mail("제목", "본문", config_path=self.cfg)
        self.assertFalse(ok)
        self.assertIn("설정 파일이 없습니다", msg)
        self.assertIn("--init", msg)

    def test_placeholder_password_blocks_send(self):
        es.init_config(self.cfg)
        # username 만 채우고 비밀번호는 템플릿 문구 그대로 둔다
        data = json.loads(self.cfg.read_text(encoding="utf-8"))
        data["username"] = "boss@gmail.com"
        data["to"] = ["boss@gmail.com"]
        self.cfg.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        ok, msg = es.send_mail("제목", "본문", config_path=self.cfg)
        self.assertFalse(ok)
        self.assertIn("앱 비밀번호가 아직 입력되지 않았습니다", msg)
        self.assertIsNone(FakeSMTP.last, "발송 시도조차 하면 안 된다")

    def test_empty_password_blocks_send(self):
        write_config(self.cfg, app_password="   ")
        ok, msg = es.send_mail("제목", "본문", config_path=self.cfg)
        self.assertFalse(ok)
        self.assertIn("앱 비밀번호", msg)

    def test_password_spaces_stripped(self):
        write_config(self.cfg, app_password="abcd efgh ijkl mnop")
        ok, _ = es.send_mail("제목", "본문", config_path=self.cfg)
        self.assertTrue(ok)
        self.assertEqual(FakeSMTP.last.logged_in, ("boss@gmail.com", REAL_PASSWORD))

    def test_bad_json(self):
        self.cfg.write_text("{ not json", encoding="utf-8")
        ok, msg = es.send_mail("제목", "본문", config_path=self.cfg)
        self.assertFalse(ok)
        self.assertIn("JSON", msg)


# ------------------------------------------------- 비밀번호가 새지 않는지


class SecrecyTests(Base):
    def _assert_clean(self, *texts):
        for t in texts:
            self.assertNotIn(REAL_PASSWORD, t)
            self.assertNotIn("abcd efgh ijkl mnop", t)

    def test_auth_failure_message_has_no_password(self):
        write_config(self.cfg)
        FakeSMTP.login_error = es.smtplib.SMTPAuthenticationError(
            535, b"5.7.8 Username and Password not accepted"
        )
        ok, msg = es.send_mail("제목", "본문", config_path=self.cfg)
        self.assertFalse(ok)
        self.assertIn("535", msg)
        self.assertIn("2단계 인증", msg)
        self.assertIn("앱 비밀번호가 맞는지", msg)
        self._assert_clean(msg)

    def test_network_error_message_has_no_password(self):
        write_config(self.cfg)
        FakeSMTP.connect_error = OSError(f"connect failed for {REAL_PASSWORD}")
        ok, msg = es.send_mail("제목", "본문", config_path=self.cfg)
        self.assertFalse(ok)
        self.assertIn("네트워크 오류", msg)
        self._assert_clean(msg)

    def test_placeholder_hint_has_no_password(self):
        write_config(self.cfg, app_password=es.PASSWORD_PLACEHOLDER)
        ok, msg = es.send_mail("제목", "본문", config_path=self.cfg)
        self._assert_clean(msg)

    def test_success_message_has_no_password(self):
        write_config(self.cfg)
        ok, msg = es.send_mail("제목", "본문", config_path=self.cfg)
        self.assertTrue(ok)
        self._assert_clean(msg)

    def test_cli_output_has_no_password(self):
        write_config(self.cfg)
        FakeSMTP.login_error = es.smtplib.SMTPAuthenticationError(535, b"nope")
        import io
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            code = es.main(["--subject", "제목", "--body", "본문", "--config", str(self.cfg)])
        self.assertEqual(code, es.EXIT_FAIL)
        self._assert_clean(out.getvalue(), err.getvalue())


# ---------------------------------------------------------------- 첨부


class AttachmentTests(Base):
    def test_missing_attachment(self):
        write_config(self.cfg)
        ok, msg = es.send_mail(
            "제목", "본문", attachments=[str(self.dir / "없는파일.pdf")], config_path=self.cfg
        )
        self.assertFalse(ok)
        self.assertIn("첨부 파일을 찾을 수 없습니다", msg)
        self.assertIsNone(FakeSMTP.last)

    def test_directory_rejected(self):
        write_config(self.cfg)
        ok, msg = es.send_mail("제목", "본문", attachments=[str(self.dir)], config_path=self.cfg)
        self.assertFalse(ok)
        self.assertIn("디렉터리", msg)

    def test_size_guard(self):
        write_config(self.cfg)
        big = self.dir / "big.pdf"
        with big.open("wb") as f:
            f.truncate(es.MAX_TOTAL_ATTACH_BYTES + 1)
        ok, msg = es.send_mail("제목", "본문", attachments=[str(big)], config_path=self.cfg)
        self.assertFalse(ok)
        self.assertIn("첨부 총 용량", msg)
        self.assertIsNone(FakeSMTP.last, "용량 초과는 발송 전에 막아야 한다")

    def test_size_guard_sums_multiple(self):
        write_config(self.cfg)
        paths = []
        for i in range(3):
            p = self.dir / f"p{i}.pdf"
            with p.open("wb") as f:
                f.truncate(9 * 1024 * 1024)  # 3 x 9MB = 27MB
            paths.append(str(p))
        ok, msg = es.send_mail("제목", "본문", attachments=paths, config_path=self.cfg)
        self.assertFalse(ok)
        self.assertIn("27.0MB", msg)

    def test_under_limit_passes(self):
        write_config(self.cfg)
        p = self.make_pdf(size=2 * 1024 * 1024)
        ok, msg = es.send_mail("제목", "본문", attachments=[str(p)], config_path=self.cfg)
        self.assertTrue(ok, msg)
        self.assertIn("첨부 1건", msg)


# ---------------------------------------------------------------- MIME 인코딩


class MimeTests(Base):
    def _send_and_parse(self, subject, body, attachments):
        write_config(self.cfg)
        ok, msg = es.send_mail(subject, body, attachments=attachments, config_path=self.cfg)
        self.assertTrue(ok, msg)
        sent = FakeSMTP.last.sent[0]
        return message_from_bytes(sent.as_bytes(), policy=policy.default), sent.as_bytes()

    def test_korean_subject_encoded_and_roundtrips(self):
        parsed, raw = self._send_and_parse(
            "[다니엘스테이] 수원시 시장조사 — 영통역 (2026-08-22)", "본문 한글", []
        )
        # 원문 한글이 헤더에 날것으로 들어가지 않는다(RFC 2047 인코딩됨)
        self.assertNotIn("수원시".encode("utf-8"), raw.split(b"\r\n\r\n")[0])
        self.assertIn(b"=?utf-8?", raw.lower())
        self.assertEqual(
            str(parsed["Subject"]), "[다니엘스테이] 수원시 시장조사 — 영통역 (2026-08-22)"
        )

    def test_korean_body_roundtrips(self):
        body = "영통역 통합 가동률 61.9%\n전수 14실 · 주간가 중위 33.0만"
        parsed, raw = self._send_and_parse("제목", body, [])
        self.assertEqual(parsed.get_body(preferencelist=("plain",)).get_content().strip(), body)
        # 전송 안전성: 전체 메시지가 7bit clean 이어야 한다
        self.assertTrue(raw.isascii(), "메시지에 8bit 바이트가 남아 있다")

    def test_ascii_body_stays_readable(self):
        parsed, raw = self._send_and_parse("subject", "plain ascii body", [])
        self.assertIn(b"plain ascii body", raw)
        self.assertTrue(raw.isascii())

    def test_korean_filename_rfc2231(self):
        pdf = self.make_pdf("다니엘스테이_수원시_영통역_2026-08-22.pdf")
        parsed, raw = self._send_and_parse("제목", "본문", [str(pdf)])
        parts = list(parsed.iter_attachments())
        self.assertEqual(len(parts), 1)
        att = parts[0]
        self.assertEqual(att.get_content_type(), "application/pdf")
        self.assertEqual(att.get_filename(), "다니엘스테이_수원시_영통역_2026-08-22.pdf")
        # RFC 2231: filename*=utf-8''%EB%8B%A4...
        self.assertIn(b"filename*", raw)
        self.assertIn(b"utf-8''", raw)
        self.assertEqual(att.get_payload(decode=True)[:5], b"%PDF-")

    def test_from_header_uses_from_name(self):
        parsed, _ = self._send_and_parse("제목", "본문", [])
        self.assertEqual(str(parsed["From"]), "다니엘스테이 <boss@gmail.com>")
        self.assertEqual(str(parsed["To"]), "boss@gmail.com")

    def test_mixed_attachment_types(self):
        pdf = self.make_pdf("보고서.pdf")
        jpg = self.dir / "표지.jpg"
        jpg.write_bytes(b"\xff\xd8\xff\xe0jpegdata")
        parsed, _ = self._send_and_parse("제목", "본문", [str(pdf), str(jpg)])
        types = [a.get_content_type() for a in parsed.iter_attachments()]
        self.assertEqual(types, ["application/pdf", "image/jpeg"])
        names = [a.get_filename() for a in parsed.iter_attachments()]
        self.assertEqual(names, ["보고서.pdf", "표지.jpg"])


# ---------------------------------------------------------------- 연결 경로


class TransportTests(Base):
    def test_ssl_path(self):
        write_config(self.cfg, use_ssl=True, smtp_port=465)
        ok, _ = es.send_mail("제목", "본문", config_path=self.cfg)
        self.assertTrue(ok)
        self.assertEqual(FakeSMTP.last.port, 465)
        self.assertFalse(FakeSMTP.last.started_tls)

    def test_starttls_path(self):
        write_config(self.cfg, use_ssl=False, smtp_port=587)
        ok, _ = es.send_mail("제목", "본문", config_path=self.cfg)
        self.assertTrue(ok)
        self.assertEqual(FakeSMTP.last.port, 587)
        self.assertTrue(FakeSMTP.last.started_tls)

    def test_to_override(self):
        write_config(self.cfg)
        ok, msg = es.send_mail("제목", "본문", to=["other@x.com"], config_path=self.cfg)
        self.assertTrue(ok)
        self.assertIn("other@x.com", msg)
        self.assertEqual(str(FakeSMTP.last.sent[0]["To"]), "other@x.com")

    def test_test_connection_does_not_send(self):
        write_config(self.cfg)
        ok, msg = es.test_connection(self.cfg)
        self.assertTrue(ok, msg)
        self.assertTrue(FakeSMTP.last.noop_called)
        self.assertEqual(FakeSMTP.last.sent, [])
        self.assertIn("메일은 보내지 않았습니다", msg)

    def test_test_connection_auth_failure(self):
        write_config(self.cfg)
        FakeSMTP.login_error = es.smtplib.SMTPAuthenticationError(535, b"nope")
        ok, msg = es.test_connection(self.cfg)
        self.assertFalse(ok)
        self.assertIn("2단계 인증", msg)


# ---------------------------------------------------------------- 종료 코드


class ExitCodeTests(Base):
    def _run(self, argv):
        import io
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            code = es.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_no_config_returns_2(self):
        code, _, err = self._run(["--subject", "제목", "--config", str(self.cfg)])
        self.assertEqual(code, es.EXIT_NOT_CONFIGURED)
        self.assertIn("설정 파일이 없습니다", err)

    def test_placeholder_returns_2(self):
        es.init_config(self.cfg)
        data = json.loads(self.cfg.read_text(encoding="utf-8"))
        data["username"] = "boss@gmail.com"
        self.cfg.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        code, _, err = self._run(["--subject", "제목", "--config", str(self.cfg)])
        self.assertEqual(code, es.EXIT_NOT_CONFIGURED)
        self.assertIn("앱 비밀번호", err)
        self.assertNotIn(REAL_PASSWORD, err)

    def test_missing_attachment_returns_1(self):
        write_config(self.cfg)
        code, _, err = self._run(
            ["--subject", "제목", "--attach", str(self.dir / "x.pdf"), "--config", str(self.cfg)]
        )
        self.assertEqual(code, es.EXIT_FAIL)
        self.assertIn("찾을 수 없습니다", err)

    def test_success_returns_0(self):
        write_config(self.cfg)
        pdf = self.make_pdf()
        code, out, _ = self._run(
            ["--subject", "제목", "--body", "본문", "--attach", str(pdf), "--config", str(self.cfg)]
        )
        self.assertEqual(code, es.EXIT_OK)
        self.assertIn("발송 완료", out)

    def test_test_flag_returns_2_when_unconfigured(self):
        code, _, err = self._run(["--test", "--config", str(self.cfg)])
        self.assertEqual(code, es.EXIT_NOT_CONFIGURED)

    def test_init_via_cli(self):
        code, out, _ = self._run(["--init", "--config", str(self.cfg)])
        self.assertEqual(code, es.EXIT_OK)
        self.assertTrue(self.cfg.exists())
        code2, out2, _ = self._run(["--init", "--config", str(self.cfg)])
        self.assertEqual(code2, es.EXIT_FAIL)
        self.assertIn("덮어쓰지 않음", out2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
