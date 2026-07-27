import http.client
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

import urlshort


class LinkStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = urlshort.LinkStore(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    def test_create_writes_readable_json_and_get_returns_link(self):
        link = self.store.create(
            "https://example.com/long-link",
            urlshort.utc_now() + timedelta(days=1),
            code="12345",
        )

        self.assertEqual(link.code, "12345")
        self.assertEqual(self.store.get("12345").url, "https://example.com/long-link")
        self.assertTrue((Path(self.temporary.name) / "12345.json").is_file())

    def test_expired_link_is_not_returned_normally(self):
        path = Path(self.temporary.name) / "23456.json"
        path.write_text(
            '{"url":"https://example.com","created_at":"2020-01-01T00:00:00Z",'
            '"expires_at":"2020-01-02T00:00:00Z"}',
            encoding="utf-8",
        )

        self.assertIsNone(self.store.get("23456"))
        self.assertTrue(self.store.get("23456", include_expired=True).expired)

    def test_rejects_bad_codes_and_unsafe_urls(self):
        expiry = urlshort.utc_now() + timedelta(days=1)
        with self.assertRaises(ValueError):
            self.store.create("javascript:alert(1)", expiry, code="12345")
        with self.assertRaises(ValueError):
            self.store.create("https://example.com", expiry, code="../12")

    def test_existing_code_is_not_overwritten(self):
        expiry = urlshort.utc_now() + timedelta(days=1)
        self.store.create("https://one.example", expiry, code="34567")
        with self.assertRaises(FileExistsError):
            self.store.create("https://two.example", expiry, code="34567")
        self.assertEqual(self.store.get("34567").url, "https://one.example")

    def test_cleanup_removes_only_expired_links(self):
        expiry = urlshort.utc_now() + timedelta(days=1)
        self.store.create("https://active.example", expiry, code="45678")
        (Path(self.temporary.name) / "56789.json").write_text(
            '{"url":"https://expired.example","created_at":"2020-01-01T00:00:00Z",'
            '"expires_at":"2020-01-02T00:00:00Z"}',
            encoding="utf-8",
        )

        self.assertEqual(self.store.cleanup(), 1)
        self.assertIsNotNone(self.store.get("45678"))
        self.assertFalse((Path(self.temporary.name) / "56789.json").exists())


class LanguageTests(unittest.TestCase):
    def test_explicit_language_wins(self):
        self.assertEqual(urlshort.choose_language("en", "ru-RU"), "en")

    def test_browser_language_uses_highest_preference(self):
        self.assertEqual(
            urlshort.choose_language(None, "en-US;q=0.7,ru-RU;q=0.9"), "ru"
        )

    def test_unsupported_browser_language_falls_back_to_english(self):
        self.assertEqual(urlshort.choose_language(None, "de-DE,fr;q=0.8"), "en")


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        store = urlshort.LinkStore(Path(self.temporary.name))
        store.create(
            "https://example.com/destination",
            urlshort.utc_now() + timedelta(days=1),
            code="12345",
        )
        template, stylesheet, entry_script = urlshort.load_assets()
        self.server = urlshort.UrlShortServer(
            ("127.0.0.1", 0), store, template, stylesheet, entry_script
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_address[1], timeout=2
        )
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        response_body = response.read()
        connection.close()
        return response, response_body

    def test_home_page(self):
        response, body = self.request("GET", "/")
        self.assertEqual(response.status, 200)
        self.assertIn(b"Type the 5-digit code", body)
        self.assertEqual(body.count(b"data-code-digit"), 5)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertEqual(
            response.getheader("Content-Security-Policy"), "default-src 'self'"
        )

    def test_russian_is_selected_from_browser_language(self):
        response, body = self.request(
            "GET", "/", headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"}
        )
        self.assertEqual(response.status, 200)
        self.assertIn(b'<html lang="ru">', body)
        self.assertIn("Откройте ссылку".encode(), body)
        self.assertIn(b'name="lang" value="ru"', body)

    def test_language_switch_overrides_browser_language(self):
        response, body = self.request(
            "GET", "/?lang=en", headers={"Accept-Language": "ru-RU"}
        )
        self.assertEqual(response.status, 200)
        self.assertIn(b'<html lang="en">', body)
        self.assertIn(b"Open your link", body)

    def test_valid_code_redirects(self):
        body = urlencode({"code": "12345"})
        response, _ = self.request(
            "POST",
            "/open",
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
            },
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(response.getheader("Location"), "https://example.com/destination")
        self.assertIsNone(response.getheader("Content-Security-Policy"))

    def test_separate_digit_fields_work_without_javascript(self):
        body = urlencode(
            {
                "digit1": "1",
                "digit2": "2",
                "digit3": "3",
                "digit4": "4",
                "digit5": "5",
                "lang": "en",
            }
        )
        response, _ = self.request(
            "POST",
            "/open",
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
            },
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(response.getheader("Location"), "https://example.com/destination")

    def test_unknown_code_shows_friendly_error(self):
        body = urlencode({"code": "99999"})
        response, response_body = self.request(
            "POST",
            "/open",
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
            },
        )
        self.assertEqual(response.status, 200)
        self.assertIn(b"That code isn&#x27;t correct", response_body)

    def test_form_language_is_kept_for_russian_error(self):
        body = urlencode({"code": "99999", "lang": "ru"})
        response, response_body = self.request(
            "POST",
            "/open",
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "Accept-Language": "en-US",
            },
        )
        self.assertEqual(response.status, 200)
        self.assertIn("Неверный код".encode(), response_body)
        self.assertIn(b'name="lang" value="ru"', response_body)

    def test_health_check(self):
        response, body = self.request("GET", "/healthz")
        self.assertEqual(response.status, 200)
        self.assertEqual(body, b"ok\n")


if __name__ == "__main__":
    unittest.main()
