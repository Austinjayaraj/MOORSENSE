"""Mooring configuration resolver.

Resolution priority:
1. Authoritative NIOT/OOS deployment configuration (if in database)
2. OMNI reference architecture + bathymetry + inference

Published NIOT/INCOIS material describes OMNI as a single-point inverse-catenary
mooring with scope ≈ 1.22 (OSICON-23 abstract volume). This establishes the
architecture but NOT the exact deployed dimensions of every buoy.

Every derived/inferred value is explicitly marked with provenance.
"""
import logging
import math
from .models import (
    MooringConfiguration, MooringLineSegment, ProvenancedValue, DataProvenance,
)
from .bathymetry_service import BathymetryService

log = logging.getLogger(__name__)

# ── Published OMNI design constraints ──────────────────────────────────────
# REFERENCE: These values appear in published NIOT/INCOIS documentation
# (OSICON-23 abstract volume). They describe the OMNI design class, NOT
# individual station deployments.

OMNI_SCOPE = 1.22           # REFERENCE — published OMNI design constraint
OMNI_MOORING_TYPE = "INVERSE_CATENARY"  # REFERENCE
OMNI_LINE_COUNT = 1         # REFERENCE — single-point mooring

# ── OMNI reference buoy geometry ───────────────────────────────────────────
# REFERENCE: Approximate design-class values. NOT individual measurements.
OMNI_REF_BUOY_DIAMETER_M = 2.7
OMNI_REF_BUOY_HEIGHT_M = 3.2
OMNI_REF_BUOY_MASS_KG = 2500.0
OMNI_REF_BUOY_DISPLACEMENT_M3 = 5.0
OMNI_REF_BUOY_NET_BUOYANCY_N = 24525.0  # ≈ 2500 kg × 9.81 m/s²

# ── Line properties ────────────────────────────────────────────────────────
# ASSUMPTION: These are typical values for deep-sea inverse-catenary moorings.
# No authoritative NIOT deployment specification has been verified for these.
# They are retained ONLY as screening-level assumptions.
OMNI_REF_ROPE_DIAMETER_M = 0.032           # ASSUMPTION
OMNI_REF_ROPE_MASS_PER_M = 0.85            # ASSUMPTION
OMNI_REF_ROPE_SUBMERGED_WEIGHT_N_M = 2.0   # ASSUMPTION
OMNI_REF_ROPE_BREAKING_STRENGTH_N = 250000.0  # ASSUMPTION — unverified
OMNI_REF_CHAIN_DIAMETER_M = 0.022          # ASSUMPTION
OMNI_REF_CHAIN_MASS_PER_M = 9.7            # ASSUMPTION
OMNI_REF_CHAIN_SUBMERGED_WEIGHT_N_M = 84.0 # ASSUMPTION
OMNI_REF_CHAIN_BREAKING_STRENGTH_N = 490000.0  # ASSUMPTION — unverified

# Segment proportions are entirely assumed — not from any deployment record.
_SEG_UPPER_FRAC = 0.05    # ASSUMPTION
_SEG_MIDDLE_FRAC = 0.85   # ASSUMPTION
_SEG_LOWER_FRAC = 0.10    # ASSUMPTION


def _ref_prov(notes: str | None = None) -> DataProvenance:
    """REFERENCE: published OMNI design constraint."""
    return DataProvenance(
        source="OMNI_DESIGN_REFERENCE", status="REFERENCE", confidence="MEDIUM",
        method="omni_reference_architecture", notes=notes)


def _assumption_prov(notes: str) -> DataProvenance:
    """ASSUMPTION: engineering assumption with no verified deployment source."""
    return DataProvenance(
        source="MoorSense_assumption", status="ASSUMPTION", confidence="LOW",
        method="engineering_assumption", notes=notes)


def _inferred_prov(method: str, notes: str | None = None) -> DataProvenance:
    return DataProvenance(
        source="MoorSense", status="INFERRED", confidence="MEDIUM",
        method=method, notes=notes)


def _derived_prov(method: str, notes: str | None = None) -> DataProvenance:
    return DataProvenance(
        source="MoorSense", status="DERIVED", confidence="MEDIUM",
        method=method, notes=notes)


class MooringConfigResolver:
    def __init__(self, bathymetry: BathymetryService | None = None):
        self.bathymetry = bathymetry or BathymetryService()

    def resolve(self, buoy_id: str, latitude: float, longitude: float,
                authoritative: dict | None = None) -> MooringConfiguration:
        """Resolve the mooring configuration for a buoy.

        If authoritative config exists, uses it. Otherwise builds a reference
        configuration from OMNI design constraints + bathymetry.
        """
        if authoritative:
            return self._from_authoritative(buoy_id, authoritative)
        return self._from_reference(buoy_id, latitude, longitude)

    def _from_authoritative(self, buoy_id: str, config: dict) -> MooringConfiguration:
        log.info("[CONFIG] %s using authoritative configuration", buoy_id)
        auth_prov = DataProvenance(
            source=config.get("source", "NIOT"),
            status="AUTHORITATIVE", confidence="HIGH",
            method="deployment_records",
            notes=config.get("source_document"))
        segments = []
        for s in config.get("segments", []):
            segments.append(MooringLineSegment(
                name=s.get("name", "segment"), segment_index=s.get("segment_index", 0),
                length_m=s.get("length_m"), diameter_m=s.get("diameter_m"),
                material=s.get("material"),
                mass_per_length_kg_m=s.get("mass_per_length_kg_m"),
                submerged_weight_n_m=s.get("submerged_weight_n_m"),
                breaking_strength_n=s.get("breaking_strength_n"),
                provenance=auth_prov))
        return MooringConfiguration(
            buoy_id=buoy_id, configuration_status="AUTHORITATIVE",
            mooring_type=config.get("mooring_type", OMNI_MOORING_TYPE),
            water_depth=ProvenancedValue(
                value=config.get("water_depth_m"), unit="m", provenance=auth_prov),
            scope=ProvenancedValue(
                value=config.get("scope", OMNI_SCOPE), unit="", provenance=auth_prov),
            total_line_length=ProvenancedValue(
                value=config.get("total_line_length_m"), unit="m", provenance=auth_prov),
            line_count=ProvenancedValue(value=config.get("line_count", 1), unit="", provenance=auth_prov),
            buoy_mass_kg=ProvenancedValue(
                value=config.get("buoy_mass_kg"), unit="kg", provenance=auth_prov),
            segments=segments)

    def _from_reference(self, buoy_id: str, latitude: float, longitude: float) -> MooringConfiguration:
        log.info("[CONFIG] %s building reference configuration", buoy_id)

        # Step 1: Water depth from bathymetry (uses buoy_id for exact cache hit)
        depth_pv = self.bathymetry.lookup_buoy(buoy_id, latitude, longitude)
        depth_m = depth_pv.value

        # Step 2: Line length from scope
        scope_pv = ProvenancedValue(value=OMNI_SCOPE, unit="", provenance=_ref_prov(
            "OMNI single-point mooring scope from OSICON-23 / NIOT published design"))
        line_length = depth_m * OMNI_SCOPE if depth_m else None
        dataset_ref = depth_pv.provenance.source if depth_pv and depth_pv.provenance else "GEBCO"
        line_length_pv = ProvenancedValue(
            value=round(line_length, 1) if line_length else None, unit="m",
            provenance=DataProvenance(
                source="MoorSense", status="DERIVED", confidence="MEDIUM",
                method="scope_x_depth",
                notes=f"{dataset_ref} water depth × OMNI reference scope 1.22. "
                      "Not a measurement of deployed line length.")) if line_length else ProvenancedValue(
            value=None, unit="m",
            provenance=DataProvenance(source="MoorSense", status="UNAVAILABLE", confidence="UNKNOWN",
                                     method="scope_x_depth", notes="Water depth unavailable"))

        # Step 3: Reference buoy geometry
        projected_area = math.pi * (OMNI_REF_BUOY_DIAMETER_M / 2) ** 2
        waterplane_area = math.pi * (OMNI_REF_BUOY_DIAMETER_M / 2) ** 2

        # Step 4: Reference line segments (simplified 3-segment model)
        segments = self._build_reference_segments(line_length)

        return MooringConfiguration(
            buoy_id=buoy_id,
            configuration_status="REFERENCE",
            mooring_type=OMNI_MOORING_TYPE,
            water_depth=depth_pv,
            scope=scope_pv,
            total_line_length=line_length_pv,
            line_count=ProvenancedValue(value=OMNI_LINE_COUNT, unit="",
                                        provenance=_ref_prov("OMNI single-point mooring")),
            buoy_mass_kg=ProvenancedValue(value=OMNI_REF_BUOY_MASS_KG, unit="kg",
                                          provenance=_ref_prov("OMNI design class reference")),
            buoy_displacement_m3=ProvenancedValue(value=OMNI_REF_BUOY_DISPLACEMENT_M3, unit="m³",
                                                   provenance=_ref_prov()),
            buoy_net_buoyancy_n=ProvenancedValue(value=OMNI_REF_BUOY_NET_BUOYANCY_N, unit="N",
                                                  provenance=_ref_prov()),
            buoy_diameter_m=ProvenancedValue(value=OMNI_REF_BUOY_DIAMETER_M, unit="m",
                                             provenance=_ref_prov()),
            buoy_height_m=ProvenancedValue(value=OMNI_REF_BUOY_HEIGHT_M, unit="m",
                                           provenance=_ref_prov()),
            projected_area_m2=ProvenancedValue(value=round(projected_area, 2), unit="m²",
                                               provenance=_derived_prov("pi*r²_from_reference_diameter")),
            waterplane_area_m2=ProvenancedValue(value=round(waterplane_area, 2), unit="m²",
                                                provenance=_derived_prov("pi*r²_from_reference_diameter")),
            fairlead_depth_m=ProvenancedValue(value=1.5, unit="m",
                                              provenance=_assumption_prov(
                                                  "Fairlead depth assumed 1.5m below waterline. "
                                                  "Not verified from NIOT deployment records.")),
            pretension_n=ProvenancedValue(
                value=round(OMNI_REF_BUOY_NET_BUOYANCY_N * 0.1, 0) if depth_m else None,
                unit="N",
                provenance=_assumption_prov(
                    "Pretension assumed as 10% of reference net buoyancy (2453 N). "
                    "NOT authoritative deployment pretension. "
                    "Actual mooring installation pretension is unknown.")),
            segments=segments,
        )

    def _build_reference_segments(self, total_length: float | None) -> list[MooringLineSegment]:
        if total_length is None or total_length <= 0:
            return []

        # Simplified 3-segment inverse catenary model:
        # Upper: ~5% polypropylene rope (near surface)
        # Middle: ~85% nylon rope (compliant section)
        # Lower: ~10% chain (near anchor)
        upper_len = round(total_length * 0.05, 1)
        middle_len = round(total_length * 0.85, 1)
        lower_len = round(total_length * 0.10, 1)

        _line_note = (
            "ASSUMPTION: line properties are typical values for deep-sea inverse-catenary "
            "moorings. No authoritative NIOT/OOS deployment specification has been verified. "
            "MBL, diameter, and weight are unvalidated engineering assumptions. "
            "Utilization and safety factor derived from these are not engineering-certified.")
        return [
            MooringLineSegment(
                name="upper_rope", segment_index=0,
                length_m=upper_len,
                diameter_m=OMNI_REF_ROPE_DIAMETER_M,
                material="polypropylene_rope",
                mass_per_length_kg_m=OMNI_REF_ROPE_MASS_PER_M,
                submerged_weight_n_m=OMNI_REF_ROPE_SUBMERGED_WEIGHT_N_M,
                breaking_strength_n=OMNI_REF_ROPE_BREAKING_STRENGTH_N,
                drag_coefficient=1.2,
                provenance=_assumption_prov(_line_note)),
            MooringLineSegment(
                name="compliant_nylon", segment_index=1,
                length_m=middle_len,
                diameter_m=OMNI_REF_ROPE_DIAMETER_M,
                material="nylon_rope",
                mass_per_length_kg_m=OMNI_REF_ROPE_MASS_PER_M,
                submerged_weight_n_m=OMNI_REF_ROPE_SUBMERGED_WEIGHT_N_M,
                breaking_strength_n=OMNI_REF_ROPE_BREAKING_STRENGTH_N,
                drag_coefficient=1.2,
                provenance=_assumption_prov(_line_note)),
            MooringLineSegment(
                name="anchor_chain", segment_index=2,
                length_m=lower_len,
                diameter_m=OMNI_REF_CHAIN_DIAMETER_M,
                material="stud_link_chain",
                mass_per_length_kg_m=OMNI_REF_CHAIN_MASS_PER_M,
                submerged_weight_n_m=OMNI_REF_CHAIN_SUBMERGED_WEIGHT_N_M,
                breaking_strength_n=OMNI_REF_CHAIN_BREAKING_STRENGTH_N,
                drag_coefficient=2.4,
                provenance=_assumption_prov(_line_note)),
        ]
