#!/usr/bin/env python3
"""A deliberately small, file-backed URL code service."""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


CODE_RE = re.compile(r"^\d{5}$")
MAX_FORM_BYTES = 1024
DEFAULT_DATA_DIR = Path(os.environ.get("URLSHORT_DATA_DIR", "data"))
STATIC_DIR = Path(__file__).resolve().parent / "static"
SUPPORTED_LANGUAGES = {"en", "ru"}
TRANSLATIONS = {
    "en": {
        "title": "Open your link",
        "prompt": "Type the 5-digit code from your message",
        "hint": "Five numbers",
        "digit": "Digit",
        "button": "Open link",
        "language_label": "Language",
        "missing_code": "Please enter the 5-digit code.",
        "too_many": "Too many incorrect tries. Please wait one minute and try again.",
        "incorrect": "That code isn't correct. Please check the message and try again.",
    },
    "ru": {
        "title": "Откройте ссылку",
        "prompt": "Введите 5-значный код из сообщения",
        "hint": "Пять цифр",
        "digit": "Цифра",
        "button": "Открыть ссылку",
        "language_label": "Язык",
        "missing_code": "Введите 5-значный код.",
        "too_many": "Слишком много неверных попыток. Подождите минуту и попробуйте снова.",
        "incorrect": "Неверный код. Проверьте сообщение и попробуйте снова.",
    },
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_url(url: str) -> str:
    url = url.strip()
    if "\r" in url or "\n" in url:
        raise ValueError("URL may not contain line breaks")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("URL must start with http:// or https://")
    return url


def choose_language(explicit: str | None, accept_language: str = "") -> str:
    """Choose an explicit supported language, then fall back to browser preferences."""
    if explicit in SUPPORTED_LANGUAGES:
        return explicit

    candidates: list[tuple[float, int, str]] = []
    for index, item in enumerate(accept_language.split(",")):
        parts = [part.strip() for part in item.split(";")]
        language = parts[0].lower().split("-", 1)[0]
        if language not in SUPPORTED_LANGUAGES:
            continue
        quality = 1.0
        for parameter in parts[1:]:
            if parameter.startswith("q="):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 0.0
        if quality > 0:
            candidates.append((quality, -index, language))

    return max(candidates)[2] if candidates else "en"


@dataclass(frozen=True)
class Link:
    code: str
    url: str
    created_at: datetime
    expires_at: datetime

    @property
    def expired(self) -> bool:
        return self.expires_at <= utc_now()


class LinkStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()

    def _path(self, code: str) -> Path:
        if not CODE_RE.fullmatch(code):
            raise ValueError("code must contain exactly 5 digits")
        return self.directory / f"{code}.json"

    def create(self, url: str, expires_at: datetime, code: str | None = None) -> Link:
        url = validate_url(url)
        if expires_at <= utc_now():
            raise ValueError("expiration must be in the future")

        self.directory.mkdir(parents=True, exist_ok=True)
        candidates = [code] if code is not None else (
            f"{random.SystemRandom().randrange(100_000):05d}" for _ in range(100_000)
        )
        created_at = utc_now()

        for candidate in candidates:
            if candidate is None or not CODE_RE.fullmatch(candidate):
                raise ValueError("code must contain exactly 5 digits")
            path = self._path(candidate)
            if path.exists():
                if code is not None:
                    raise FileExistsError(f"code {candidate} already exists")
                continue

            link = Link(candidate, url, created_at, expires_at.astimezone(timezone.utc))
            payload = {
                "url": link.url,
                "created_at": format_timestamp(link.created_at),
                "expires_at": format_timestamp(link.expires_at),
            }
            fd, temporary_name = tempfile.mkstemp(
                dir=self.directory, prefix=f".{candidate}.", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as temporary:
                    json.dump(payload, temporary, indent=2)
                    temporary.write("\n")
                    temporary.flush()
                    os.fsync(temporary.fileno())
                # Refuse to replace an existing code, including one created concurrently.
                os.link(temporary_name, path)
                os.unlink(temporary_name)
                return link
            except Exception:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                if path.exists() and code is None:
                    continue
                raise

        raise RuntimeError("no unused five-digit codes are available")

    def get(self, code: str, include_expired: bool = False) -> Link | None:
        if not CODE_RE.fullmatch(code):
            return None
        try:
            with self._path(code).open(encoding="utf-8") as source:
                payload = json.load(source)
            link = Link(
                code=code,
                url=validate_url(payload["url"]),
                created_at=parse_timestamp(payload["created_at"]),
                expires_at=parse_timestamp(payload["expires_at"]),
            )
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return link if include_expired or not link.expired else None

    def all(self, include_expired: bool = True) -> list[Link]:
        links = []
        if not self.directory.exists():
            return links
        for path in self.directory.glob("*.json"):
            link = self.get(path.stem, include_expired=include_expired)
            if link is not None:
                links.append(link)
        return sorted(links, key=lambda link: link.created_at, reverse=True)

    def remove(self, code: str) -> bool:
        try:
            self._path(code).unlink()
            return True
        except FileNotFoundError:
            return False

    def cleanup(self) -> int:
        removed = 0
        for link in self.all(include_expired=True):
            if link.expired and self.remove(link.code):
                removed += 1
        return removed


class FailureLimiter:
    """A small in-memory limiter; restarting the service resets it."""

    def __init__(self, max_failures: int = 20, window_seconds: int = 60):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allowed(self, identity: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            recent = [value for value in self._failures.get(identity, []) if value > cutoff]
            self._failures[identity] = recent
            return len(recent) < self.max_failures

    def fail(self, identity: str) -> None:
        with self._lock:
            self._failures.setdefault(identity, []).append(time.monotonic())

    def succeed(self, identity: str) -> None:
        with self._lock:
            self._failures.pop(identity, None)


class UrlShortServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        store: LinkStore,
        page_template: str,
        stylesheet: bytes,
        entry_script: bytes,
        trust_proxy: bool = False,
    ):
        super().__init__(address, UrlShortHandler)
        self.store = store
        self.page_template = page_template
        self.stylesheet = stylesheet
        self.entry_script = entry_script
        self.trust_proxy = trust_proxy
        self.limiter = FailureLimiter()


class UrlShortHandler(BaseHTTPRequestHandler):
    server: UrlShortServer

    def _identity(self) -> str:
        if self.server.trust_proxy:
            forwarded = self.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",", 1)[0].strip()
        return self.client_address[0]

    def _security_headers(self, include_content_policy: bool = True) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if include_content_policy:
            # Do not set form-action 'self': local preview and reverse-proxy
            # origins can make this app's own /open endpoint appear cross-origin.
            self.send_header("Content-Security-Policy", "default-src 'self'")
        self.send_header("Cache-Control", "no-store")

    def _send_page(
        self,
        language: str,
        message_key: str | None = None,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        translations = TRANSLATIONS[language]
        message = translations[message_key] if message_key else ""
        message_html = (
            f'<p class="message" role="alert">{html.escape(message)}</p>' if message else ""
        )
        replacements = {
            "{{LANG}}": language,
            "{{TITLE}}": html.escape(translations["title"]),
            "{{PROMPT}}": html.escape(translations["prompt"]),
            "{{HINT}}": html.escape(translations["hint"]),
            "{{DIGIT}}": html.escape(translations["digit"]),
            "{{BUTTON}}": html.escape(translations["button"]),
            "{{LANGUAGE_LABEL}}": html.escape(translations["language_label"]),
            "{{LANG_VALUE}}": language,
            "{{RU_CURRENT}}": 'class="active" aria-current="page"'
            if language == "ru"
            else "",
            "{{EN_CURRENT}}": 'class="active" aria-current="page"'
            if language == "en"
            else "",
            "{{MESSAGE}}": message_html,
        }
        rendered = self.server.page_template
        for placeholder, value in replacements.items():
            rendered = rendered.replace(placeholder, value)
        body = rendered.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed_path = urlsplit(self.path)
        path = parsed_path.path
        if path == "/":
            requested = parse_qs(parsed_path.query).get("lang", [None])[0]
            language = choose_language(requested, self.headers.get("Accept-Language", ""))
            self._send_page(language)
        elif path == "/style.css":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(self.server.stylesheet)))
            self._security_headers()
            self.end_headers()
            self.wfile.write(self.server.stylesheet)
        elif path == "/code-entry.js":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(self.server.entry_script)))
            self._security_headers()
            self.end_headers()
            self.wfile.write(self.server.entry_script)
        elif path == "/healthz":
            body = b"ok\n"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/open":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_FORM_BYTES:
            language = choose_language(None, self.headers.get("Accept-Language", ""))
            self._send_page(language, "missing_code", HTTPStatus.BAD_REQUEST)
            return

        fields = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        requested = fields.get("lang", [None])[0]
        language = choose_language(requested, self.headers.get("Accept-Language", ""))
        identity = self._identity()
        if not self.server.limiter.allowed(identity):
            self._send_page(
                language, "too_many", HTTPStatus.TOO_MANY_REQUESTS
            )
            return

        code = fields.get("code", [""])[0].strip()
        if not CODE_RE.fullmatch(code):
            code = "".join(fields.get(f"digit{index}", [""])[0] for index in range(1, 6))
        link = self.server.store.get(code)
        if link is None:
            self.server.limiter.fail(identity)
            self._send_page(language, "incorrect")
            return

        self.server.limiter.succeed(identity)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", link.url)
        # A form-action policy on this response can make browsers block the
        # external destination while still showing a successful 303 request.
        self._security_headers(include_content_policy=False)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(
            f'{self.log_date_time_string()} {self.client_address[0]} {format % args}\n'
        )


def load_assets() -> tuple[str, bytes, bytes]:
    return (
        (STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        (STATIC_DIR / "style.css").read_bytes(),
        (STATIC_DIR / "code-entry.js").read_bytes(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Five-digit URL code service")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="directory containing code JSON files (default: %(default)s)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the web server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument(
        "--trust-proxy",
        action="store_true",
        help="trust X-Forwarded-For from the local reverse proxy",
    )

    add = commands.add_parser("add", help="create a code for a URL")
    add.add_argument("url")
    add.add_argument("--days", type=float, default=7)
    add.add_argument("--code", help="use a specific five-digit code")

    commands.add_parser("list", help="list codes")

    remove = commands.add_parser("remove", help="remove a code")
    remove.add_argument("code")

    commands.add_parser("cleanup", help="remove expired codes")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = LinkStore(args.data_dir)

    try:
        if args.command == "serve":
            page_template, stylesheet, entry_script = load_assets()
            server = UrlShortServer(
                (args.host, args.port),
                store,
                page_template,
                stylesheet,
                entry_script,
                trust_proxy=args.trust_proxy,
            )
            print(f"Listening on http://{args.host}:{args.port}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0

        if args.command == "add":
            if args.days <= 0:
                raise ValueError("--days must be greater than zero")
            link = store.create(
                args.url,
                utc_now() + timedelta(days=args.days),
                code=args.code,
            )
            print(f"Code: {link.code}")
            print(f"Expires: {format_timestamp(link.expires_at)}")
            return 0

        if args.command == "list":
            links = store.all(include_expired=True)
            if not links:
                print("No codes.")
                return 0
            print(f"{'CODE':<7} {'STATUS':<9} {'EXPIRES (UTC)':<21} URL")
            for link in links:
                status = "expired" if link.expired else "active"
                print(
                    f"{link.code:<7} {status:<9} "
                    f"{format_timestamp(link.expires_at):<21} {link.url}"
                )
            return 0

        if args.command == "remove":
            if store.remove(args.code):
                print(f"Removed {args.code}.")
                return 0
            print(f"Code {args.code} was not found.", file=sys.stderr)
            return 1

        if args.command == "cleanup":
            count = store.cleanup()
            print(f"Removed {count} expired code{'s' if count != 1 else ''}.")
            return 0
    except (ValueError, FileExistsError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
