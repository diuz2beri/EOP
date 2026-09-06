from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pacificeo.api import router
from pacificeo.scheduler import AoiScheduler
from pacificeo.settings import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    scheduler: BackgroundScheduler | None = None
    if settings.scheduler_enabled:
        service = AoiScheduler(settings)
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(
            service.tick,
            "interval",
            seconds=settings.scheduler_poll_seconds,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="PacificEO Monitor", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().dashboard_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Tenant-ID"],
)


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}
