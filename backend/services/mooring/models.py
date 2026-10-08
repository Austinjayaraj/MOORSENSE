"""Mooring Digital Twin data models with full provenance tracking.

Every quantity carries provenance so the system never silently converts
assumptions into facts.

ProvenanceStatus taxonomy:
  MEASURED         — Direct sensor observation (e.g. INCOIS telemetry)
  AUTHORITATIVE    — From NIOT/OOS deployment records, verified
  REFERENCE        — From published OMNI design documentation
  INFERRED         — Derived from external datasets (e.g. GEBCO)
  DERIVED          — Calculated from other known quantities
  MODELLED         — From a numerical model (not direct observation)
  ESTIMATED        — Statistical/trajectory estimate, not verified
  ASSUMPTION       — Engineering assumption with no published source
  UNAVAILABLE      — Not obtainable from current sources
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

ProvenanceStatus = Literal[
    "MEASURED", "AUTHORITATIVE", "REFERENCE", "INFERRED",
    "DERIVED", "MODELLED", "ESTIMATED", "ASSUMPTION", "UNAVAILABLE",
]
Confidence = Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
RiskState = Literal["NORMAL", "WATCH", "WARNING", "CRITICAL", "INSUFFICIENT_DATA"]
SolverStatus = Literal["CONVERGED", "WARNING", "FAILED", "NOT_RUN"]


class DataProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    status: ProvenanceStatus
    confidence: Confidence = "UNKNOWN"
    timestamp: datetime | None = None
    method: str | None = None
    notes: str | None = None


class ProvenancedValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float | None = None
    unit: str = ""
    provenance: DataProvenance


class MooringLineSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    segment_index: int = 0
    length_m: float | None = None
    diameter_m: float | None = None
    material: str | None = None
    mass_per_length_kg_m: float | None = None
    submerged_weight_n_m: float | None = None
    elastic_modulus_pa: float | None = None
    axial_stiffness_n: float | None = None
    breaking_strength_n: float | None = None
    drag_coefficient: float = 1.2
    added_mass_coefficient: float = 1.0
    buoyancy_per_length_n_m: float | None = None
    provenance: DataProvenance = Field(default_factory=lambda: DataProvenance(
        source="OMNI_REFERENCE", status="REFERENCE", confidence="LOW"))


class MooringConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buoy_id: str
    configuration_version: str = "v1"
    configuration_status: str = "REFERENCE"
    mooring_type: str = "INVERSE_CATENARY"
    water_depth: ProvenancedValue | None = None
    scope: ProvenancedValue | None = None
    total_line_length: ProvenancedValue | None = None
    line_count: ProvenancedValue | None = None
    buoy_mass_kg: ProvenancedValue | None = None
    buoy_displacement_m3: ProvenancedValue | None = None
    buoy_net_buoyancy_n: ProvenancedValue | None = None
    buoy_diameter_m: ProvenancedValue | None = None
    buoy_height_m: ProvenancedValue | None = None
    projected_area_m2: ProvenancedValue | None = None
    waterplane_area_m2: ProvenancedValue | None = None
    fairlead_depth_m: ProvenancedValue | None = None
    anchor_latitude: ProvenancedValue | None = None
    anchor_longitude: ProvenancedValue | None = None
    pretension_n: ProvenancedValue | None = None
    seabed_type: str | None = None
    seabed_friction: float | None = None
    segments: list[MooringLineSegment] = Field(default_factory=list)

    def effective_depth(self) -> float | None:
        return self.water_depth.value if self.water_depth else None

    def effective_line_length(self) -> float | None:
        return self.total_line_length.value if self.total_line_length else None

    def effective_scope(self) -> float | None:
        return self.scope.value if self.scope else None

    def has_minimum_geometry(self) -> bool:
        return (self.effective_depth() is not None
                and self.effective_line_length() is not None
                and len(self.segments) > 0
                and any(s.submerged_weight_n_m is not None for s in self.segments))


class EnvironmentalState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wind_speed_ms: float | None = None
    wind_direction_deg: float | None = None
    current_speed_ms: float | None = None
    current_direction_deg: float | None = None
    wave_height_m: float | None = None
    wave_period_s: float | None = None
    wave_direction_deg: float | None = None
    current_profile: list[dict] | None = None
    sources: dict[str, ProvenanceStatus] = Field(default_factory=dict)


class EnvironmentalForceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wind_force_n: float | None = None
    wind_fx: float | None = None
    wind_fy: float | None = None
    current_force_n: float | None = None
    current_fx: float | None = None
    current_fy: float | None = None
    wave_force_n: float | None = None
    wave_fx: float | None = None
    wave_fy: float | None = None
    total_horizontal_n: float | None = None
    total_fx: float | None = None
    total_fy: float | None = None
    total_direction_deg: float | None = None
    model_level: str = "screening"


class ConfidenceBreakdown(BaseModel):
    """Per-dimension confidence for a mooring response."""
    model_config = ConfigDict(extra="forbid")
    telemetry: Confidence = "UNKNOWN"
    bathymetry: Confidence = "UNKNOWN"
    configuration: Confidence = "UNKNOWN"
    environmental_data: Confidence = "UNKNOWN"
    anchor_position: Confidence = "UNKNOWN"
    material_properties: Confidence = "UNKNOWN"
    physics_convergence: Confidence = "UNKNOWN"
    overall: Confidence = "UNKNOWN"


class MeasuredTensionHook(BaseModel):
    """Optional physical tension measurement for model validation.

    Populated only when an actual tension sensor reading exists.
    NEVER fabricate this value.
    """
    model_config = ConfigDict(extra="forbid")
    measured_tension_n: float
    sensor_id: str | None = None
    observation_timestamp: str | None = None
    source: str = "PHYSICAL_SENSOR"
    model_error_n: float | None = None
    model_relative_error: float | None = None


class MooringResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buoy_id: str
    observation_timestamp: str
    model_timestamp: str
    fairlead_tension_n: float | None = None
    anchor_tension_n: float | None = None
    horizontal_tension_n: float | None = None
    vertical_tension_n: float | None = None
    line_angle_deg: float | None = None
    horizontal_excursion_m: float | None = None
    watch_circle_radius_m: float | None = None
    watch_circle_utilization: float | None = None
    utilization: float | None = None
    safety_factor: float | None = None
    environmental_forces: EnvironmentalForceResult | None = None
    # Per-dimension confidence breakdown
    confidence_breakdown: ConfidenceBreakdown | None = None
    risk_state: RiskState = "INSUFFICIENT_DATA"
    confidence: Confidence = "UNKNOWN"
    solver_status: SolverStatus = "NOT_RUN"
    solver_iterations: int | None = None
    solver_residual: float | None = None
    # Physics decomposition: which forces contributed
    forcing_mode: str = "UNKNOWN"  # WIND_ONLY, WIND_CURRENT, FULL, NO_DATA, etc.
    environmental_completeness: str = "UNKNOWN"
    # Optional physical measurement hook (null until sensor data available)
    measured_tension: MeasuredTensionHook | None = None
    # Coupled equilibrium prediction (MODELLED — not GPS)
    predicted_offset_m: float | None = None
    predicted_bearing_deg: float | None = None
    equilibrium_residual_n: float | None = None
    equilibrium_solver_status: str | None = None
    # GPS validation (null unless GPS track is available)
    observed_offset_m: float | None = None
    observed_bearing_deg: float | None = None
    position_error_m: float | None = None
    bearing_error_deg: float | None = None
    buoy_motion_validation_status: str = "NOT_VALIDATED"
    # Model version stack for reproducibility
    model_version: str = "MoorSense Physics v0.4"
    configuration_version: str = "v1"
    physics_version: str = "catenary-0.4"


class TrajectoryPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float
    longitude: float
    timestamp: str
    distance_from_anchor_m: float | None = None
    bearing_from_anchor_deg: float | None = None


class TrajectoryAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buoy_id: str
    centroid_latitude: float | None = None
    centroid_longitude: float | None = None
    estimated_anchor_latitude: float | None = None
    estimated_anchor_longitude: float | None = None
    watch_circle_radius_m: float | None = None
    max_excursion_m: float | None = None
    points: list[TrajectoryPoint] = Field(default_factory=list)
    provenance: DataProvenance = Field(default_factory=lambda: DataProvenance(
        source="GPS_TRAJECTORY", status="ESTIMATED", confidence="MEDIUM",
        method="trajectory_centroid"))


class FleetDigitalTwinEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buoy_id: str
    tension_kn: float | None = None
    angle_deg: float | None = None
    utilization: float | None = None
    safety_factor: float | None = None
    risk: RiskState = "INSUFFICIENT_DATA"
    confidence: Confidence = "UNKNOWN"
    observation_timestamp: str | None = None
    solver_status: SolverStatus = "NOT_RUN"
    error: str | None = None
