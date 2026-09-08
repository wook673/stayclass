# -*- coding: utf-8 -*-
"""kakao_notify 단위 테스트 (네트워크 모킹).

실행: python routine/test_kakao_notify.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kakao_notify as kn  # noqa: E402


class FakeResp:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


def write_token(path: Path, **over):
    data = {
        "rest_api_key": "abcdef0123456789abcdef0123456789",
        "access_token": "ACCESS_OLD_TOKEN",
        "refresh_token": "REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
        "refresh_token_expires_at": time.time() + 60 * 60 * 24 * 30,
        "token_type": "bearer",
    }
    data.update(over)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


class TokenFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "kakao_token.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_guidance_not_crash(self):
        result = kn.send("x", path=self.path)
        self.assertFalse(result.ok)
        self.assertIn("kakao_setup.py", result.message)

    def test_cli_exit_code_2_without_token(self):
        code = kn.main(["--text", "x", "--token-file", str(self.path)])
        self.assertEqual(code, 2)

    def test_broken_json_is_handled(self):
        self.path.write_text("{not json", encoding="utf-8")
        result = kn.send("x", path=self.path)
        self.assertFalse(result.ok)
        self.assertIn("읽을 수 없습니다", result.message)

    def test_save_and_load_roundtrip(self):
        record = kn.build_token_record(
            {
                "access_token": "A" * 20,
                "refresh_token": "R" * 20,
                "expires_in": 21599,
                "refresh_token_expires_in": 5183999,
                "scope": "talk_message",
            },
            "KEY123",
        )
        kn.save_token(record, self.path)
        loaded = kn.load_token(self.path)
        self.assertEqual(loaded["access_token"], "A" * 20)
        self.assertEqual(loaded["rest_api_key"], "KEY123")
        self.assertFalse(kn.is_expired(loaded))


class TruncateAndTemplateTests(unittest.TestCase):
    def test_truncate_under_limit(self):
        self.assertEqual(kn.truncate("짧은 글"), "짧은 글")

    def test_truncate_over_limit(self):
        text = "가" * 300
        out = kn.truncate(text)
        self.assertEqual(len(out), kn.TEXT_LIMIT)
        self.assertTrue(out.endswith("…"))

    def test_template_without_link_has_empty_link_object(self):
        tpl = kn.build_template("본문")
        self.assertEqual(tpl["object_type"], "text")
        self.assertEqual(tpl["link"], {})

    def test_template_with_link(self):
        tpl = kn.build_template("본문", "https://example.com", "리포트 열기")
        self.assertEqual(tpl["link"]["web_url"], "https://example.com")
        self.assertEqual(tpl["link"]["mobile_web_url"], "https://example.com")
        self.assertEqual(tpl["button_title"], "리포트 열기")


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "kakao_token.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_expired_token_triggers_refresh_then_sends(self):
        write_token(self.path, expires_at=time.time() - 10)
        calls = []

        def fake_post(url, **kw):
            calls.append((url, kw))
            if url == kn.TOKEN_URL:
                return FakeResp(
                    200,
                    {
                        "access_token": "ACCESS_NEW_TOKEN",
                        "refresh_token": "REFRESH_NEW",
                        "expires_in": 21599,
                        "refresh_token_expires_in": 5183999,
                        "token_type": "bearer",
                    },
                )
            return FakeResp(200, {"result_code": 0})

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            result = kn.send("요약", path=self.path)

        self.assertTrue(result.ok, result.message)
        self.assertEqual(calls[0][0], kn.TOKEN_URL)
        self.assertEqual(calls[0][1]["data"]["grant_type"], "refresh_token")
        self.assertEqual(calls[1][0], kn.MEMO_URL)
        self.assertEqual(
            calls[1][1]["headers"]["Authorization"], "Bearer ACCESS_NEW_TOKEN"
        )
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["access_token"], "ACCESS_NEW_TOKEN")
        self.assertEqual(saved["refresh_token"], "REFRESH_NEW")

    def test_refresh_keeps_old_refresh_token_when_not_returned(self):
        write_token(self.path, expires_at=time.time() - 10)

        def fake_post(url, **kw):
            if url == kn.TOKEN_URL:
                return FakeResp(
                    200, {"access_token": "ACCESS_NEW", "expires_in": 21599}
                )
            return FakeResp(200, {"result_code": 0})

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            self.assertTrue(kn.send("요약", path=self.path).ok)

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["refresh_token"], "REFRESH_TOKEN")

    def test_valid_token_skips_refresh(self):
        write_token(self.path)
        urls = []

        def fake_post(url, **kw):
            urls.append(url)
            return FakeResp(200, {"result_code": 0})

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            self.assertTrue(kn.send("요약", path=self.path).ok)
        self.assertEqual(urls, [kn.MEMO_URL])

    def test_refresh_token_expired_gives_setup_hint(self):
        write_token(self.path, expires_at=time.time() - 10)

        def fake_post(url, **kw):
            return FakeResp(
                400,
                {"error": "invalid_grant", "error_description": "refresh token expired"},
            )

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            result = kn.send("요약", path=self.path)
        self.assertFalse(result.ok)
        self.assertIn("kakao_setup.py", result.message)

    def test_401_during_send_retries_once_after_refresh(self):
        write_token(self.path)
        seq = []

        def fake_post(url, **kw):
            seq.append(url)
            if url == kn.TOKEN_URL:
                return FakeResp(200, {"access_token": "ACCESS_NEW", "expires_in": 21599})
            if seq.count(kn.MEMO_URL) == 1:
                return FakeResp(401, {"code": -401, "msg": "this access token does not exist"})
            return FakeResp(200, {"result_code": 0})

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            result = kn.send("요약", path=self.path)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(seq, [kn.MEMO_URL, kn.TOKEN_URL, kn.MEMO_URL])


class ClientSecretTests(unittest.TestCase):
    """클라이언트 시크릿이 활성화된 앱 대응."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "kakao_token.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_refresh_includes_client_secret_when_saved(self):
        write_token(
            self.path,
            expires_at=time.time() - 10,
            client_id="CLIENT_ID_KEY",
            client_secret="SECRET_VALUE",
        )
        calls = []

        def fake_post(url, **kw):
            calls.append((url, kw))
            if url == kn.TOKEN_URL:
                return FakeResp(200, {"access_token": "ACCESS_NEW", "expires_in": 21599})
            return FakeResp(200, {"result_code": 0})

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            result = kn.send("요약", path=self.path)

        self.assertTrue(result.ok, result.message)
        sent = calls[0][1]["data"]
        self.assertEqual(sent["client_id"], "CLIENT_ID_KEY")
        self.assertEqual(sent["client_secret"], "SECRET_VALUE")
        # 갱신 후에도 자격증명이 파일에 남아 있어야 다음 갱신이 된다.
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["client_secret"], "SECRET_VALUE")
        self.assertEqual(saved["client_id"], "CLIENT_ID_KEY")

    def test_legacy_token_without_client_id_falls_back_to_rest_api_key(self):
        write_token(self.path, expires_at=time.time() - 10)  # client_id 없음(구버전)
        calls = []

        def fake_post(url, **kw):
            calls.append((url, kw))
            if url == kn.TOKEN_URL:
                return FakeResp(200, {"access_token": "ACCESS_NEW", "expires_in": 21599})
            return FakeResp(200, {"result_code": 0})

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            result = kn.send("요약", path=self.path)

        self.assertTrue(result.ok, result.message)
        sent = calls[0][1]["data"]
        self.assertEqual(sent["client_id"], "abcdef0123456789abcdef0123456789")
        self.assertNotIn("client_secret", sent)

    def test_invalid_client_without_secret_tells_user_to_rerun_setup(self):
        write_token(self.path, expires_at=time.time() - 10)

        def fake_post(url, **kw):
            return FakeResp(
                401,
                {"error": "invalid_client", "error_description": "Bad client credentials"},
            )

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            result = kn.send("요약", path=self.path)

        self.assertFalse(result.ok)
        self.assertIn("client_id/secret", result.message)
        self.assertIn("--secret", result.message)

    def test_token_credentials_prefers_client_id(self):
        cid, sec = kn.token_credentials(
            {"client_id": "NEW", "rest_api_key": "OLD", "client_secret": "S"}
        )
        self.assertEqual((cid, sec), ("NEW", "S"))
        self.assertEqual(kn.token_credentials({"rest_api_key": "OLD"}), ("OLD", None))


# ---------------------------------------------------------------- 이미지 발송


def make_jpg(path: Path, size=(40, 60), color=(200, 30, 30)) -> Path:
    from PIL import Image

    Image.new("RGB", size, color).save(path, format="JPEG", quality=95)
    return path


UPLOAD_OK = {
    "infos": {
        "original": {
            "url": "https://k.kakaocdn.net/dn/abc/img.jpg",
            "width": 1280,
            "height": 2995,
            "length": 467000,
            "content_type": "image/jpeg",
        }
    }
}


class ImageBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "kakao_token.json"
        write_token(self.path)
        self.jpg = make_jpg(self.dir / "본문_1.jpg")

    def tearDown(self):
        self.tmp.cleanup()

    def leftover_temp_files(self):
        return list(Path(tempfile.gettempdir()).glob("kakao_img_*"))


class UploadImageTests(ImageBase):
    def test_upload_returns_url_and_dimensions(self):
        calls = []

        def fake_post(url, **kw):
            calls.append((url, kw))
            return FakeResp(200, UPLOAD_OK)

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            info = kn.upload_image(self.jpg, path=self.path)

        self.assertEqual(info["url"], "https://k.kakaocdn.net/dn/abc/img.jpg")
        self.assertEqual((info["width"], info["height"]), (1280, 2995))
        url, kw = calls[0]
        self.assertEqual(url, kn.IMAGE_UPLOAD_URL)
        self.assertEqual(kw["headers"]["Authorization"], "Bearer ACCESS_OLD_TOKEN")
        # multipart 'file' 필드로 올라가야 한다
        self.assertIn("file", kw["files"])
        name, _fp, ctype = kw["files"]["file"]
        self.assertEqual(name, "본문_1.jpg")
        self.assertEqual(ctype, "image/jpeg")

    def test_missing_file_raises_readable_error(self):
        with self.assertRaises(kn.ImageUploadError) as ctx:
            kn.upload_image(self.dir / "없는파일.jpg", path=self.path)
        self.assertIn("없습니다", str(ctx.exception))

    def test_upload_http_error_raises_readable_error(self):
        def fake_post(url, **kw):
            return FakeResp(403, {"code": -402, "msg": "insufficient scopes"})

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            with self.assertRaises(kn.ImageUploadError) as ctx:
                kn.upload_image(self.jpg, path=self.path)
        self.assertIn("talk_message", str(ctx.exception))
        self.assertIn(self.jpg.name, str(ctx.exception))

    def test_upload_response_without_url_is_reported(self):
        def fake_post(url, **kw):
            return FakeResp(200, {"infos": {}})

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            with self.assertRaises(kn.ImageUploadError) as ctx:
                kn.upload_image(self.jpg, path=self.path)
        self.assertIn("url이 없습니다", str(ctx.exception))

    def test_upload_401_refreshes_once_then_retries(self):
        seq = []

        def fake_post(url, **kw):
            seq.append(url)
            if url == kn.TOKEN_URL:
                return FakeResp(200, {"access_token": "ACCESS_NEW", "expires_in": 21599})
            if seq.count(kn.IMAGE_UPLOAD_URL) == 1:
                return FakeResp(401, {"code": -401, "msg": "token expired"})
            return FakeResp(200, UPLOAD_OK)

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            info = kn.upload_image(self.jpg, path=self.path)

        self.assertEqual(info["width"], 1280)
        self.assertEqual(
            seq, [kn.IMAGE_UPLOAD_URL, kn.TOKEN_URL, kn.IMAGE_UPLOAD_URL]
        )

    def test_expired_token_refreshes_before_upload(self):
        write_token(self.path, expires_at=time.time() - 10)
        seq = []

        def fake_post(url, **kw):
            seq.append(url)
            if url == kn.TOKEN_URL:
                return FakeResp(200, {"access_token": "ACCESS_NEW", "expires_in": 21599})
            return FakeResp(200, UPLOAD_OK)

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            kn.upload_image(self.jpg, path=self.path)
        self.assertEqual(seq, [kn.TOKEN_URL, kn.IMAGE_UPLOAD_URL])


class PrepareImageTests(ImageBase):
    def test_small_file_is_used_as_is(self):
        used, note = kn.prepare_image(self.jpg)
        self.assertEqual(used, self.jpg)
        self.assertIsNone(note)

    def test_oversized_file_is_reencoded_to_temp_original_untouched(self):
        big = make_jpg(self.dir / "큰그림.jpg", size=(3000, 6000))
        before = big.read_bytes()
        used, note = kn.prepare_image(big, max_bytes=100)  # 강제로 리사이즈 분기
        try:
            self.assertNotEqual(used, big)
            self.assertTrue(used.exists())
            self.assertIn("재인코딩", note)
            from PIL import Image

            with Image.open(used) as im:
                self.assertEqual(im.size[0], kn.IMAGE_RESIZE_WIDTH)  # 폭만 축소
                self.assertEqual(im.size[1], 6000 * kn.IMAGE_RESIZE_WIDTH // 3000)
            self.assertEqual(big.read_bytes(), before)  # 원본 보존
        finally:
            kn.cleanup_temp(big, used)
        self.assertFalse(used.exists())

    def test_tall_image_keeps_full_height_when_narrow(self):
        tall = make_jpg(self.dir / "세로긴.jpg", size=(1000, 2995))
        used, note = kn.prepare_image(tall, max_bytes=10)
        try:
            from PIL import Image

            with Image.open(used) as im:
                self.assertEqual(im.size, (1000, 2995))  # 폭 1280 미만 → 그대로
        finally:
            kn.cleanup_temp(tall, used)

    def test_without_pillow_falls_back_to_original_with_warning(self):
        big = make_jpg(self.dir / "큰그림2.jpg", size=(900, 900))
        with mock.patch.dict(sys.modules, {"PIL": None}):
            used, note = kn.prepare_image(big, max_bytes=10)
        self.assertEqual(used, big)
        self.assertIn("Pillow", note)

    def test_upload_cleans_up_temp_file(self):
        big = make_jpg(self.dir / "큰그림3.jpg", size=(2000, 2000))
        before = set(self.leftover_temp_files())
        with mock.patch.object(kn, "IMAGE_MAX_BYTES", 100):
            with mock.patch.object(
                kn.requests, "post", side_effect=lambda url, **kw: FakeResp(200, UPLOAD_OK)
            ):
                info = kn.upload_image(big, path=self.path)
        self.assertIn("재인코딩", info["note"])
        self.assertEqual(set(self.leftover_temp_files()), before)


class ImageTemplateTests(unittest.TestCase):
    INFO = {"url": "https://cdn/x.jpg", "width": 1280, "height": 1600}

    def test_feed_template_fields(self):
        tpl = kn.build_image_template(self.INFO, "1/2 지도·요약", "수원시 영통역")
        self.assertEqual(tpl["object_type"], "feed")
        content = tpl["content"]
        self.assertEqual(content["title"], "1/2 지도·요약")
        self.assertEqual(content["description"], "수원시 영통역")
        self.assertEqual(content["image_url"], "https://cdn/x.jpg")
        self.assertEqual(content["image_width"], 1280)
        self.assertEqual(content["image_height"], 1600)
        self.assertEqual(content["link"], {})  # 링크 미지정 = 최소값

    def test_feed_template_with_link(self):
        tpl = kn.build_image_template(self.INFO, "제목", "", "https://example.com")
        link = tpl["content"]["link"]
        self.assertEqual(link["web_url"], "https://example.com")
        self.assertEqual(link["mobile_web_url"], "https://example.com")

    def test_long_title_and_description_are_truncated(self):
        tpl = kn.build_image_template(self.INFO, "가" * 500, "나" * 500)
        self.assertEqual(len(tpl["content"]["title"]), kn.FEED_TITLE_LIMIT)
        self.assertEqual(len(tpl["content"]["description"]), kn.FEED_DESC_LIMIT)


class SendImageTests(ImageBase):
    def test_send_image_posts_feed_template(self):
        posted = {}

        def fake_post(url, **kw):
            if url == kn.IMAGE_UPLOAD_URL:
                return FakeResp(200, UPLOAD_OK)
            posted["template"] = json.loads(kw["data"]["template_object"])
            return FakeResp(200, {"result_code": 0})

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            result = kn.send_image(self.jpg, "2/2 전 매물 가동률", "전수 34실", path=self.path)

        self.assertTrue(result.ok, result.message)
        content = posted["template"]["content"]
        self.assertEqual(posted["template"]["object_type"], "feed")
        self.assertEqual(content["title"], "2/2 전 매물 가동률")
        self.assertEqual(content["image_url"], UPLOAD_OK["infos"]["original"]["url"])
        self.assertEqual(content["image_height"], 2995)

    def test_title_defaults_to_filename_stem(self):
        posted = {}

        def fake_post(url, **kw):
            if url == kn.IMAGE_UPLOAD_URL:
                return FakeResp(200, UPLOAD_OK)
            posted["template"] = json.loads(kw["data"]["template_object"])
            return FakeResp(200, {"result_code": 0})

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            self.assertTrue(kn.send_image(self.jpg, path=self.path).ok)
        self.assertEqual(posted["template"]["content"]["title"], "본문_1")

    def test_send_image_failure_message_names_the_file(self):
        def fake_post(url, **kw):
            if url == kn.IMAGE_UPLOAD_URL:
                return FakeResp(200, UPLOAD_OK)
            return FakeResp(400, {"code": -2, "msg": "bad template"})

        with mock.patch.object(kn.requests, "post", side_effect=fake_post):
            result = kn.send_image(self.jpg, path=self.path)
        self.assertFalse(result.ok)
        self.assertIn(self.jpg.name, result.message)

    def test_send_image_without_token_is_readable(self):
        result = kn.send_image(self.jpg, path=self.dir / "nope.json")
        self.assertFalse(result.ok)
        self.assertIn("kakao_setup.py", result.message)


class SendReportTests(ImageBase):
    def setUp(self):
        super().setUp()
        self.jpg2 = make_jpg(self.dir / "본문_2.jpg", color=(20, 90, 60))

    def test_text_then_images_in_order_with_interval(self):
        seq = []
        sleeps = []

        def fake_post(url, **kw):
            if url == kn.MEMO_URL:
                tpl = json.loads(kw["data"]["template_object"])
                seq.append(tpl["object_type"])
            else:
                seq.append("upload")
            return FakeResp(200, UPLOAD_OK if url == kn.IMAGE_UPLOAD_URL else {"result_code": 0})

        with mock.patch.object(kn.time, "sleep", side_effect=sleeps.append):
            with mock.patch.object(kn.requests, "post", side_effect=fake_post):
                report = kn.send_report(
                    "요약",
                    [(self.jpg, "1/2 지도·요약", ""), (self.jpg2, "2/2 가동률", "")],
                    path=self.path,
                )

        self.assertTrue(report.ok, report.message)
        self.assertEqual((report.sent, report.failed), (3, 0))
        self.assertEqual(seq, ["text", "upload", "feed", "upload", "feed"])
        # 텍스트→이미지1, 이미지1→이미지2 사이 2회 대기
        self.assertEqual(sleeps, [kn.SEND_INTERVAL_SEC, kn.SEND_INTERVAL_SEC])
        self.assertEqual([label for label, _, _ in report.details][0], "텍스트 요약")

    def test_partial_failure_still_sends_the_rest_and_aggregates(self):
        state = {"uploads": 0}

        def fake_post(url, **kw):
            if url == kn.IMAGE_UPLOAD_URL:
                state["uploads"] += 1
                if state["uploads"] == 1:
                    return FakeResp(500, {"code": -1, "msg": "server error"})
                return FakeResp(200, UPLOAD_OK)
            return FakeResp(200, {"result_code": 0})

        with mock.patch.object(kn.time, "sleep"):
            with mock.patch.object(kn.requests, "post", side_effect=fake_post):
                report = kn.send_report(
                    "요약", [self.jpg, self.jpg2], path=self.path
                )

        self.assertFalse(report.ok)
        self.assertEqual((report.sent, report.failed), (2, 1))
        self.assertEqual(state["uploads"], 2)  # 첫 장 실패해도 둘째 장 계속 진행
        labels = {label: ok for label, ok, _ in report.details}
        self.assertTrue(labels["텍스트 요약"])
        self.assertFalse(labels[self.jpg.name])
        self.assertTrue(labels[self.jpg2.name])
        self.assertIn("1건 실패", report.message)

    def test_text_only_report(self):
        with mock.patch.object(kn.requests, "post", return_value=FakeResp(200, {"result_code": 0})):
            report = kn.send_report("요약", None, path=self.path)
        self.assertTrue(report.ok)
        self.assertEqual((report.sent, report.failed), (1, 0))

    def test_empty_report_is_not_ok(self):
        report = kn.send_report(None, [], path=self.path)
        self.assertFalse(report.ok)
        self.assertIn("보낼 내용이 없습니다", report.message)


class ImageCliTests(ImageBase):
    def test_cli_sends_each_image_with_paired_title(self):
        titles = []

        def fake_post(url, **kw):
            if url == kn.IMAGE_UPLOAD_URL:
                return FakeResp(200, UPLOAD_OK)
            tpl = json.loads(kw["data"]["template_object"])
            if tpl["object_type"] == "feed":
                titles.append(tpl["content"]["title"])
            return FakeResp(200, {"result_code": 0})

        with mock.patch.object(kn.time, "sleep"):
            with mock.patch.object(kn.requests, "post", side_effect=fake_post):
                code = kn.main(
                    [
                        "--text", "요약",
                        "--image", str(self.jpg),
                        "--image", str(self.jpg2 if hasattr(self, "jpg2") else self.jpg),
                        "--image-title", "1/2 지도·요약",
                        "--token-file", str(self.path),
                        "--quiet",
                    ]
                )
        self.assertEqual(code, 0)
        # 두 번째 제목은 파일명으로 자동 채움
        self.assertEqual(titles, ["1/2 지도·요약", "본문_1"])

    def test_cli_returns_1_when_an_image_fails(self):
        def fake_post(url, **kw):
            if url == kn.IMAGE_UPLOAD_URL:
                return FakeResp(500, {"code": -1, "msg": "server error"})
            return FakeResp(200, {"result_code": 0})

        with mock.patch.object(kn.time, "sleep"):
            with mock.patch.object(kn.requests, "post", side_effect=fake_post):
                code = kn.main(
                    ["--text", "요약", "--image", str(self.jpg),
                     "--token-file", str(self.path)]
                )
        self.assertEqual(code, 1)

    def test_pair_image_args_fills_defaults(self):
        pairs = kn.pair_image_args(
            ["out/본문_1.jpg", "out/본문_2.jpg"], ["1/2 지도"], ["요약 지도"]
        )
        self.assertEqual([t for _, t, _ in pairs], ["1/2 지도", "본문_2"])
        self.assertEqual([d for _, _, d in pairs], ["요약 지도", ""])

    def test_normalize_images_accepts_bare_paths_and_tuples(self):
        out = kn.normalize_images(["a.jpg", ("b.jpg", "제목"), ("c.jpg", "제목", "설명")])
        self.assertEqual([(p.name, t, d) for p, t, d in out],
                         [("a.jpg", "a", ""), ("b.jpg", "제목", ""), ("c.jpg", "제목", "설명")])


class ErrorMessageTests(unittest.TestCase):
    def test_scope_missing_message(self):
        msg = kn.explain_send_error(403, {"code": -402, "msg": "insufficient scopes"})
        self.assertIn("talk_message", msg)

    def test_unknown_code_still_readable(self):
        msg = kn.explain_send_error(500, {"code": -999, "msg": "boom"})
        self.assertIn("-999", msg)
        self.assertIn("boom", msg)

    def test_network_failure_is_caught(self):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "t.json"
        write_token(path)
        with mock.patch.object(kn.requests, "post", side_effect=OSError("no network")):
            result = kn.send("요약", path=path)
        self.assertFalse(result.ok)
        self.assertIn("네트워크", result.message)
        tmp.cleanup()

    def test_mask_hides_token(self):
        out = kn.mask("ABCDEFGHIJKLMNOP")
        self.assertTrue(out.startswith("ABCD"))
        self.assertNotIn("EFGH", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
