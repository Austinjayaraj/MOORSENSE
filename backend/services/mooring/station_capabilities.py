"""Station capability profiles for environmental parameter availability.

Availability statuses must remain distinct — never convert:
  NO_DATA → 0
  NOT_OFFERED → 0
  UNKNOWN → 0
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict

ParameterStatus = Literal[
    "MEASURED", "NO_DATA", "NOT_OFFERED",
    "SOURCE_UNAVAILABLE", "RESTRICTED", "UNKNOWN",
]


class ParameterCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ParameterStatus = "UNKNOWN"
    notes: str | None = None


class StationCapabilityProfile(BaseModel):
    """Per-station sensor availability profile.

    Updated from live parameter_status returned by IncoisBuoyProvider.
    These are OBSERVED availabilities, not manufacturer specifications.
    """
    model_config = ConfigDict(extra="forbid")
    station_id: str
    # Meteorology
    wind_speed: ParameterCapability = ParameterCapability()
    wind_direction: ParameterCapability = ParameterCapability()
    wind_gust: ParameterCapability = ParameterCapability()
    air_temperature: ParameterCapability = ParameterCapability()
    air_pressure: ParameterCapability = ParameterCapability()
    humidity: ParameterCapability = ParameterCapability()
    rainfall: ParameterCapability = ParameterCapability()
    irradiance: ParameterCapability = ParameterCapability()
    # Waves
    significant_wave_height: ParameterCapability = ParameterCapability()
    wave_period: ParameterCapability = ParameterCapability()
    wave_direction: ParameterCapability = ParameterCapability()
    swell_height: ParameterCapability = ParameterCapability()
    swell_period: ParameterCapability = ParameterCapability()
    # Currents
    current_speed: ParameterCapability = ParameterCapability()
    current_direction: ParameterCapability = ParameterCapability()
    # Ocean
    sst: ParameterCapability = ParameterCapability()
    surface_salinity: ParameterCapability = ParameterCapability()
    temperature_profile: ParameterCapability = ParameterCapability()
    salinity_profile: ParameterCapability = ParameterCapability()
    current_profile: ParameterCapability = ParameterCapability()

    def environmental_completeness(self) -> str:
        has_wind = self.wind_speed.status == "MEASURED"
        has_current = self.current_speed.status == "MEASURED"
        has_waves = self.significant_wave_height.status == "MEASURED"
        if has_wind and has_current and has_waves:
            return "COMPLETE"
        if has_wind and has_current:
            return "PARTIAL_NO_WAVES"
        if has_wind and has_waves:
            return "PARTIAL_NO_CURRENT"
        if has_wind:
            return "WIND_ONLY"
        if has_current or has_waves:
            return "PARTIAL"
        return "INSUFFICIENT"


_INCOIS_STATUS_MAP = {
    "AVAILABLE": "MEASURED",
    "NO_DATA": "NO_DATA",
    "NOT_OFFERED": "NOT_OFFERED",
    "SOURCE_UNAVAILABLE": "SOURCE_UNAVAILABLE",
    "RESTRICTED": "RESTRICTED",
}

_INCOIS_TO_CAPABILITY_FIELD = {
    "wind_speed": "wind_speed",
    "wind_direction": "wind_direction",
    "wind_gust": "wind_gust",
    "air_temperature": "air_temperature",
    "air_pressure": "air_pressure",
    "humidity": "humidity",
    "rainfall": "rainfall",
    "irradiance": "irradiance",
    "hm0": "significant_wave_height",
    "significant_wave_height": "significant_wave_height",
    "tp": "wave_period",
    "wave_period": "wave_period",
    "wave_direction": "wave_direction",
    "swell_height": "swell_height",
    "swell_period": "swell_period",
    "current_speed": "current_speed",
    "current_direction": "current_direction",
    "sst": "sst",
    "surface_salinity": "surface_salinity",
}


def build_capability_profile(station_id: str, provider_status: dict) -> StationCapabilityProfile:
    """Build a StationCapabilityProfile from IncoisBuoyProvider parameter_status dict."""
    caps: dict[str, ParameterCapability] = {}
    for incois_key, field_name in _INCOIS_TO_CAPABILITY_FIELD.items():
        incois_status = provider_status.get(incois_key)
        if incois_status:
            caps[field_name] = ParameterCapability(
                status=_INCOIS_STATUS_MAP.get(incois_status, "UNKNOWN"))
    # Profile detection: if any water_temperature_Nm key exists, mark profile
    if any(k.startswith("water_temperature_") for k in provider_status):
        caps["temperature_profile"] = ParameterCapability(status="MEASURED")
    if any(k.startswith("salinity_") for k in provider_status
           if provider_status.get(k) == "AVAILABLE"):
        caps["salinity_profile"] = ParameterCapability(status="MEASURED")
    if any(k.startswith("current_speed_") for k in provider_status):
        caps["current_profile"] = ParameterCapability(status="MEASURED")
    return StationCapabilityProfile(station_id=station_id, **caps)
