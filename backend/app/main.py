import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()

configure_logging(settings.log_level)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting %s v%s",
        settings.app_name,
        settings.app_version,
    )

    yield

    logger.info(
        "Shutting down %s",
        settings.app_name,
    )


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered hospitality revenue platform.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=[
        "Authorization",
        "Content-Type",
    ],
)

app.include_router(
    router,
    prefix=settings.api_prefix,
)
