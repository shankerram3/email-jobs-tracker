"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from .config import settings
from .database import init_db
from .routers import applications, sync, analytics, auth_router, langgraph, reprocess


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Job Application Tracker API",
    description="Track job applications from Gmail with LangGraph AI classification",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(applications.router)
app.include_router(sync.router)
app.include_router(analytics.router)
app.include_router(auth_router.router)
app.include_router(langgraph.router)
app.include_router(reprocess.router)

@app.get("/api/health")
def health():
    return {"status": "ok"}

def _frontend_dist_dir() -> Path:
    """
    Where the built frontend assets live.

    - In Docker (single-container): set FRONTEND_DIST_DIR=/app/frontend_dist
    - In local dev: frontend is typically served by Vite, but this still allows
      `npm run build` + serving from FastAPI if `frontend/dist` exists.
    """
    env = (os.getenv("FRONTEND_DIST_DIR") or "").strip()
    if env:
        return Path(env)
    # repo_root/backend/app/main.py -> repo_root/
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "frontend" / "dist"


def _serve_spa_file(dist: Path, rel_path: str) -> FileResponse | HTMLResponse:
    """
    Serve a file from the frontend dist folder, falling back to index.html for SPA routes.
    """
    rel_path = (rel_path or "").lstrip("/")
    if rel_path.startswith("api"):
        # Don't ever treat /api as a frontend route.
        raise HTTPException(status_code=404, detail="Not found")

    index = dist / "index.html"
    if not dist.exists() or not index.exists():
        return HTMLResponse(
            content="Frontend build not found. Run `npm run build` in `frontend/` or set FRONTEND_DIST_DIR.",
            status_code=404,
        )

    candidate = (dist / rel_path) if rel_path else index
    if candidate.exists() and candidate.is_file():
        return FileResponse(candidate)

    # SPA fallback: serve index.html for client-side routes
    return FileResponse(index)


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def frontend_root():
    dist = _frontend_dist_dir()
    return _serve_spa_file(dist, "")


@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def frontend_catch_all(path: str):
    dist = _frontend_dist_dir()
    return _serve_spa_file(dist, path)
