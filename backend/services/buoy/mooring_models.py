from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class MooringLineSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_id: str
    segment: int
    length_m: float | None = None
    diameter_mm: float | None = None
    material: str | None = None
    mass_per_m: float | None = None
    weight_per_m: float | None = None
    axial_stiffness: float | None = None
    breaking_strength_N: float | None = None


class MooringConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buoy_id: str
    deployment_id: str | None = None
    water_depth_m: float | None = None
    anchor_latitude: float | None = None
    anchor_longitude: float | None = None
    number_of_lines: int | None = None
    buoy_mass_kg: float | None = None
    buoy_buoyancy_N: float | None = None
    buoy_length_m: float | None = None
    buoy_width_m: float | None = None
    buoy_height_m: float | None = None
    projected_area_m2: float | None = None
    waterplane_area_m2: float | None = None
    center_of_gravity: dict | None = None
    center_of_buoyancy: dict | None = None
    pretension_N: float | None = None
    seabed_type: str | None = None
    seabed_friction_coefficient: float | None = None
    line_segments: list[MooringLineSegment] = Field(default_factory=list)
    source: str | None = None
    source_document: str | None = None
    verified: bool = False
    availability: Literal["STATIC", "UNAVAILABLE"] = "UNAVAILABLE"
    requires_authoritative_mooring_configuration: bool = True

    def is_sufficient_for_analysis(self) -> bool:
        return all([
            self.water_depth_m is not None,
            self.number_of_lines is not None and self.number_of_lines > 0,
            self.buoy_mass_kg is not None,
            self.projected_area_m2 is not None,
            len(self.line_segments) > 0,
            all(s.length_m is not None and s.weight_per_m is not None
                for s in self.line_segments),
        ])


class EnvironmentalForces(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wind_force_N: float | None = None
    wind_direction_deg: float | None = None
    current_force_N: float | None = None
    current_direction_deg: float | None = None
    wave_force_N: float | None = None
    wave_direction_deg: float | None = None
    total_horizontal_force_N: float | None = None
    total_force_direction_deg: float | None = None
    model_level: str = "screening"
    inputs_used: dict = Field(default_factory=dict)


class LineTensionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_id: str
    estimated_tension_N: float | None = None
    horizontal_tension_N: float | None = None
    vertical_tension_N: float | None = None
    line_angle_deg: float | None = None
    utilization_ratio: float | None = None
    safety_factor: float | None = None
    model_status: str = "INSUFFICIENT_CONFIGURATION"


class MooringEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    buoy_id: str
    source_observation_timestamp: str
    calculated_at: str
    environmental_forces: EnvironmentalForces
    lines: list[LineTensionResult] = Field(default_factory=list)
    max_tension_N: float | None = None
    max_utilization: float | None = None
    risk_level: str = "UNKNOWN"
    model_status: str = "INSUFFICIENT_CONFIGURATION"
