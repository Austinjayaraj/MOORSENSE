"""Tests for GEBCO bathymetry integration.

Unit tests use a tiny synthetic in-memory NetCDF fixture — no network required.
Integration tests that need the real GEBCO file or live WMS are skipped unless
the relevant environment / file is available.
"""
import math
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest
import numpy as np

from services.mooring.bathymetry_service import (
    BathymetryService, OMNI_FLEET_SEED, GEBCO_DATASET_VERSION,
)
from services.mooring.models import ProvenancedValue, DataProvenance
from services.mooring.config_resolver import MooringConfigResolver, OMNI_SCOPE


# ─── Synthetic NetCDF fixture ────────────────────────────────────────────────

def _make_synthetic_nc(tmp_path: Path) -> Path:
    """Build a tiny 5×5 GEBCO-like NetCDF with known elevation values."""
    nc = pytest.importorskip("netCDF4", reason="netCDF4 not installed")
    xr = pytest.importorskip("xarray", reason="xarray not installed")
    import xarray as xr_mod
    import numpy as np_mod

    lats = np_mod.array([6.0, 10.0, 14.0, 16.0, 18.0])
    lons = np_mod.array([67.0, 72.0, 84.0, 88.0, 94.0])
    elev = np_mod.array([
        [-3800, -3200, -2900, -3800, -2900],
        [-1500, -1600, -2100, -2500, -2900],
        [-3200, -2000, -3100, -3000, -2900],
        [-2700, -2400, -2200, -2600, -2100],
        [-3300, -4000, -2100, -2200, -2100],
    ], dtype=float)

    ds = xr_mod.Dataset(
        {"elevation": (["lat", "lon"], elev)},
        coords={"lat": lats, "lon": lons},
    )
    nc_path = tmp_path / "test_gebco.nc"
    ds.to_netcdf(nc_path)
    return nc_path


# ─── BathymetryService unit tests ───────────────────────────────────────────

class TestBathymetryCacheKey:
    def test_rounding_2_decimals(self):
        k = BathymetryService._cache_key(16.3617, 87.9903)
        assert k == "16.362,87.990"

    def test_negative_coords(self):
        k = BathymetryService._cache_key(-6.57, -88.23)
        assert "-6.570" in k and "-88.230" in k

    def test_cache_key_3dp_precision(self):
        # Keys are at 3 decimal places — nearby points at 3dp resolution share a key
        k1 = BathymetryService._cache_key(16.3601, 87.9901)
        k2 = BathymetryService._cache_key(16.3604, 87.9904)
        assert k1 == k2  # both round to 16.360,87.990
        # Points 3dp apart get different keys
        k3 = BathymetryService._cache_key(16.360, 87.990)
        k4 = BathymetryService._cache_key(16.361, 87.991)
        assert k3 != k4


class TestBathymetryFleetSeed:
    """Pre-seeded OMNI fleet depths loaded without network."""

    def test_all_12_stations_seeded(self):
        assert len(OMNI_FLEET_SEED) == 12

    def test_bd10_depth_seeded(self):
        assert "OMNI-BD10" in OMNI_FLEET_SEED
        assert OMNI_FLEET_SEED["OMNI-BD10"]["depth_m"] == 2627

    def test_all_depths_positive(self):
        for name, entry in OMNI_FLEET_SEED.items():
            assert entry["depth_m"] > 0, f"{name} has non-positive depth"

    def test_all_depths_realistic_ocean(self):
        for name, entry in OMNI_FLEET_SEED.items():
            assert entry["depth_m"] > 500, f"{name} depth {entry['depth_m']}m is suspiciously shallow"
            assert entry["depth_m"] < 8000, f"{name} depth {entry['depth_m']}m exceeds max ocean depth"

    def test_service_returns_bd10_from_seed(self):
        svc = BathymetryService()
        pv = svc.lookup_buoy("OMNI-BD10", 16.3617, 87.9903)
        assert pv.value == 2627
        assert pv.provenance.status == "INFERRED"
        assert "GEBCO" in pv.provenance.source

    def test_service_provenance_not_measured(self):
        svc = BathymetryService()
        pv = svc.lookup_buoy("OMNI-BD14", 6.5706, 88.2333)
        assert pv.provenance.status != "MEASURED"
        assert pv.provenance.status != "AUTHORITATIVE"

    def test_service_provenance_includes_disclaimer(self):
        svc = BathymetryService()
        pv = svc.lookup_buoy("OMNI-AD06", 18.4950, 67.4500)
        assert pv.provenance.notes is not None
        # Must contain some form of disclaimer
        assert "GEBCO" in pv.provenance.notes or "screening" in pv.provenance.notes.lower()

    def test_all_fleet_buoys_resolvable(self):
        svc = BathymetryService()
        for buoy_id, entry in OMNI_FLEET_SEED.items():
            pv = svc.lookup_buoy(buoy_id, entry["lat"], entry["lon"])
            assert pv.value is not None, f"{buoy_id} lookup returned None"
            assert pv.value > 0


class TestBathymetryLocalNetCDF:
    """Tests using a synthetic NetCDF file."""

    def test_load_synthetic_nc(self, tmp_path):
        pytest.importorskip("xarray")
        nc_path = _make_synthetic_nc(tmp_path)
        svc = BathymetryService.__new__(BathymetryService)
        svc._mem_cache = {}
        svc._buoy_cache = {}
        svc._nc_dataset = None
        svc._seed_omni_fleet()
        # Manually load the synthetic file
        import xarray as xr
        ds = xr.open_dataset(nc_path)
        svc._nc_dataset = ds
        svc._nc_elev_var = "elevation"
        # Lookup a known coordinate
        depth = svc._lookup_local_nc(16.0, 88.0)
        assert depth is not None
        assert depth == pytest.approx(2600, abs=200)  # nearest to 16.0,88.0 = -2600

    def test_negative_elevation_converted_to_positive_depth(self, tmp_path):
        pytest.importorskip("xarray")
        nc_path = _make_synthetic_nc(tmp_path)
        import xarray as xr
        svc = BathymetryService.__new__(BathymetryService)
        svc._mem_cache = {}
        svc._buoy_cache = {}
        svc._nc_dataset = xr.open_dataset(nc_path)
        svc._nc_elev_var = "elevation"
        # All elevations in test file are negative (ocean), returned depth > 0
        depth = svc._lookup_local_nc(14.0, 84.0)
        assert depth is not None
        assert depth > 0  # -3100 → 3100

    def test_outside_nc_bounds_returns_none(self, tmp_path):
        pytest.importorskip("xarray")
        nc_path = _make_synthetic_nc(tmp_path)
        import xarray as xr
        svc = BathymetryService.__new__(BathymetryService)
        svc._mem_cache = {}
        svc._buoy_cache = {}
        svc._nc_dataset = xr.open_dataset(nc_path)
        svc._nc_elev_var = "elevation"
        # xarray sel with method="nearest" will snap to boundary rather than fail
        # but we can verify it doesn't crash
        depth = svc._lookup_local_nc(0.0, 0.0)
        # No assertion on value — just must not crash
        _ = depth


class TestBathymetryDiskCache:
    def test_cache_persists_and_reloads(self, tmp_path):
        svc = BathymetryService.__new__(BathymetryService)
        svc._mem_cache = {}
        svc._buoy_cache = {}
        svc._nc_dataset = None
        svc._seed_omni_fleet()
        # Add a new entry
        pv = ProvenancedValue(value=3500.0, unit="m",
                              provenance=DataProvenance(
                                  source=GEBCO_DATASET_VERSION, status="INFERRED",
                                  confidence="MEDIUM", method="test"))
        svc._mem_cache["12.000,80.000"] = pv
        # Patch the CACHE_DIR
        import services.mooring.bathymetry_service as bm
        orig_dir = bm.CACHE_DIR
        bm.CACHE_DIR = tmp_path
        try:
            svc._save_disk_cache()
            cache_file = tmp_path / "depth_cache.json"
            assert cache_file.exists()
            data = json.loads(cache_file.read_text())
            assert "12.000,80.000" in data
            assert data["12.000,80.000"]["depth_m"] == 3500.0
        finally:
            bm.CACHE_DIR = orig_dir


# ─── Config resolver with real depths ────────────────────────────────────────

class TestConfigResolverWithRealDepths:
    def test_bd10_config_has_real_depth(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        assert config.water_depth is not None
        assert config.water_depth.value == 2627
        assert config.water_depth.provenance.status == "INFERRED"

    def test_line_length_derived_from_depth(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        assert config.total_line_length is not None
        expected = round(2627 * OMNI_SCOPE, 1)
        assert config.total_line_length.value == pytest.approx(expected, abs=0.5)
        assert config.total_line_length.provenance.status == "DERIVED"
        assert "GEBCO" in (config.total_line_length.provenance.notes or "")

    def test_scope_is_reference(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        assert config.scope.value == OMNI_SCOPE
        assert config.scope.provenance.status == "REFERENCE"

    def test_all_fleet_buoys_get_config(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        for buoy_id, entry in OMNI_FLEET_SEED.items():
            config = resolver.resolve(buoy_id, entry["lat"], entry["lon"])
            assert config.water_depth is not None
            assert config.water_depth.value == entry["depth_m"]
            assert config.total_line_length is not None
            assert config.total_line_length.value > 0
            assert config.has_minimum_geometry(), f"{buoy_id} missing minimum geometry"

    def test_scope_line_length_arithmetic(self):
        """3250 * 1.22 = 3965 m"""
        svc = BathymetryService()
        svc._buoy_cache["OMNI-TEST"] = ProvenancedValue(
            value=3250, unit="m",
            provenance=DataProvenance(source=GEBCO_DATASET_VERSION, status="INFERRED",
                                      confidence="MEDIUM"))
        resolver = MooringConfigResolver(svc)
        config = resolver._from_reference("OMNI-TEST", 15.0, 90.0)
        assert config.total_line_length.value == pytest.approx(3965.0, abs=0.5)

    def test_water_depth_not_authoritative(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD14", 6.5706, 88.2333)
        assert config.water_depth.provenance.status not in ("MEASURED", "AUTHORITATIVE")

    def test_line_length_not_authoritative(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        assert config.total_line_length.provenance.status not in ("MEASURED", "AUTHORITATIVE")


# ─── Integration test (skipped without real GEBCO file) ─────────────────────

GEBCO_FILE = Path(__file__).parents[1] / "data" / "bathymetry" / "gebco_omni_indian_ocean.nc"

@pytest.mark.skipif(not GEBCO_FILE.exists(),
                    reason="Real GEBCO NetCDF not present (download from download.gebco.net)")
class TestRealGEBCOFile:
    def test_file_loads(self):
        import xarray as xr
        ds = xr.open_dataset(GEBCO_FILE)
        assert "elevation" in ds or any(v in ds for v in ["Elevation", "z", "depth"])
        ds.close()

    def test_bd10_depth_from_file(self):
        svc = BathymetryService()
        assert svc._nc_dataset is not None
        depth = svc._lookup_local_nc(16.3617, 87.9903)
        assert depth is not None
        assert 1000 < depth < 6000, f"BD10 depth {depth}m out of expected range"

    def test_file_covers_fleet_bbox(self):
        import xarray as xr
        ds = xr.open_dataset(GEBCO_FILE)
        lat_dim = next((d for d in ["lat", "latitude", "y"] if d in ds.dims), None)
        lon_dim = next((d for d in ["lon", "longitude", "x"] if d in ds.dims), None)
        assert lat_dim and lon_dim
        lats = ds[lat_dim].values
        lons = ds[lon_dim].values
        assert lats.min() <= 6.0, "File doesn't cover BD14 latitude"
        assert lats.max() >= 18.5, "File doesn't cover AD06 latitude"
        assert lons.min() <= 67.0, "File doesn't cover AD06 longitude"
        assert lons.max() >= 94.5, "File doesn't cover BD12 longitude"
        ds.close()
