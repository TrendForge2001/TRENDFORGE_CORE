"""Mobile owner identity boundary; trading mutation adapters are separate work."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request

from services.mobile_identity import FirebaseOwnerIdentity, MobileIdentityError
from services.paper_storage_setup import paper_storage_setup


def attach_mobile_auth_routes(
    app: FastAPI, *, identity: FirebaseOwnerIdentity | None = None
) -> None:
    verifier = identity or FirebaseOwnerIdentity()
    router = APIRouter(prefix="/mobile/v1", tags=["Personal mobile"])

    @app.middleware("http")
    async def private_mobile_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/mobile/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            vary = response.headers.get("Vary", "")
            if "authorization" not in {v.strip().lower() for v in vary.split(",")}:
                response.headers["Vary"] = (
                    f"{vary}, Authorization" if vary else "Authorization"
                )
        return response

    def owner(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        parts = (authorization or "").split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                401, "Mobile sign-in required", headers={"WWW-Authenticate": "Bearer"}
            )
        try:
            return verifier.verify(parts[1])
        except MobileIdentityError as exc:
            messages = {
                401: "Mobile session is invalid; refresh or sign in again",
                403: "This account is not authorized for the personal app",
                503: "Mobile identity is unavailable or not configured",
            }
            raise HTTPException(
                exc.status,
                messages[exc.status],
                headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None,
            ) from None
        except Exception:
            raise HTTPException(
                503, "Mobile identity is temporarily unavailable"
            ) from None

    @router.get("/auth/session")
    def session(principal: Annotated[dict, Depends(owner)]) -> dict[str, Any]:
        return {
            "authenticated": True,
            "uid": principal["uid"],
            "expires_at": datetime.fromtimestamp(
                principal["expires_at"], UTC
            ).isoformat(),
            "broker_orders_allowed": False,
            "trading_mutations_available": False,
        }

    @router.get("/readiness")
    def readiness(_principal: Annotated[dict, Depends(owner)]) -> dict[str, Any]:
        storage = paper_storage_setup()
        return {
            "authenticated": True,
            "persistent_storage_verified": storage["verified"],
            "storage_checks": storage["checks"],
            "trading_mutations_available": False,
            "broker_orders_allowed": False,
        }

    app.include_router(router)
