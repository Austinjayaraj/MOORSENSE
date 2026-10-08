# Mooring Configuration

## Overview

Each OMNI buoy has a mooring system anchoring it to the seabed. MoorSense maintains buoy-specific mooring engineering configuration for digital twin calculations.

**IMPORTANT**: No mooring engineering values are fabricated. Fields without authoritative source data remain `null` with `availability: "UNAVAILABLE"`.

## Configuration Schema

### mooring_configurations table

| Field | Type | Description | Status |
|-------|------|-------------|--------|
| buoy_id | TEXT | Station identifier | Required |
| deployment_id | TEXT | Specific deployment identifier | UNAVAILABLE |
| water_depth_m | FLOAT | Water depth at mooring location | UNAVAILABLE |
| anchor_latitude | FLOAT | Anchor position latitude | UNAVAILABLE |
| anchor_longitude | FLOAT | Anchor position longitude | UNAVAILABLE |
| number_of_lines | INT | Number of mooring lines | UNAVAILABLE |
| buoy_mass_kg | FLOAT | Hull mass | UNAVAILABLE |
| buoy_buoyancy_N | FLOAT | Buoyancy force | UNAVAILABLE |
| buoy_length_m | FLOAT | Hull length | UNAVAILABLE |
| buoy_width_m | FLOAT | Hull width/diameter | UNAVAILABLE |
| buoy_height_m | FLOAT | Hull height | UNAVAILABLE |
| projected_area_m2 | FLOAT | Wind-exposed projected area | UNAVAILABLE |
| waterplane_area_m2 | FLOAT | Waterplane area | UNAVAILABLE |
| center_of_gravity | JSONB | CoG coordinates | UNAVAILABLE |
| center_of_buoyancy | JSONB | CoB coordinates | UNAVAILABLE |
| pretension_N | FLOAT | Mooring pretension | UNAVAILABLE |
| seabed_type | TEXT | Seabed classification | UNAVAILABLE |
| seabed_friction_coefficient | FLOAT | Seabed friction | UNAVAILABLE |
| source | TEXT | Configuration data source | — |
| source_document | TEXT | Reference document | — |
| verified | BOOL | Whether configuration is verified | false |

### mooring_line_segments table

| Field | Type | Description | Status |
|-------|------|-------------|--------|
| line_id | TEXT | Line identifier (e.g., LINE_01) | Required |
| segment | INT | Segment number within line | Required |
| length_m | FLOAT | Segment length | UNAVAILABLE |
| diameter_mm | FLOAT | Line diameter | UNAVAILABLE |
| material | TEXT | Line material | UNAVAILABLE |
| mass_per_m | FLOAT | Mass per unit length | UNAVAILABLE |
| weight_per_m | FLOAT | Submerged weight per unit length | UNAVAILABLE |
| axial_stiffness | FLOAT | Axial stiffness (EA) | UNAVAILABLE |
| breaking_strength_N | FLOAT | Minimum breaking load | UNAVAILABLE |

## Anchor Position

Authoritative anchor coordinates are stored when available. If not:

```json
{
  "anchor_latitude": null,
  "anchor_longitude": null
}
```

The anchor is NOT assumed to be directly underneath the buoy. Buoy position from INCOIS is the registry deployment position, not current GPS.

## Populating Configuration

To enable mooring analysis for a specific buoy, insert a row into `mooring_configurations` with verified engineering data from authoritative mooring design documents. Until then, all calculations return:

```json
{
  "model_status": "INSUFFICIENT_CONFIGURATION",
  "requires_authoritative_mooring_configuration": true
}
```

## Data Classification

All mooring configuration fields are classified as:
- **STATIC**: When populated from verified engineering documents
- **UNAVAILABLE**: When no authoritative source has provided the value

No estimated or generic values are substituted for unknown mooring parameters.
