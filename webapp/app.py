#!/usr/bin/env python3
"""Small local web app for generating map posters."""

from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import re
import sys
import threading
import traceback
import uuid
import zipfile
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
WEBAPP_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEBAPP_DIR / "static"
CACHE_DIR = WEBAPP_DIR / ".cache"
CACHE_DIR.mkdir(exist_ok=True)
(CACHE_DIR / "matplotlib").mkdir(exist_ok=True)
(CACHE_DIR / "xdg").mkdir(exist_ok=True)
PREVIEW_DIR = CACHE_DIR / "previews"
PREVIEW_DIR.mkdir(exist_ok=True)

os.environ.setdefault("MPLCONFIGDIR", str(CACHE_DIR / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_DIR / "xdg"))
os.environ.setdefault("MPLBACKEND", "Agg")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import create_map_poster as poster  # noqa: E402
from font_management import load_fonts  # noqa: E402
from lat_lon_parser import parse  # noqa: E402


@dataclass
class Job:
    id: str
    status: str = "queued"
    progress: str = "Queued"
    files: list[Path] = field(default_factory=list)
    archive: Path | None = None
    error: str | None = None
    request: dict[str, Any] = field(default_factory=dict)


jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()
generation_lock = threading.Lock()


def preview_cache_key(payload: dict[str, Any]) -> str:
    normalized = {
        "version": 2,
        "city": str(payload.get("city", "")).strip().casefold(),
        "country": str(payload.get("country", "")).strip().casefold(),
        "latitude": str(payload.get("latitude", "")).strip(),
        "longitude": str(payload.get("longitude", "")).strip(),
        "countryLabel": str(payload.get("countryLabel", "")).strip(),
        "displayCity": str(payload.get("displayCity", "")).strip(),
        "displayCountry": str(payload.get("displayCountry", "")).strip(),
        "fontFamily": str(payload.get("fontFamily", "")).strip(),
        "theme": str(payload.get("theme", "terracotta")).strip(),
        "distance": str(payload.get("distance", 18000)).strip(),
        "width": str(payload.get("width", 12)).strip(),
        "height": str(payload.get("height", 16)).strip(),
        "previewDpi": 140,
        "previewMinSide": 3.6,
    }
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def read_json_body(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def slugify(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return clean.strip("_") or "poster"


def get_theme_payload() -> list[dict[str, Any]]:
    themes = []
    for theme_name in poster.get_available_themes():
        theme_path = ROOT / poster.THEMES_DIR / f"{theme_name}.json"
        try:
            with theme_path.open("r", encoding=poster.FILE_ENCODING) as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            data = {}

        themes.append(
            {
                "id": theme_name,
                "name": data.get("name", theme_name.replace("_", " ").title()),
                "description": data.get("description", ""),
                "colors": {
                    "bg": data.get("bg", "#ffffff"),
                    "text": data.get("text", "#111111"),
                    "water": data.get("water", "#d8e6ef"),
                    "parks": data.get("parks", "#e3eadc"),
                    "road": data.get("road_primary", "#444444"),
                },
            }
        )
    return themes


def get_poster_payload(limit: int = 36) -> list[dict[str, str]]:
    posters_dir = ROOT / poster.POSTERS_DIR
    if not posters_dir.exists():
        return []

    manifest = ROOT / "data" / "homepage_posters.json"
    images: list[Path] = []
    if manifest.exists():
        try:
            with manifest.open("r", encoding="utf-8") as file:
                keepers = json.load(file)
            images = [
                posters_dir / Path(str(filename)).name
                for filename in keepers
                if (posters_dir / Path(str(filename)).name).is_file()
            ][:limit]
        except (OSError, json.JSONDecodeError, TypeError):
            images = []

    if not images:
        images = sorted(
            [
                path
                for path in posters_dir.iterdir()
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            ],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[:limit]

    return [
        {
            "name": path.name,
            "url": f"/poster/{path.name}",
        }
        for path in images
    ]


def coerce_float(value: Any, name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is invalid") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return number


def coerce_int(value: Any, name: str, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is invalid") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return number


def set_job(job_id: str, **updates: Any) -> None:
    with jobs_lock:
        job = jobs[job_id]
        for key, value in updates.items():
            setattr(job, key, value)


def snapshot_job(job_id: str) -> dict[str, Any] | None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return None
        files = [
            {
                "name": path.name,
                "downloadUrl": f"/api/download/{job.id}/{path.name}",
                "previewUrl": f"/api/preview/{job.id}/{path.name}",
                "format": path.suffix.lower().lstrip("."),
            }
            for path in job.files
        ]
        return {
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "error": job.error,
            "files": files,
            "archiveUrl": f"/api/download/{job.id}/{job.archive.name}" if job.archive else None,
            "request": job.request,
        }


def generate_job(job_id: str, payload: dict[str, Any]) -> None:
    try:
        city = str(payload.get("city", "")).strip()
        country = str(payload.get("country", "")).strip()
        if not city or not country:
            raise ValueError("City and country are required")

        preview_only = bool(payload.get("previewOnly", False))
        output_format = "png" if preview_only else str(payload.get("format", "png")).lower()
        if output_format not in {"png", "svg", "pdf"}:
            raise ValueError("Unsupported format")

        distance = coerce_int(payload.get("distance", 18000), "Distance", 1000, 50000)
        width = coerce_float(payload.get("width", 12), "Width", 1, 50)
        height = coerce_float(payload.get("height", 16), "Height", 1, 50)
        dpi = 140 if preview_only else 300
        if preview_only:
            smaller_side = min(width, height)
            if smaller_side > 3.6:
                scale = 3.6 / smaller_side
                width *= scale
                height *= scale

        available_themes = poster.get_available_themes()
        theme = str(payload.get("theme", "terracotta"))
        all_themes = False if preview_only else bool(payload.get("allThemes", False))
        themes = available_themes if all_themes else [theme]
        missing = [item for item in themes if item not in available_themes]
        if missing:
            raise ValueError(f"Theme not found: {', '.join(missing)}")

        set_job(job_id, status="running", progress="Queued")
        with generation_lock:
            set_job(job_id, progress="Locating city")
            latitude = str(payload.get("latitude", "")).strip()
            longitude = str(payload.get("longitude", "")).strip()
            if latitude and longitude:
                coords = (parse(latitude), parse(longitude))
            elif latitude or longitude:
                raise ValueError("Latitude and longitude must be filled in together")
            else:
                try:
                    coords = poster.get_coordinates(city, country)
                except ValueError as exc:
                    raise ValueError(f"Could not locate: {city}, {country}") from exc

            font_family = str(payload.get("fontFamily", "")).strip()
            fonts = None
            if font_family:
                set_job(job_id, progress="Loading font")
                fonts = load_fonts(font_family)

            files = []
            for index, theme_name in enumerate(themes, start=1):
                remaining = len(themes) - index
                if len(themes) > 1:
                    remaining_label = "last image" if remaining == 0 else f"{remaining} images left"
                    set_job(
                        job_id,
                        progress=f"Generating {index}/{len(themes)}: {theme_name} ({remaining_label})",
                    )
                else:
                    set_job(job_id, progress=f"Generating: {theme_name}")
                poster.THEME = poster.load_theme(theme_name)
                if preview_only:
                    output_file = PREVIEW_DIR / f"{preview_cache_key(payload)}.png"
                else:
                    output_file = Path(poster.generate_output_filename(city, theme_name, output_format))

                if not output_file.exists():
                    poster.create_poster(
                        city,
                        country,
                        coords,
                        distance,
                        str(output_file),
                        output_format,
                        width,
                        height,
                        country_label=str(payload.get("countryLabel", "")).strip() or None,
                        display_city=str(payload.get("displayCity", "")).strip() or None,
                        display_country=str(payload.get("displayCountry", "")).strip() or None,
                        fonts=fonts,
                        dpi=dpi,
                    )
                files.append(output_file)

            archive = None
            if len(files) > 1:
                archive_name = f"{slugify(city)}_{job_id[:8]}_posters.zip"
                archive = ROOT / poster.POSTERS_DIR / archive_name
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
                    for path in files:
                        zip_file.write(path, arcname=path.name)

        set_job(job_id, status="done", progress="Completed", files=files, archive=archive)
    except Exception as exc:  # pragma: no cover - surfaced through the UI
        traceback.print_exc()
        set_job(job_id, status="error", progress="Error", error=str(exc))


class AppHandler(SimpleHTTPRequestHandler):
    server_version = "MapToPosterWeb/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[webapp] {format % args}")

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file_path(self, path: Path, download: bool = False) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def send_file_headers(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/themes":
            self.send_json({"themes": get_theme_payload()})
            return
        if path == "/api/posters":
            self.send_json({"posters": get_poster_payload()})
            return
        if path.startswith("/api/jobs/"):
            job_id = path.removeprefix("/api/jobs/").strip("/")
            snapshot = snapshot_job(job_id)
            if snapshot is None:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
            else:
                self.send_json(snapshot)
            return
        if path.startswith("/api/download/"):
            parts = path.removeprefix("/api/download/").split("/", 1)
            if len(parts) != 2:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            job_id, filename = parts
            with jobs_lock:
                job = jobs.get(job_id)
            if job is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            allowed = {item.name: item for item in job.files}
            if job.archive:
                allowed[job.archive.name] = job.archive
            selected = allowed.get(Path(filename).name)
            if selected is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file_path(selected, download=True)
            return
        if path.startswith("/api/preview/"):
            parts = path.removeprefix("/api/preview/").split("/", 1)
            if len(parts) != 2:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            job_id, filename = parts
            with jobs_lock:
                job = jobs.get(job_id)
            if job is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            allowed = {item.name: item for item in job.files}
            selected = allowed.get(Path(filename).name)
            if selected is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file_path(selected)
            return
        if path == "/sample-poster.png":
            sample = ROOT / "posters" / "singapore_neon_cyberpunk_20260118_153328.png"
            if not sample.exists():
                sample = next((ROOT / "posters").glob("*.png"), None)
            if sample is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file_path(sample)
            return
        if path.startswith("/poster/"):
            filename = Path(path.removeprefix("/poster/")).name
            selected = ROOT / poster.POSTERS_DIR / filename
            self.send_file_path(selected)
            return

        if path in {"/studio", "/studio/"}:
            requested = "studio.html"
        elif path in {"/about", "/about/"}:
            requested = "about.html"
        else:
            requested = "index.html" if path in {"/", ""} else path.lstrip("/")
        candidate = (STATIC_DIR / requested).resolve()
        if not str(candidate).startswith(str(STATIC_DIR.resolve())):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        self.send_file_path(candidate)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/preview/"):
            parts = path.removeprefix("/api/preview/").split("/", 1)
            if len(parts) != 2:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            job_id, filename = parts
            with jobs_lock:
                job = jobs.get(job_id)
            if job is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            allowed = {item.name: item for item in job.files}
            selected = allowed.get(Path(filename).name)
            if selected is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file_headers(selected)
            return
        if path == "/sample-poster.png":
            sample = ROOT / "posters" / "singapore_neon_cyberpunk_20260118_153328.png"
            if not sample.exists():
                sample = next((ROOT / "posters").glob("*.png"), None)
            if sample is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file_headers(sample)
            return
        if path.startswith("/poster/"):
            filename = Path(path.removeprefix("/poster/")).name
            selected = ROOT / poster.POSTERS_DIR / filename
            self.send_file_headers(selected)
            return

        if path in {"/studio", "/studio/"}:
            requested = "studio.html"
        elif path in {"/about", "/about/"}:
            requested = "about.html"
        else:
            requested = "index.html" if path in {"/", ""} else path.lstrip("/")
        candidate = (STATIC_DIR / requested).resolve()
        if not str(candidate).startswith(str(STATIC_DIR.resolve())):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        self.send_file_headers(candidate)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/generate":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = read_json_body(self)
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        job_id = uuid.uuid4().hex
        if bool(payload.get("previewOnly", False)):
            cached_preview = PREVIEW_DIR / f"{preview_cache_key(payload)}.png"
            if cached_preview.exists():
                with jobs_lock:
                    jobs[job_id] = Job(
                        id=job_id,
                        status="done",
                        progress="Completed",
                        files=[cached_preview],
                        request=payload,
                    )
                self.send_json({"jobId": job_id}, HTTPStatus.ACCEPTED)
                return

        with jobs_lock:
            jobs[job_id] = Job(id=job_id, request=payload)
        worker = threading.Thread(target=generate_job, args=(job_id, payload), daemon=True)
        worker.start()
        self.send_json({"jobId": job_id}, HTTPStatus.ACCEPTED)


def main() -> None:
    host = "127.0.0.1"
    port = 8080
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            host = sys.argv[1]
    if len(sys.argv) > 2:
        port = int(sys.argv[2])
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"MapToPoster webapp: http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
