# Author: Ching Kao
# Student ID: 85768427
"""Check the generated preview's origin, asset scope and storage stability."""

from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from fastapi.testclient import TestClient

from ai_coder.main import create_app


def test_preview_exists_only_after_entry_point_and_serves_its_workspace(settings, tmp_path):
    """One site's HTML and modules use its own loopback origin."""
    app = create_app(settings)
    with TestClient(app) as client:
        workspace = client.post("/api/workspaces", json={"name": "Preview"}).json()
        other = client.post("/api/workspaces", json={"name": "Other preview"}).json()
        route = f"/api/workspaces/{workspace['id']}/preview"
        assert client.get(route).json() == {"url": None}
        project = settings.workspaces_root / workspace["id"] / "project"
        second = settings.workspaces_root / other["id"] / "project"
        (second / "index.html").write_text("<h1>Other</h1>")
        (project / "index.html").write_text('<script type="module" src="app.js"></script>')
        (project / "app.js").write_text("export const answer = 42;")
        (project / "app.test.js").write_text("private test")
        (project / "package.json").write_text("{}")
        (project / ".env").write_text("private config")
        (project / "node_modules").mkdir()
        (project / "node_modules" / "dep.js").write_text("private dependency")
        secret = tmp_path / "secret.js"
        secret.write_text("outside workspace")
        (project / "symlink.js").symlink_to(secret)
        assert client.get("/api/workspaces/missing/preview").status_code == 404
        result = client.get(route)
        url = result.json()["url"]
        assert result.headers["Cache-Control"] == "no-store"
        assert url.startswith("http://127.0.0.1:") and url != client.get(f"/api/workspaces/{other['id']}/preview").json()["url"]
        with urlopen(url, timeout=5) as response:
            assert b'src="app.js"' in response.read()
            policy = response.headers["Content-Security-Policy"]
            assert "connect-src 'self'" in policy and "frame-ancestors http://127.0.0.1:5173" in policy
        with urlopen(url + "app.js", timeout=5) as response:
            assert "text/javascript" in response.headers["Content-Type"]
            assert b"answer = 42" in response.read()
        for hidden in ("app.test.js", "package.json", ".env", "node_modules/dep.js", "symlink.js", "%2e%2e/metadata.json"):
            try:
                urlopen(url + hidden, timeout=5)
            except HTTPError as error:
                assert error.code == 404
            else:
                raise AssertionError(f"Preview served private path {hidden}")
        try:
            urlopen(Request(url, headers={"Host": "other.test"}), timeout=5)
        except HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("Preview accepted an untrusted Host header")

    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(route).json() == {"url": url}


def test_preview_resolves_only_audio_imports_behind_missing_root_assets(settings, tmp_path):
    with TestClient(create_app(settings)) as client:
        workspace = client.post("/api/workspaces", json={"name": "Verified audio"}).json()
        project = settings.workspaces_root / workspace["id"] / "project"
        (project / "index.html").write_text("<h1>Audio</h1>")
        imported = project / "public" / "audio"
        imported.mkdir(parents=True)
        direct = project / "audio"
        direct.mkdir()

        formats = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg"}
        for suffix in formats:
            (imported / f"track.{suffix}").write_bytes(b"verified audio fixture")
        (direct / "track.mp3").write_bytes(b"original project fixture")
        (imported / "settings.json").write_text("{}")
        (imported / "unsupported.flac").write_bytes(b"unsupported audio fixture")
        (imported / "folder").mkdir()
        (imported / "folder" / "track.mp3").write_bytes(b"nested fixture")
        (imported / "outside.mp3").symlink_to(tmp_path / "outside.mp3")
        (tmp_path / "outside.mp3").write_bytes(b"outside workspace")
        (imported / "inside.mp3").symlink_to(imported / "track.mp3")
        (imported / "cycle.mp3").symlink_to(imported / "cycle.mp3")
        (imported / "shadowed.mp3").write_bytes(b"verified audio fixture")
        (direct / "shadowed.mp3").symlink_to(imported / "shadowed.mp3")
        (imported / "folder.mp3").write_bytes(b"verified audio fixture")
        (direct / "folder.mp3").mkdir()

        url = client.get(f"/api/workspaces/{workspace['id']}/preview").json()["url"]
        for suffix, media_type in formats.items():
            with urlopen(f"{url}audio/track.{suffix}", timeout=5) as response:
                assert response.headers["Content-Type"] == media_type
                assert "connect-src 'self'" in response.headers["Content-Security-Policy"]
                expected = b"original project fixture" if suffix == "mp3" else b"verified audio fixture"
                assert response.read() == expected
        (direct / "track.mp3").unlink()
        with urlopen(url + "audio/track.mp3", timeout=5) as response:
            assert response.read() == b"verified audio fixture"

        for path in (
            "settings.json", "folder/track.mp3", "outside.mp3", "inside.mp3", "cycle.mp3",
            "shadowed.mp3", "folder.mp3", "unsupported.flac", "%2e%2e/public/audio/track.mp3",
        ):
            with pytest.raises(HTTPError) as error:
                urlopen(url + "audio/" + path, timeout=5)
            assert error.value.code == 404
