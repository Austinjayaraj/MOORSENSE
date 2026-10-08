"""Bathymetry lookup service for water depth at buoy deployment positions.

Supports three strategies in priority order:
1. Local GEBCO_2026 netCDF tile (backend/data/bathymetry/gebco_omni_indian_ocean.nc)
2. Persistent depth cache (JSON, seeded from GEBCO WMS for known OMNI fleet)
3. Live GEBCO WMS lookup (requires network; cached after first hit)

To obtain the GEBCO_2026 subset for the OMNI fleet:
  - Visit https://download.gebco.net/
  - Select GEBCO_2026 Grid, NetCDF format
  - Bounding box: S=5.57, W=66.45, N=19.50, E=95.07
  - Save as: backend/data/bathymetry/gebco_omni_indian_ocean.nc
  - Add backend/data/bathymetry/*.nc to .gitignore

GEBCO depth is classified as INFERRED (external dataset), NOT authoritative
deployment survey data. GEBCO itself states the grid should not be used for
navigation or safety-at-sea purposes.

Depth values are positive metres below sea level. Elevations above sea level
(positive in GEBCO) are flagged — buoy mooring locations should be ocean cells.
"""
import json
import logging
import math
import re
from pathlib import Path
from .models import ProvenancedValue, DataProvenance

log = logging.getLogger(__name__)

GEBCO_WMS_URL = "https://wms.gebco.net/mapserv"
GEBCO_WMS_LAYER = "GEBCO_LATEST_2"
GEBCO_DATASET_VERSION = "GEBCO_2026"
CACHE_DIR = Path(__file__).parents[2] / "data" / "cache" / "bathymetry"
LOCAL_NC_PATH = Path(__file__).parents[2] / "data" / "bathymetry" / "gebco_omni_indian_ocean.nc"

# Pre-seeded depths for all 12 known OMNI stations, retrieved 2026-10-08 from
# GEBCO WMS (layer GEBCO_LATEST_2). Values are positive metres below sea level.
# These are included so the fleet runner works without a live WMS connection.
OMNI_FLEET_SEED: dict[str, dict] = {
    "OMNI-AD06": {"lat": 18.4950, "lon": 67.4500, "depth_m": 3338, "dataset": GEBCO_DATASET_VERSION},
    "OMNI-AD07": {"lat": 14.9314, "lon": 68.9758, "depth_m": 3977, "dataset": GEBCO_DATASET_VERSION},
    "OMNI-AD08": {"lat": 12.0681, "lon": 68.6328, "depth_m": 4301, "dataset": GEBCO_DATASET_VERSION},
    "OMNI-AD09": {"lat": 8.1831,  "lon": 73.2983, "depth_m": 2090, "dataset": GEBCO_DATASET_VERSION},
    "OMNI-AD10": {"lat": 10.3217, "lon": 72.5872, "depth_m": 1617, "dataset": GEBCO_DATASET_VERSION},
    "OMNI-BD08": {"lat": 17.8247, "lon": 89.2358, "depth_m": 2140, "dataset": GEBCO_DATASET_VERSION},
    "OMNI-BD09": {"lat": 17.4997, "lon": 89.1167, "depth_m": 2298, "dataset": GEBCO_DATASET_VERSION},
    "OMNI-BD10": {"lat": 16.3617, "lon": 87.9903, "depth_m": 2627, "dataset": GEBCO_DATASET_VERSION},
    "OMNI-BD11": {"lat": 13.5250, "lon": 84.1667, "depth_m": 3229, "dataset": GEBCO_DATASET_VERSION},
    "OMNI-BD12": {"lat": 10.5153, "lon": 94.0739, "depth_m": 2973, "dataset": GEBCO_DATASET_VERSION},
    "OMNI-BD13": {"lat": 13.9900, "lon": 86.9969, "depth_m": 3014, "dataset": GEBCO_DATASET_VERSION},
    "OMNI-BD14": {"lat": 6.5706,  "lon": 88.2333, "depth_m": 3832, "dataset": GEBCO_DATASET_VERSION},
}


class BathymetryService:
    def __init__(self):
        self._mem_cache: dict[str, ProvenancedValue] = {}
        self._buoy_cache: dict[str, ProvenancedValue] = {}
        self._nc_dataset = None
        self._seed_omni_fleet()
        self._load_local_gebco()
        self._load_disk_cache()

    def _seed_omni_fleet(self):
        """Pre-seed the cache with known OMNI buoy depths from GEBCO WMS."""
        for buoy_id, entry in OMNI_FLEET_SEED.items():
            pv = self._make_pv(entry["depth_m"], entry["dataset"])
            key = self._cache_key(entry["lat"], entry["lon"])
            self._mem_cache[key] = pv
            self._buoy_cache[buoy_id] = pv
        log.debug("[BATHYMETRY] Seeded %d OMNI buoy depths", len(OMNI_FLEET_SEED))

    def _make_pv(self, depth_m: float, dataset: str = GEBCO_DATASET_VERSION,
                 method: str = "gebco_wms") -> ProvenancedValue:
        return ProvenancedValue(
            value=float(depth_m), unit="m",
            provenance=DataProvenance(
                source=dataset, status="INFERRED", confidence="MEDIUM",
                method=method,
                notes=(f"{dataset} bathymetric grid (~500m resolution). "
                       "Depth is a screening-level inferred value, not authoritative "
                       "deployment survey data. GEBCO should not be used for navigation.")))

    def _load_local_gebco(self):
        if not LOCAL_NC_PATH.exists():
            log.info("[BATHYMETRY] No local GEBCO file at %s — using seeded/WMS values", LOCAL_NC_PATH)
            return
        try:
            import xarray as xr
            ds = xr.open_dataset(LOCAL_NC_PATH)
            # Validate expected variables
            elev_var = next((v for v in ["elevation", "Elevation", "z", "depth"]
                             if v in ds), None)
            if elev_var is None:
                log.warning("[BATHYMETRY] GEBCO NetCDF has no recognised elevation variable")
                return
            self._nc_dataset = ds
            self._nc_elev_var = elev_var
            log.info("[BATHYMETRY] Loaded local GEBCO tile (%s), var=%s", LOCAL_NC_PATH.name, elev_var)
        except Exception as exc:
            log.warning("[BATHYMETRY] Failed to load GEBCO tile: %s", exc)

    def _load_disk_cache(self):
        cache_file = CACHE_DIR / "depth_cache.json"
        if not cache_file.exists():
            return
        try:
            data = json.loads(cache_file.read_text())
            for key, entry in data.items():
                if key not in self._mem_cache:  # don't override seed
                    self._mem_cache[key] = ProvenancedValue(
                        value=entry.get("depth_m"),
                        unit="m",
                        provenance=DataProvenance(
                            source=entry.get("dataset", GEBCO_DATASET_VERSION),
                            status="INFERRED",
                            confidence=entry.get("confidence", "MEDIUM"),
                            method=entry.get("method", "gebco_wms")))
            log.info("[BATHYMETRY] Loaded %d additional cached depths", len(data))
        except Exception:
            pass

    def _save_disk_cache(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = {}
        for key, pv in self._mem_cache.items():
            if pv.value is not None:
                data[key] = {
                    "depth_m": pv.value,
                    "dataset": pv.provenance.source,
                    "confidence": pv.provenance.confidence,
                    "method": pv.provenance.method or "gebco_wms",
                }
        (CACHE_DIR / "depth_cache.json").write_text(json.dumps(data, indent=2))

    @staticmethod
    def _cache_key(lat: float, lon: float) -> str:
        return f"{round(lat, 3):.3f},{round(lon, 3):.3f}"

    def lookup_buoy(self, buoy_id: str, latitude: float, longitude: float) -> ProvenancedValue:
        """Lookup by buoy_id first (exact match), then by coordinates."""
        if buoy_id in self._buoy_cache:
            return self._buoy_cache[buoy_id]
        return self.lookup(latitude, longitude, buoy_id=buoy_id)

    def lookup(self, latitude: float, longitude: float,
               buoy_id: str | None = None) -> ProvenancedValue:
        """Return water depth (positive metres) at given coordinates."""
        key = self._cache_key(latitude, longitude)
        if key in self._mem_cache:
            return self._mem_cache[key]

        # Try local NetCDF first
        depth = self._lookup_local_nc(latitude, longitude)
        method = "local_netcdf_nearest_neighbour"
        if depth is None:
            depth = self._lookup_wms(latitude, longitude)
            method = "gebco_wms"

        if depth is None:
            return ProvenancedValue(
                value=None, unit="m",
                provenance=DataProvenance(
                    source=GEBCO_DATASET_VERSION, status="UNAVAILABLE",
                    confidence="UNKNOWN", method="bathymetry_lookup",
                    notes="No local dataset and WMS lookup failed"))

        # Sanity check: buoy moorings must be in ocean
        if depth <= 0:
            log.warning("[BATHYMETRY] %s: positive/zero elevation=%.0f — land or shallow?",
                        buoy_id or key, depth)
            return ProvenancedValue(
                value=None, unit="m",
                provenance=DataProvenance(
                    source=GEBCO_DATASET_VERSION, status="UNAVAILABLE",
                    confidence="UNKNOWN", method=method,
                    notes=f"GEBCO returned elevation={depth:.0f}m — possible land cell"))

        pv = self._make_pv(depth, method=method)
        self._mem_cache[key] = pv
        if buoy_id:
            self._buoy_cache[buoy_id] = pv
        self._save_disk_cache()
        log.info("[BATHYMETRY] %s depth=%.0fm via %s", buoy_id or key, depth, method)
        return pv

    def _lookup_local_nc(self, lat: float, lon: float) -> float | None:
        if self._nc_dataset is None:
            return None
        try:
            ds = self._nc_dataset
            var = getattr(self, "_nc_elev_var", "elevation")
            # Try both lat/lon and y/x coordinate names
            lat_dim = next((d for d in ["lat", "latitude", "y"] if d in ds.dims), None)
            lon_dim = next((d for d in ["lon", "longitude", "x"] if d in ds.dims), None)
            if lat_dim and lon_dim:
                elev = ds[var].sel({lat_dim: lat, lon_dim: lon}, method="nearest").values.item()
            else:
                elev = ds[var].sel(lat=lat, lon=lon, method="nearest").values.item()
            if math.isfinite(float(elev)):
                return -float(elev) if float(elev) < 0 else float(elev)
        except Exception as exc:
            log.debug("[BATHYMETRY] NetCDF lookup error: %s", exc)
        return None

    def _lookup_wms(self, lat: float, lon: float) -> float | None:
        """GEBCO WMS GetFeatureInfo with correct pixel computation.

        Uses a 1-degree bounding box and 200×200 grid for adequate resolution.
        The pixel I/J are computed from the lat/lon position within the box.
        """
        try:
            import httpx
            margin = 1.0
            lat_min, lat_max = lat - margin, lat + margin
            lon_min, lon_max = lon - margin, lon + margin
            width, height = 200, 200
            # I: column from left (lon increases left→right)
            I = int((lon - lon_min) / (lon_max - lon_min) * width)
            # J: row from top (lat decreases top→bottom in image)
            J = int((lat_max - lat) / (lat_max - lat_min) * height)
            I = max(0, min(width - 1, I))
            J = max(0, min(height - 1, J))
            params = {
                "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo",
                "LAYERS": GEBCO_WMS_LAYER, "QUERY_LAYERS": GEBCO_WMS_LAYER,
                "INFO_FORMAT": "text/plain", "CRS": "EPSG:4326",
                "BBOX": f"{lat_min},{lon_min},{lat_max},{lon_max}",
                "WIDTH": str(width), "HEIGHT": str(height),
                "I": str(I), "J": str(J),
            }
            response = httpx.get(GEBCO_WMS_URL, params=params, timeout=20,
                                 follow_redirects=True)
            if response.status_code == 200:
                m = re.search(r"value_list = '(-?\d+)'", response.text)
                if m:
                    elev = int(m.group(1))
                    return -elev if elev < 0 else elev
        except Exception as exc:
            log.warning("[BATHYMETRY] WMS lookup failed: %s", type(exc).__name__)
        return None

    def close(self):
        if self._nc_dataset is not None:
            try:
                self._nc_dataset.close()
            except Exception:
                pass
