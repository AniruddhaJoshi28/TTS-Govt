"""API gateway. Implements the proposed /api/v1 contracts from plan §5.

Only /health is functional. All other endpoints answer 501 with a structured
error so clients can integrate against the contract before the services exist,
and so nothing ever returns a fabricated result.
"""

import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from schemas.api.envelope import Envelope, ErrorDetail, Language

API_PREFIX = "/api/v1"

app = FastAPI(title="Government GR Assistant API", version="0.1.0")


@app.middleware("http")
async def assign_request_id(request: Request, call_next):
    incoming = request.headers.get("X-Request-ID", "")
    try:
        request_id = str(uuid.UUID(incoming))
    except ValueError:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


class DependencyStatus(BaseModel):
    name: str
    status: str  # "ok" | "unavailable" | "not_configured"


class Health(BaseModel):
    status: str  # "ok" | "degraded"
    dependencies: list[DependencyStatus]


# Dependencies the product relies on; each reports "not_configured" until wired up.
DEPENDENCIES = ["postgres", "object_storage", "bm25_index", "vector_index", "slm", "stt", "tts"]


@app.get(f"{API_PREFIX}/health", response_model=Envelope[Health])
async def health(request: Request) -> Envelope[Health]:
    deps = [DependencyStatus(name=name, status="not_configured") for name in DEPENDENCIES]
    overall = "ok" if all(d.status == "ok" for d in deps) else "degraded"
    return Envelope[Health](
        request_id=request.state.request_id,
        language=Language.ENGLISH,
        data=Health(status=overall, dependencies=deps),
    )


def _not_implemented(request: Request, service: str) -> JSONResponse:
    body = Envelope[None](
        request_id=request.state.request_id,
        language=Language.ENGLISH,
        error=ErrorDetail(code="not_implemented", message=f"The {service} service is not available yet."),
    )
    return JSONResponse(status_code=501, content=body.model_dump(mode="json"))


PLANNED_ROUTES = [
    ("GET", "/documents", "document search"),
    ("GET", "/documents/{document_id}", "document details"),
    ("POST", "/summaries", "summary"),
    ("POST", "/qa", "question answering"),
    ("POST", "/speech/transcriptions", "speech transcription"),
    ("POST", "/speech/synthesis", "speech synthesis"),
    ("GET", "/audio-assets/{asset_id}", "audio library"),
    ("POST", "/feedback", "feedback"),
]

for method, path, service in PLANNED_ROUTES:

    def _handler(request: Request, _service: str = service) -> JSONResponse:
        return _not_implemented(request, _service)

    app.add_api_route(f"{API_PREFIX}{path}", _handler, methods=[method], status_code=501)
