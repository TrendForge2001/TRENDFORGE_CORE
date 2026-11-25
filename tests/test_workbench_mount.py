"""The public application entry point and the workbench's owner boundary."""

from zipfile import ZipFile

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse
from starlette.routing import Mount

from api.admin_auth import require_admin_api_key
from core.owner_access import COOKIE, OwnerAccessMiddleware, issue_token
from core.workbench_web import API_ROOT, ROOT, workbench_routes


def test_workbench_uses_owner_session_and_preserves_classic_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "fixture owner access")
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "fixture-admin-access-1234567890-abcdef")
    bundle = tmp_path / "bundle.zip"
    with ZipFile(bundle, "w") as archive:
        for view in ("scanner", "backtests", "strategies", "runs", "health"):
            archive.writestr(f"{view}/index.html", f"<h1>{view}</h1>")
        archive.writestr("_next/static/fixture.js", "console.log('fixture')")

    core, classic = FastAPI(), FastAPI()

    @core.get("/reports/batches", dependencies=[Depends(require_admin_api_key)])
    def batches(limit: int = 50):
        return {"limit": limit}

    @core.post("/reports/scan", dependencies=[Depends(require_admin_api_key)])
    def scan(payload: dict):
        return payload

    @classic.get("/")
    def legacy_tools():
        return PlainTextResponse("Stock reports and paper tools")

    routes, files = workbench_routes(core, classic, bundle)
    unified = FastAPI(routes=[*routes, Mount("/app", app=classic)])
    unified.add_middleware(OwnerAccessMiddleware)

    try:
        with TestClient(unified) as client:
            for path in ("/app/", ROOT + "/scanner/", ROOT + "/_next/static/fixture.js", API_ROOT + "/reports/batches"):
                response = client.get(path, follow_redirects=False)
                assert response.status_code == 303
                assert response.headers["location"].startswith("/owner/laptop?next=")
            client.cookies.set(COOKIE, issue_token("session"))
            landing = client.get("/app/")
            assert landing.url.path == ROOT + "/scanner/"
            assert "<h1>scanner</h1>" in landing.text
            assert landing.headers["cache-control"] == "private, no-store"
            assert client.get(ROOT + "/_next/static/fixture.js").status_code == 200
            assert client.get("/app/classic/").text == "Stock reports and paper tools"
            batches = client.get(API_ROOT + "/reports/batches?limit=3", headers={"X-TrendForge-Admin-Key": "ignored client key"})
            assert batches.json() == {"limit": 3}
            assert client.post(API_ROOT + "/reports/scan", json={}).status_code == 403
            assert client.post(API_ROOT + "/reports/scan", json={"sample": 1}, headers={"X-TrendForge-Workbench": "1"}).json() == {"sample": 1}
            assert client.post(API_ROOT + "/paper/execute", json={}, headers={"X-TrendForge-Workbench": "1"}).status_code == 404
    finally:
        files.cleanup()
