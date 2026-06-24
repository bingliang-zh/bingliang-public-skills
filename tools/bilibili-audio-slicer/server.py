#!/usr/bin/env python3
"""Local Bilibili audio slicer."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, unquote, urlparse, urlunparse


TOOL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TOOL_ROOT.parent.parent
WEB_ROOT = TOOL_ROOT / "web"
WORK_ROOT = TOOL_ROOT / ".work"
LOCAL_TOOL_ROOTS = [Path("C:/Tools")]
HOOK_SOUND_ROOT = REPO_ROOT / "hooks" / "stop-sound"
HOOK_SOUND_ASSET_ROOT = HOOK_SOUND_ROOT / "sounds"
CATALOG_PATH = HOOK_SOUND_ROOT / "sounds.yaml"
MAX_BODY_BYTES = 1024 * 1024


def ensure_dirs() -> None:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    (WORK_ROOT / "jobs").mkdir(parents=True, exist_ok=True)


def find_command(name: str) -> str | None:
    local_names = [name]
    if os.name == "nt" and not name.lower().endswith(".exe"):
        local_names.append(f"{name}.exe")
    for root in LOCAL_TOOL_ROOTS:
        for local_name in local_names:
            candidate = root / local_name
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name)


def console(message: str) -> None:
    if sys.stdout:
        print(message)


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    content_length = int(handler.headers.get("Content-Length", "0"))
    if content_length > MAX_BODY_BYTES:
        raise ValueError("request body is too large")
    raw = handler.rfile.read(content_length)
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON body: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value


def require_tool(name: str) -> str:
    command = find_command(name)
    if not command:
        raise RuntimeError(f"Missing required command: {name}")
    return command


def validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must start with http:// or https://")
    return value


def run_command(command: list[str], timeout_seconds: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )


def job_dir(job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9-]{36}", job_id):
        raise ValueError("invalid job id")
    path = WORK_ROOT / "jobs" / job_id
    if not path.is_dir():
        raise FileNotFoundError("job not found")
    return path


def locate_job_audio(path: Path) -> Path:
    candidates = sorted(path.glob("source.*"))
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() in {".mp3", ".m4a", ".webm", ".opus", ".wav"}:
            return candidate
    raise FileNotFoundError("downloaded audio file was not found")


def normalize_cookie_file(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    if not path.is_file():
        raise ValueError(f"cookies file not found: {path}")
    return str(path)


def looks_like_cookie_text(value: str) -> bool:
    if "\n" in value or "\r" in value or "\t" in value:
        return True
    if re.search(r"(^|;\s*)(SESSDATA|bili_jct|DedeUserID|buvid3)=", value):
        return True
    return value.startswith("# Netscape HTTP Cookie File")


def write_cookie_text(job_path: Path, value: str) -> str:
    cookie_path = job_path / "cookies.txt"
    text = value.strip()
    if "\t" not in text and "\n" not in text and "=" in text:
        text = cookie_header_to_netscape(text)
    cookie_path.write_text(text + "\n", encoding="utf-8")
    return str(cookie_path)


def cookie_header_to_netscape(value: str) -> str:
    lines = ["# Netscape HTTP Cookie File"]
    for part in value.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, cookie_value = part.split("=", 1)
        name = name.strip()
        if not name:
            continue
        lines.append(f".bilibili.com\tTRUE\t/\tFALSE\t0\t{name}\t{cookie_value.strip()}")
    return "\n".join(lines)


def normalize_cookie_input(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    value = value.strip()
    if not value:
        return None, None
    if value.lower() in {"chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi"}:
        return value.lower(), None
    return None, normalize_cookie_file(value)


def bilibili_p1_url(value: str) -> str | None:
    parsed = urlparse(value)
    if "bilibili.com" not in parsed.netloc or "/video/" not in parsed.path:
        return None
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if any(key == "p" for key, _item_value in query):
        return None
    query.append(("p", "1"))
    return urlunparse(parsed._replace(query=urlencode(query)))


def remove_attempt_outputs(path: Path) -> None:
    for candidate in path.glob("source.*"):
        if candidate.is_file():
            candidate.unlink()


def build_yt_dlp_command(
    yt_dlp: str,
    url: str,
    output_template: Path,
    cookies_from_browser: str | None,
    cookies_file: str | None,
    no_playlist: bool,
) -> list[str]:
    command = [
        yt_dlp,
        "--user-agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "--add-header",
        "Referer:https://www.bilibili.com/",
        "--add-header",
        "Origin:https://www.bilibili.com",
    ]
    if cookies_file:
        command.extend(["--cookies", cookies_file])
    elif cookies_from_browser:
        command.extend(["--cookies-from-browser", cookies_from_browser])
    if no_playlist:
        command.append("--no-playlist")
    else:
        command.extend(["--playlist-items", "1"])
    command.extend(
        [
            "-f",
            "ba/bestaudio",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--print",
            "title",
            "--print",
            "after_move:filepath",
            "-o",
            str(output_template),
            url,
        ]
    )
    return command


def download_audio(url: str, cookies: str | None = None) -> dict:
    yt_dlp = require_tool("yt-dlp")
    require_tool("ffmpeg")

    job_id = str(uuid.uuid4())
    path = WORK_ROOT / "jobs" / job_id
    path.mkdir(parents=True, exist_ok=True)

    if cookies and looks_like_cookie_text(cookies):
        cookies_from_browser, cookies_file = None, write_cookie_text(path, cookies)
    else:
        cookies_from_browser, cookies_file = normalize_cookie_input(cookies)

    attempts: list[tuple[str, str, bool]] = [("direct", url, True)]
    p1_url = bilibili_p1_url(url)
    if p1_url:
        attempts.append(("bilibili-p1", p1_url, True))
    attempts.append(("first-playlist-item", url, False))

    failures: list[str] = []
    result: subprocess.CompletedProcess[str] | None = None
    for label, attempt_url, no_playlist in attempts:
        remove_attempt_outputs(path)
        command = build_yt_dlp_command(
            yt_dlp=yt_dlp,
            url=attempt_url,
            output_template=path / "source.%(ext)s",
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            no_playlist=no_playlist,
        )
        result = run_command(command)
        if result.returncode == 0:
            break
        message = result.stderr.strip() or result.stdout.strip() or "yt-dlp failed"
        failures.append(f"{label}: {message}")
    else:
        message = "\n\n".join(failures) if failures else "yt-dlp failed"
        if "Could not copy Chrome cookie database" in message:
            message += (
                "\n\nChrome is probably locking its cookie database. Close Chrome and retry, "
                "choose another browser, or export cookies to a cookies.txt file and use Cookies."
            )
        if "HTTP Error 412: Precondition Failed" in message:
            message += (
                "\n\nBilibili rejected every metadata attempt. The tool tried the direct URL, "
                "the ?p=1 URL when applicable, and the first playlist item. Retry with Cookies "
                "set to edge/firefox or a cookies.txt path."
            )
        raise RuntimeError(message)

    audio = locate_job_audio(path)
    assert result is not None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    title = lines[0] if lines else audio.stem

    return {
        "job_id": job_id,
        "title": title,
        "filename": audio.name,
        "audio_url": f"/api/audio/{job_id}",
    }

def safe_output_name(value: str, fallback: str) -> str:
    stem = value.strip() if value else fallback
    stem = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", stem)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", stem)
    stem = re.sub(r"\s+", "-", stem)
    stem = stem.strip(".-")
    if not stem or stem == "-":
        stem = fallback
    return f"{stem}.mp3"


def parse_seconds(value: object, name: str) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if seconds < 0:
        raise ValueError(f"{name} must be non-negative")
    return seconds


def yaml_scalar(value: str | None) -> str:
    if value is None or value == "":
        return "null"
    if re.fullmatch(r"[A-Za-z0-9._/@:+ -]+", value) and value.lower() not in {"null", "true", "false"}:
        return value
    return json.dumps(value, ensure_ascii=False)


def block_id(block: list[str]) -> str | None:
    if not block:
        return None
    match = re.match(r"- id:\s*(.+?)\s*$", block[0])
    if not match:
        return None
    raw = match.group(1)
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip('"')
    return None if raw == "null" else raw


def render_catalog_entry(clip_id: str, path: str) -> list[str]:
    return [
        f"- id: {yaml_scalar(clip_id)}",
        f"  path: {yaml_scalar(path)}",
    ]


def upsert_catalog_entry(clip_id: str, path: str) -> None:
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = CATALOG_PATH.read_text(encoding="utf-8").splitlines() if CATALOG_PATH.exists() else []

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("- id:"):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
        elif line.strip():
            blocks.append([line])
    if current:
        blocks.append(current)

    replacement = render_catalog_entry(clip_id, path)
    replaced = False
    output_blocks: list[list[str]] = []
    for block in blocks:
        if block_id(block) == clip_id:
            output_blocks.append(replacement)
            replaced = True
        else:
            output_blocks.append(block)
    if not replaced:
        output_blocks.append(replacement)

    flattened: list[str] = []
    for block in output_blocks:
        flattened.extend(block)
    CATALOG_PATH.write_text("\n".join(flattened).rstrip() + "\n", encoding="utf-8")


def export_clip(payload: dict) -> dict:
    ffmpeg = require_tool("ffmpeg")
    path = job_dir(str(payload.get("job_id", "")))
    audio = locate_job_audio(path)

    start = parse_seconds(payload.get("start"), "start")
    end = parse_seconds(payload.get("end"), "end")
    if end <= start:
        raise ValueError("end must be greater than start")
    if end - start > 120:
        raise ValueError("clip length is capped at 120 seconds")

    clip_id = str(payload.get("clip_id", "")).strip()
    if not clip_id:
        raise ValueError("clip_id is required")

    fallback_name = f"clip-{int(time.time())}"
    filename = safe_output_name(clip_id, fallback_name)
    HOOK_SOUND_ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    target = HOOK_SOUND_ASSET_ROOT / filename

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(audio),
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{end - start:.3f}",
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(target),
    ]
    result = run_command(command, timeout_seconds=300)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed")

    if bool(payload.get("update_catalog", True)):
        upsert_catalog_entry(
            clip_id=clip_id,
            path=f"sounds/{filename}",
        )

    return {
        "path": str(target.relative_to(REPO_ROOT)).replace(os.sep, "/"),
        "filename": filename,
        "catalog": str(CATALOG_PATH.relative_to(REPO_ROOT)).replace(os.sep, "/"),
    }


def send_file(handler: BaseHTTPRequestHandler, path: Path, content_type: str | None = None) -> None:
    if not path.is_file():
        handler.send_error(HTTPStatus.NOT_FOUND)
        return

    total = path.stat().st_size
    start = 0
    end = total - 1
    status = HTTPStatus.OK
    range_header = handler.headers.get("Range")
    if range_header:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if match:
            if match.group(1):
                start = int(match.group(1))
            if match.group(2):
                end = int(match.group(2))
            start = max(0, min(start, total - 1))
            end = max(start, min(end, total - 1))
            status = HTTPStatus.PARTIAL_CONTENT

    length = end - start + 1
    handler.send_response(status)
    handler.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Content-Length", str(length))
    if status == HTTPStatus.PARTIAL_CONTENT:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{total}")
    handler.end_headers()

    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            chunk = handle.read(min(1024 * 256, remaining))
            if not chunk:
                break
            handler.wfile.write(chunk)
            remaining -= len(chunk)


class Handler(BaseHTTPRequestHandler):
    server_version = "BilibiliAudioSlicer/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        if sys.stderr:
            sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self) -> None:  # noqa: N802
        try:
            self.route_get()
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            self.route_post()
        except ValueError as exc:
            json_response(self, 400, {"error": str(exc)})
        except FileNotFoundError as exc:
            json_response(self, 404, {"error": str(exc)})
        except RuntimeError as exc:
            json_response(self, 500, {"error": str(exc)})
        except subprocess.TimeoutExpired:
            json_response(self, 504, {"error": "command timed out"})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def route_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            json_response(
                self,
                200,
                {
                    "yt_dlp": bool(find_command("yt-dlp")),
                    "ffmpeg": bool(find_command("ffmpeg")),
                    "repo_root": str(REPO_ROOT),
                },
            )
            return

        if path.startswith("/api/audio/"):
            job_id = unquote(path.rsplit("/", 1)[-1])
            send_file(self, locate_job_audio(job_dir(job_id)), "audio/mpeg")
            return

        if path == "/":
            path = "/index.html"
        static_path = (WEB_ROOT / path.lstrip("/")).resolve()
        if WEB_ROOT not in static_path.parents and static_path != WEB_ROOT:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        send_file(self, static_path)

    def route_post(self) -> None:
        parsed = urlparse(self.path)
        payload = read_json_body(self)

        if parsed.path == "/api/download":
            url = validate_url(str(payload.get("url", "")).strip())
            cookies = str(payload.get("cookies", "")).strip() or None
            json_response(self, 200, download_audio(url, cookies))
            return

        if parsed.path == "/api/clip":
            json_response(self, 200, export_clip(payload))
            return

        self.send_error(HTTPStatus.NOT_FOUND)


def main() -> int:
    ensure_dirs()
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    console(f"Serving Bilibili audio slicer at http://127.0.0.1:{port}")
    console("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console("\nStopped.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        (WORK_ROOT / "server.error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
