"""The public application entry point and the workbench's owner boundary."""

from zipfile import ZipFile

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse
from starlette.routing import Mount

from api.admin_auth import require_admin_api_key
from core.owner_access import COOKIE, OwnerAccessMiddleware, issue_token
from core.workbench_web import API_ROOT, ROOT, workbench_routes


def test_workbench_uses_owner_session_and_preserves_classic_tools(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "fixture owner access")
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY", "fixture-admin-access-1234567890-abcdef"
    )
    bundle = tmp_path / "bundle.zip"
    with ZipFile(bundle, "w") as archive:
        for view in ("scanner", "stocks", "backtests", "strategies", "runs", "health"):
            archive.writestr(f"{view}/index.html", f"<h1>{view}</h1>")
        archive.writestr("_next/static/fixture.js", "console.log('fixture')")

    core, classic = FastAPI(), FastAPI()

    @core.get("/reports/batches", dependencies=[Depends(require_admin_api_key)])
    def batches(limit: int = 50):
        return {"limit": limit}

    @core.post("/reports/scan", dependencies=[Depends(require_admin_api_key)])
    def scan(payload: dict):
        return payload

    @core.get("/reports/stocks/{symbol}", dependencies=[Depends(require_admin_api_key)])
    def stock_report(symbol: str, horizon: str):
        return {"symbol": symbol, "horizon": horizon}

    @core.get("/workspace/watchlist/{name:path}/constituents")
    def constituents(name: str):
        return {"name": name}

    @core.post(
        "/reports/backtest-queue/start", dependencies=[Depends(require_admin_api_key)]
    )
    def queue():
        return {"status": "started"}

    @classic.get("/")
    def legacy_tools():
        return PlainTextResponse("Stock reports and paper tools")

    routes, files = workbench_routes(core, classic, bundle)
    unified = FastAPI(routes=[*routes, Mount("/app", app=classic)])
    unified.add_middleware(OwnerAccessMiddleware)

    try:
        with TestClient(unified) as client:
            for path in (
                "/app/",
                ROOT + "/scanner/",
                ROOT + "/stocks/",
                ROOT + "/_next/static/fixture.js",
                API_ROOT + "/reports/batches",
                API_ROOT + "/reports/stocks/SBIN?horizon=short_term",
            ):
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
            assert client.get(ROOT + "/stocks/").status_code == 200
            assert client.get(
                API_ROOT + "/reports/stocks/M%26M?horizon=long_term"
            ).json() == {"symbol": "M&M", "horizon": "long_term"}
            assert client.get(
                API_ROOT
                + "/workspace/watchlist/NIFTY%20FINANCIAL%20SERVICES%2025%2F50"
                + "/constituents"
            ).json() == {"name": "NIFTY FINANCIAL SERVICES 25/50"}
            assert (
                client.get(
                    API_ROOT + "/workspace/watchlist/Custom/constituents"
                ).status_code
                == 404
            )
            batches = client.get(
                API_ROOT + "/reports/batches?limit=3",
                headers={"X-TrendForge-Admin-Key": "ignored client key"},
            )
            assert batches.json() == {"limit": 3}
            assert client.post(API_ROOT + "/reports/scan", json={}).status_code == 403
            assert (
                client.post(
                    API_ROOT + "/reports/backtest-queue/start", json={}
                ).status_code
                == 403
            )
            assert client.post(
                API_ROOT + "/reports/backtest-queue/start",
                json={},
                headers={"X-TrendForge-Workbench": "1"},
            ).json() == {"status": "started"}
            assert client.post(
                API_ROOT + "/reports/scan",
                json={"sample": 1},
                headers={"X-TrendForge-Workbench": "1"},
            ).json() == {"sample": 1}
            assert (
                client.post(
                    API_ROOT + "/paper/execute",
                    json={},
                    headers={"X-TrendForge-Workbench": "1"},
                ).status_code
                == 404
            )
    finally:
        files.cleanup()
