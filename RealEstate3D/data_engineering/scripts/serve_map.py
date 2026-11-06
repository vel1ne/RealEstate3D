"""Serve the Saratov map locally without exposing the rest of the project.

Python standard library only. No requests are forwarded to tile providers.
"""
import argparse
import errno
from functools import partial
import hashlib
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit
import webbrowser


APP_ID = "RealEstate3D-Saratov-Map"
PROTOCOL_VERSION = 1
HEALTH_PATH = "/_realestate3d_health_v1"
MAP_PATH = "/maps/saratov_trucks.html"
ROOT = Path(__file__).resolve().parents[1]
ASSET_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


def identity(root):
    normalized = str(root.resolve()).casefold().encode("utf-8")
    return {
        "app": APP_ID,
        "protocol_version": PROTOCOL_VERSION,
        "root_id": hashlib.sha256(normalized).hexdigest()[:24],
    }


class MapHandler(BaseHTTPRequestHandler):
    server_version = "RealEstate3DLocal/1"
    sys_version = ""

    def __init__(self, *args, root, **kwargs):
        self.root = root.resolve()
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        # Routine tile-independent local file requests do not need console noise.
        pass

    def do_GET(self):
        self.serve_request(head_only=False)

    def do_HEAD(self):
        self.serve_request(head_only=True)

    def reply(self, status, body=b"", content_type="text/plain; charset=utf-8", head_only=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def serve_request(self, head_only):
        # Reject Host headers for other domains, in addition to binding loopback.
        if self.headers.get("Host", "") not in {
            "127.0.0.1:" + str(self.server.server_port),
            "localhost:" + str(self.server.server_port),
        }:
            self.reply(403, b"Local map access only.", head_only=head_only)
            return
        try:
            path = unquote(urlsplit(self.path).path, errors="strict")
        except (ValueError, UnicodeError):
            self.reply(400, b"Invalid path.", head_only=head_only)
            return
        parts = path.split("/")
        if "\\" in path or "\x00" in path or any(p in {".", ".."} for p in parts):
            self.reply(403, b"Path not allowed.", head_only=head_only)
            return
        if path == HEALTH_PATH:
            body = json.dumps(identity(self.root), separators=(",", ":")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
            return
        if path == "/":
            self.send_response(302)
            self.send_header("Location", MAP_PATH)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == MAP_PATH:
            file_path = self.root / "maps" / "saratov_trucks.html"
            content_type = "text/html; charset=utf-8"
        elif path.startswith("/maps/assets/"):
            if any(not part or part.startswith(".") for part in parts[3:]):
                self.reply(403, b"Path not allowed.", head_only=head_only)
                return
            file_path = self.root.joinpath(*parts[1:])
            content_type = ASSET_TYPES.get(file_path.suffix.lower())
            if content_type is None:
                self.reply(403, b"Asset type not allowed.", head_only=head_only)
                return
        else:
            self.reply(404, b"Only the map and its assets are available.", head_only=head_only)
            return
        try:
            resolved = file_path.resolve(strict=True)
            resolved.relative_to(self.root)
            if path.startswith("/maps/assets/"):
                resolved.relative_to(self.root / "maps" / "assets")
            elif resolved != self.root / "maps" / "saratov_trucks.html":
                raise ValueError("Map symlink outside allowed file")
            if not resolved.is_file():
                raise FileNotFoundError()
            file_stat = resolved.stat()
        except ValueError:
            self.reply(403, b"Path not allowed.", head_only=head_only)
            return
        except (OSError, RuntimeError):
            self.reply(404, b"File not found.", head_only=head_only)
            return
        etag = '"%x-%x"' % (file_stat.st_mtime_ns, file_stat.st_size)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", self.date_time_string(file_stat.st_mtime))
            self.end_headers()
            return
        try:
            with resolved.open("rb") as stream:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(file_stat.st_size))
                self.send_header("Last-Modified", self.date_time_string(file_stat.st_mtime))
                self.send_header("ETag", etag)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
                self.end_headers()
                if not head_only:
                    while True:
                        chunk = stream.read(256 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


class LocalMapServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def existing_server_is_ours(port, root):
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", HEALTH_PATH)
        response = connection.getresponse()
        if response.status != 200:
            return False
        payload = response.read(8193)
        return len(payload) <= 8192 and json.loads(payload) == identity(root)
    except (OSError, ValueError, HTTPException):
        return False
    finally:
        connection.close()


def open_map(url, no_browser):
    print("Карта: " + url, flush=True)
    if not no_browser:
        try:
            if not webbrowser.open(url, new=2):
                print("Откройте этот адрес в браузере вручную.", flush=True)
        except webbrowser.Error:
            print("Откройте этот адрес в браузере вручную.", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Локальный запуск карты Саратова")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    parser.add_argument("--port", type=int, default=8874, help="локальный порт (по умолчанию 8874)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("порт должен быть от 1 до 65535")
    if not (ROOT / "maps" / "saratov_trucks.html").is_file():
        print("Не найден maps\\saratov_trucks.html. Сохраните всю папку RealEstate3D вместе.", file=sys.stderr)
        return 1
    url = "http://127.0.0.1:%d%s" % (args.port, MAP_PATH)
    handler = partial(MapHandler, root=ROOT)
    try:
        server = LocalMapServer(("127.0.0.1", args.port), handler)
    except OSError as error:
        if error.errno in {errno.EADDRINUSE, 10048}:
            if existing_server_is_ours(args.port, ROOT):
                print("Карта из этой папки уже запущена.", flush=True)
                open_map(url, args.no_browser)
                return 0
            print("Порт %d занят другой программой или картой из другой папки. "
                  "Закройте прежнее окно запуска либо используйте --port с другим номером."
                  % args.port, file=sys.stderr)
        else:
            print("Не удалось запустить локальную карту: " + str(error), file=sys.stderr)
        return 2
    print("Карта запущена только на этом компьютере.", flush=True)
    print("Пока пользуетесь картой, оставьте это окно открытым. "
          "Чтобы остановить сервер, закройте окно или нажмите Ctrl+C.", flush=True)
    open_map(url, args.no_browser)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nКарта остановлена.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
