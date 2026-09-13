import hmac
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, func

from .config import Settings
from .db import cases, database, migrate
from .models import DraftRequest, Review
from .service import Conflict, Investigation


def create_app(settings=None, engine=None, provider=None):
    settings = settings or Settings()
    settings.validate()
    engine = engine or database(settings.database_url)
    service = Investigation(engine, settings, provider)

    @asynccontextmanager
    async def lifespan(app):
        migrate(engine)
        yield

    app = FastAPI(title="BankMore Fraud Intelligence", version="0.1.0", lifespan=lifespan)
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=settings.origins,
        allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
    bearer = HTTPBearer(auto_error=False)

    def auth(scope):
        def require(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
            if not credentials:
                raise HTTPException(401, "Credencial necessária", headers={"WWW-Authenticate": "Bearer"})
            identity = next((value for key, value in settings.identities.items()
                if hmac.compare_digest(key, credentials.credentials)), None)
            if identity is None:
                raise HTTPException(401, "Credencial inválida")
            if scope not in identity["scopes"]:
                raise HTTPException(403, "Escopo insuficiente")
            return identity
        return require

    @app.exception_handler(Conflict)
    async def conflict_handler(request, error):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(LookupError)
    async def missing_handler(request, error):
        return JSONResponse(status_code=404, content={"detail": "Caso não encontrado"})

    @app.exception_handler(ValueError)
    async def invalid_handler(request, error):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(httpx.HTTPError)
    async def provider_handler(request, error):
        return JSONResponse(status_code=503, content={"detail": "Provedor de IA indisponível"})

    @app.get("/health")
    def health():
        with engine.connect() as conn:
            conn.execute(select(1))
        return {"status": "ok", "mode": settings.mode}

    @app.get("/api/me")
    def me(identity=Depends(auth("read"))):
        return identity

    @app.get("/api/cases")
    def list_cases(limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=10000),
                   status: str | None = None, identity=Depends(auth("read"))):
        return service.list_cases(identity, limit, offset, status)

    @app.get("/api/cases/{case_id}")
    def evidence(case_id: str, identity=Depends(auth("read"))):
        return service.evidence(case_id, identity)

    @app.get("/api/cases/{case_id}/summary")
    def summary(case_id: str, identity=Depends(auth("read"))):
        return service.summary(case_id, identity)

    @app.get("/api/cases/{case_id}/procedures")
    def procedures(case_id: str, q: str = Query(min_length=1, max_length=500),
                   limit: int = Query(3, ge=1, le=5), identity=Depends(auth("read"))):
        return service.procedures(case_id, q, identity, limit)

    @app.get("/api/cases/{case_id}/similar")
    def similar(case_id: str, limit: int = Query(3, ge=1, le=5), identity=Depends(auth("read"))):
        return service.similar(case_id, identity, limit)

    @app.post("/api/cases/{case_id}/reports")
    def draft(case_id: str, request: DraftRequest, identity=Depends(auth("draft"))):
        return service.draft(case_id, request.expected_version, identity)

    @app.post("/api/cases/{case_id}/reviews")
    def review(case_id: str, request: Review, identity=Depends(auth("review"))):
        return service.review(case_id, request, identity)

    @app.get("/api/metrics")
    def metrics(identity=Depends(auth("read"))):
        with engine.connect() as conn:
            grouped = conn.execute(select(cases.c.status, func.count()).where(cases.c.queue == identity["queue"])
                .group_by(cases.c.status)).all()
        return {"cases": dict(grouped), "mode": settings.mode}

    return app
