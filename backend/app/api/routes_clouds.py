import os
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from app.services.cloud_service import cloud_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clouds", tags=["Satellite Clouds"])

STATIC_FALLBACK_TEXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../public/textures/earth_clouds.png")
)

@router.get("/latest")
async def get_latest_clouds_meta():
    """
    Returns metadata for the real-time NOAA SOS Clouds dataset,
    including satellite constellation, valid timestamp, cadence, and texture URL.
    """
    return cloud_service.get_metadata()

@router.api_route("/texture/latest", methods=["GET", "HEAD"])
async def get_latest_cloud_texture():
    """
    Returns the latest real-time transparent satellite cloud composite as a PNG image.
    Uses NOAA SOS infrared imagery with alpha transparency so the underlying
    MoorSense globe and buoy positions remain visible.
    """
    path = cloud_service.get_latest_processed_path()
    if not path or not os.path.exists(path):
        # If cache is still populating, trigger a fetch and serve static fallback seamlessly
        if os.path.exists(STATIC_FALLBACK_TEXTURE):
            return FileResponse(
                STATIC_FALLBACK_TEXTURE,
                media_type="image/png",
                headers={
                    "Cache-Control": "public, max-age=30",
                    "X-Cloud-Source": "MoorSense-Base-Fallback"
                }
            )
        raise HTTPException(status_code=404, detail="Cloud texture not available yet")

    return FileResponse(
        path,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=60",
            "X-Cloud-Source": "NOAA-Science-On-a-Sphere-RealTime",
            "X-Cloud-Frame": cloud_service.latest_frame_id or "latest"
        }
    )

@router.get("/texture/{frame_name}")
async def get_specific_cloud_texture(frame_name: str):
    """
    Returns a specific timestamped transparent cloud PNG for historical playback or smooth crossfading.
    """
    safe_name = os.path.basename(frame_name)
    if not safe_name.endswith(".png"):
        safe_name += "_transparent.png"

    path = os.path.join(cloud_service.cache_dir, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Texture frame {safe_name} not found")

    return FileResponse(
        path,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Cloud-Source": "NOAA-Science-On-a-Sphere-RealTime"
        }
    )

@router.post("/refresh")
async def trigger_cloud_refresh(background_tasks: BackgroundTasks):
    """
    Triggers an on-demand download and processing of the newest NOAA satellite cloud frame.
    """
    background_tasks.add_task(cloud_service.fetch_latest_frame)
    return {
        "status": "QUEUED",
        "message": "NOAA real-time satellite cloud refresh task started"
    }
