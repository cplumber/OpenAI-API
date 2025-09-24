"""
FastAPI Application Entry Point
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.database import init_database, start_cleanup_scheduler
from app.api.routes import extract, classify, jobs, health, ai_action
from app.utils.prl_cleaner import start_prl_cleanup_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Resume Analyzer API",
    description="REST API for PDF resume analysis and document classification",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # tighten later if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    init_database()
    start_cleanup_scheduler()
    start_prl_cleanup_scheduler()  # runs once immediately + hourly background loop
    logger.info("Database initialized and cleanup scheduler started")

# Routers
app.include_router(ai_action.router, prefix="/ai", tags=["ai-actions"]) 
app.include_router(extract.router, prefix="/extract", tags=["extraction"])
app.include_router(classify.router, prefix="/classify", tags=["classification"])
app.include_router(jobs.router,     prefix="/jobs",     tags=["jobs"])
app.include_router(health.router,   prefix="/health",   tags=["health"])

@app.get("/")
async def root():
    return {"message": "Resume Analyzer API", "version": "1.0.0"}


# ---------------- Swagger Docs: Inject X-API-Key header ----------------
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    components = openapi_schema.setdefault("components", {})
    parameters = components.setdefault("parameters", {})

    # Define reusable header parameter
    parameters["XApiKeyHeader"] = {
        "name": "X-API-Key",
        "in": "header",
        "required": False,  # keep optional so /health and root still callable without
        "schema": {"type": "string"},
        "description": "API key header. Caddy validates **X-API-Key**.",
    }

    # Attach it to every operation
    for path_item in openapi_schema.get("paths", {}).values():
        for op_name, operation in list(path_item.items()):
            if op_name not in ("get", "put", "post", "delete", "options",
                               "head", "patch", "trace"):
                continue
            op_params = operation.setdefault("parameters", [])
            has_header = any(
                p.get("$ref") == "#/components/parameters/XApiKeyHeader"
                or (p.get("in") == "header" and p.get("name") == "X-API-Key")
                for p in op_params
            )
            if not has_header:
                op_params.append({"$ref": "#/components/parameters/XApiKeyHeader"})

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
# ----------------------------------------------------------------------


if __name__ == "__main__":
    import uvicorn
    # Keep module path matching your imports (app.*) and bind to loopback for Caddy
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, workers=2)
