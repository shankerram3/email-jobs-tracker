"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routers import applications, sync, analytics, auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Job Application Tracker API",
    description="Track job applications from Gmail with AI classification",
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


@app.get("/")
def read_root():
    return {"message": "Job Application Tracker API", "docs": "/docs"}
