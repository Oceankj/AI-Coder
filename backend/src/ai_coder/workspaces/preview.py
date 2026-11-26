# Author: Ching Kao
# Student ID: 85768427
"""Serve each generated website from its own local browser origin."""

from __future__ import annotations

import shutil
import tempfile
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import unquote, urlsplit

from ai_coder.workspaces.permissions import is_test_file
from ai_coder.workspaces.service import InvalidPathError, resolve_project_path


LOOPBACK = "127.0.0.1"
AUDIO_TYPES = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
}
PUBLIC_TYPES = {
    ".html": "text/html", ".htm": "text/html", ".css": "text/css",
    ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
    ".ico": "image/x-icon", ".avif": "image/avif", ".woff": "font/woff",
    ".woff2": "font/woff2", ".ttf": "font/ttf", ".mp4": "video/mp4", ".webm": "video/webm",
    ".wasm": "application/wasm", ".txt": "text/plain", ".webmanifest": "application/manifest+json",
    **AUDIO_TYPES,
}


class ProjectPreviewHandler(BaseHTTPRequestHandler):
    """Serve public assets only, with no dependency folders or backend access."""

    def __init__(self, *args, project: Path, frame_ancestors: str, **kwargs):
        self.project = project
        self.policy = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; "
            "frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'self'; "
            f"frame-ancestors {frame_ancestors}"
        )
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """Send an asset belonging to the current workspace project."""
        self._serve(body=True)

    def do_HEAD(self):
        """Return headers without sending an asset body."""
        self._serve(body=False)

    def _serve(self, *, body: bool):
        if self.headers.get("Host") != f"{LOOPBACK}:{self.server.server_port}":
            self.send_error(403)
            return
        try:
            name = unquote(urlsplit(self.path).path.removeprefix("/"), errors="strict") or "index.html"
            parts = name.split("/")
            if (any(part.startswith(".") or part == "node_modules" for part in parts)
                    or name in {"package.json", "package-lock.json"} or is_test_file(name)):
                raise InvalidPathError("Private project file.")
            suffix = Path(name).suffix.lower()
            media_type = PUBLIC_TYPES.get(suffix)
            if not media_type or self.project.is_symlink():
                raise InvalidPathError("Unsupported asset.")
            asset = resolve_project_path(self.project, name)
            if (len(parts) == 2 and parts[0] == "audio" and suffix in AUDIO_TYPES
                    and asset == self.project / name and not asset.exists()):
                name = f"public/{name}"
                asset = resolve_project_path(self.project, name)
            if asset != self.project / name or not asset.is_file():
                raise InvalidPathError("Project preview serves regular project files.")
            source = asset.open("rb")
        except (InvalidPathError, OSError, RuntimeError, UnicodeError, ValueError):
            self.send_error(404)
            return

        with source:
            self.send_response(200)
            if media_type.startswith("text/"):
                media_type += "; charset=utf-8"
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Security-Policy", self.policy)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if body:
                shutil.copyfileobj(source, self.wfile)

    def log_message(self, format, *args):
        """Avoid logging generated asset paths on the backend console."""


class WorkspacePreviews:
    """Start workspace previews on demand and release all listeners on shutdown."""

    def __init__(self, cors_origins: tuple[str, ...]):
        self._servers: dict[Path, ThreadingHTTPServer] = {}
        self._lock = Lock()
        origins = []
        for value in cors_origins:
            parsed = urlsplit(value)
            if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.geturl() == f"{parsed.scheme}://{parsed.netloc}":
                origins.append(parsed.geturl())
        self._frame_ancestors = " ".join(origins) or "'none'"

    def url_for(self, workspace: Path) -> str | None:
        """Return the site's local origin once its entry point exists."""
        project = workspace.resolve() / "project"
        entry = project / "index.html"
        if project.is_symlink() or entry.is_symlink() or not entry.is_file():
            return None
        with self._lock:
            if project not in self._servers:
                self._servers[project] = self._start(project)
            return f"http://{LOOPBACK}:{self._servers[project].server_port}/"

    def _start(self, project: Path) -> ThreadingHTTPServer:
        """Bind the previous port when available so browser storage survives a restart."""
        port_file = project.parent / ".preview-port"
        try:
            saved_port = int(port_file.read_text()) if not port_file.is_symlink() else 0
        except (OSError, ValueError):
            saved_port = 0
        if not 1024 <= saved_port <= 65535:
            saved_port = 0
        handler = partial(ProjectPreviewHandler, project=project, frame_ancestors=self._frame_ancestors)
        try:
            server = ThreadingHTTPServer((LOOPBACK, saved_port), handler)
        except OSError:
            if not saved_port:
                raise
            server = ThreadingHTTPServer((LOOPBACK, 0), handler)

        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=project.parent, delete=False) as marker:
                marker_path = Path(marker.name)
                marker.write(str(server.server_port))
            try:
                marker_path.replace(port_file)
            finally:
                marker_path.unlink(missing_ok=True)
            Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
        except BaseException:
            server.server_close()
            raise
        return server

    def close(self):
        """Stop active preview listeners before the backend exits."""
        with self._lock:
            for server in self._servers.values():
                server.shutdown()
                server.server_close()
            self._servers.clear()
