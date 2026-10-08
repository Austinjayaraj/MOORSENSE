from fastapi import APIRouter, Query, HTTPException, Request
from typing import Optional
from app.models.schemas import StationResponse
from app.services.ocean_service import ocean_service

router = APIRouter(prefix="/stations", tags=["stations"])


def _buoy_runtime(request: Request):
    return getattr(request.app.state, "buoy_runtime", None)


def _buoy_station_list(rt):
    """Build station list from BuoyRuntime's live INCOIS catalog."""
    if rt is None or not rt.buoys:
        return []
    results = []
    for buoy_id, buoy in rt.buoys.items():
        detail = rt.cache.detail(buoy)
        obs_ts = detail.get("observationTimestamp")
        received_ts = detail.get("receivedAt")
        freshness = detail.get("freshness", {})
        provider_status = detail.get("providerStatus", "CONNECTING")
        if freshness.get("state") == "LIVE":
            data_status = "LIVE"
        elif freshness.get("state") == "RECENT":
            data_status = "RECENT"
        elif freshness.get("state") == "STALE":
            data_status = "STALE"
        elif provider_status == "SOURCE_UNAVAILABLE":
            data_status = "SOURCE_UNAVAILABLE"
        elif obs_ts:
            data_status = "LATEST_AVAILABLE"
        else:
            data_status = "NO_DATA"
        results.append({
            "id": buoy.id,
            "name": buoy.name,
            "type": buoy.type,
            "latitude": buoy.latitude,
            "longitude": buoy.longitude,
            "status": buoy.status,
            "coordinateKind": buoy.coordinateKind,
            "metadataSource": buoy.metadataSource,
            "metadataRetrievedAt": buoy.metadataRetrievedAt,
            "reportingStatus": buoy.reportingStatus,
            "agency": buoy.agency,
            "latest_observation": obs_ts,
            "latest_received": received_ts,
            "data_status": data_status,
            "source": detail.get("source", "INCOIS"),
        })
    return results


@router.get("")
async def get_stations(request: Request, region: Optional[str] = Query(None)):
    rt = _buoy_runtime(request)
    buoy_stations = _buoy_station_list(rt)
    if buoy_stations:
        return buoy_stations
    return ocean_service.get_stations(region=region)


@router.get("/frontend")
async def get_frontend_stations(request: Request):
    """Stations in the format the 3D frontend expects."""
    rt = _buoy_runtime(request)
    buoy_stations = _buoy_station_list(rt)
    if buoy_stations:
        return buoy_stations
    return ocean_service.get_all_station_details()


@router.get("/{station_id}")
async def get_station(station_id: str, request: Request):
    rt = _buoy_runtime(request)
    if rt and station_id in rt.buoys:
        buoy = rt.buoys[station_id]
        detail = rt.cache.detail(buoy)
        return {**detail, "data_status": "LATEST_AVAILABLE" if detail.get("observationTimestamp") else "NO_DATA"}
    station = ocean_service.get_station(station_id)
    if station is None:
        raise HTTPException(status_code=404, detail="Station not found")
    return station


@router.get("/{station_id}/detail")
async def get_station_detail(station_id: str, request: Request):
    """Single station in the frontend-compatible format."""
    rt = _buoy_runtime(request)
    if rt and station_id in rt.buoys:
        buoy = rt.buoys[station_id]
        return rt.detail(station_id)
    detail = ocean_service.get_station_detail(station_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Station not found")
    return detail
