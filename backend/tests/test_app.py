# Author: Ching Kao
# Student ID: 85768427
"""Step 1: application skeleton, error format, and CORS.

These tests pin the cross-cutting rules from docs/interfaces.md that every
route depends on:

- Every error body is {"error": {"code": ..., "message": ...}} with a JSON
  content type, including errors raised by FastAPI itself (unknown routes,
  wrong methods, request validation).
- Validation failures return 400, not FastAPI's default 422.
- The Vite dev server origins may call the API from the browser.
"""
from fastapi.testclient import TestClient

from ai_coder.api.errors import ApiError
from ai_coder.config import Settings
from ai_coder.main import create_app

DEV_ORIGIN = "http://127.0.0.1:5173"


def make_client(tmp_path, register_test_routes=None) -> TestClient:
    settings = Settings(workspaces_root=tmp_path / "workspaces")
    app = create_app(settings)
    if register_test_routes:
        register_test_routes(app)
    return TestClient(app)


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


def test_health_returns_ok(tmp_path):
    response = make_client(tmp_path).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_uses_error_format(tmp_path):
    response = make_client(tmp_path).get("/api/does-not-exist")
    assert_error(response, 404, "NOT_FOUND")
    assert response.json()["error"]["message"] == "API route not found."


def test_wrong_method_uses_error_format(tmp_path):
    response = make_client(tmp_path).delete("/api/health")
    assert_error(response, 405, "METHOD_NOT_ALLOWED")


def test_api_error_uses_its_status_and_code(tmp_path):
    def routes(app):
        @app.get("/api/test-conflict")
        def conflict():
            raise ApiError(409, "NOT_READY", "Run is not complete yet.")

    response = make_client(tmp_path, routes).get("/api/test-conflict")
    assert_error(response, 409, "NOT_READY")
    assert response.json()["error"]["message"] == "Run is not complete yet."


def test_validation_error_returns_400_not_422(tmp_path):
    def routes(app):
        @app.get("/api/test-validation")
        def validation(count: int):
            return {"count": count}

    response = make_client(tmp_path, routes).get("/api/test-validation?count=abc")
    assert_error(response, 400, "INVALID_INPUT")


def test_unexpected_exception_returns_500_error_format(tmp_path):
    def routes(app):
        @app.get("/api/test-crash")
        def crash():
            raise RuntimeError("boom")

    client = TestClient(
        _app_with_routes(tmp_path, routes), raise_server_exceptions=False
    )
    response = client.get("/api/test-crash")
    assert_error(response, 500, "INTERNAL_ERROR")
    # Internal details must not leak to the browser.
    assert "boom" not in response.json()["error"]["message"]


def test_cors_allows_vite_dev_origin(tmp_path):
    response = make_client(tmp_path).options(
        "/api/health",
        headers={
            "Origin": DEV_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == DEV_ORIGIN


def test_cors_allows_localhost_spelling_too(tmp_path):
    # 127.0.0.1 and localhost are different origins to a browser.
    response = make_client(tmp_path).get(
        "/api/health", headers={"Origin": "http://localhost:5173"}
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_other_origins(tmp_path):
    response = make_client(tmp_path).get(
        "/api/health", headers={"Origin": "http://evil.example"}
    )
    assert "access-control-allow-origin" not in response.headers


def test_cors_exposes_download_filename_header(tmp_path):
    response = make_client(tmp_path).get(
        "/api/health", headers={"Origin": DEV_ORIGIN}
    )
    exposed = response.headers["access-control-expose-headers"].lower()
    assert "content-disposition" in exposed


def test_create_app_makes_workspaces_root(tmp_path):
    make_client(tmp_path)
    assert (tmp_path / "workspaces").is_dir()


def _app_with_routes(tmp_path, register_test_routes):
    app = create_app(Settings(workspaces_root=tmp_path / "workspaces"))
    register_test_routes(app)
    return app
