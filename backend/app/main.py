import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.routes_health import router as health_router
from app.api.routes_stations import router as stations_router
from app.api.routes_ocean import router as ocean_router
from app.api.routes_comparison import router as comparison_router
from app.api.routes_anomalies import router as anomalies_router
from app.api.routes_argo import router as argo_router
from app.api.routes_ingest import router as ingest_router
from app.api.routes_clouds import router as clouds_router
from app.services.ml_service import ml_service
from app.services.anomaly_service import anomaly_service
from app.services.ocean_service import ocean_service
from app.services.cloud_service import cloud_service
import asyncio

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Ocean Sentry API",
    description="Backend for ocean model-observation comparison and anomaly detection",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(stations_router, prefix="/api")
app.include_router(ocean_router, prefix="/api")
app.include_router(comparison_router, prefix="/api")
app.include_router(anomalies_router, prefix="/api")
app.include_router(argo_router, prefix="/api")
app.include_router(ingest_router, prefix="/api")
app.include_router(clouds_router, prefix="/api")


async def periodic_cloud_sync():
    """Periodically checks NOAA SOS for new 10-minute satellite cloud frames."""
    while True:
        try:
            logger.info("Checking NOAA SOS for real-time cloud frame updates...")
            await asyncio.to_thread(cloud_service.fetch_latest_frame)
        except Exception as e:
            logger.warning(f"Periodic cloud sync encountered error: {e}")
        # NOAA publishes frames ~every 10 minutes (600 seconds)
        await asyncio.sleep(600)


@app.on_event("startup")
async def startup():
    logger.info("Ocean Sentry API starting up")
    ml_service.load_model()
    anomaly_service.run_inference(ml_service)
    ocean_service.apply_ml_status(anomaly_service)
    # Start background NOAA cloud sync
    asyncio.create_task(periodic_cloud_sync())
    logger.info("Startup complete")

