# Coupled Buoy Equilibrium Model (Audited)

## What It Solves

Given total horizontal environmental force F_env and mooring geometry,
finds the buoy horizontal offset x where:

    F_environment(x) + F_mooring_restoring(x) = 0

This is a static equilibrium problem. The mooring restoring force is computed
using the existing catenary solver for each candidate offset.

## Implementation

`services/mooring/buoy_equilibrium.py` → `solve_equilibrium()`

Method: bisection search for offset where F_restoring = F_env.
The restoring force at each candidate offset is found by solving the catenary
geometry (binary search for H such that horizontal span = offset).

## Outputs

| Field | Provenance |
|-------|-----------|
| predicted_offset_m | MODELLED |
| predicted_bearing_deg | MODELLED |
| predicted_fairlead_tension_n | MODELLED |
| predicted_line_angle_deg | MODELLED |
| predicted_anchor_load_n | MODELLED |
| equilibrium_residual_n | MODELLED |

All outputs are MODELLED. None are MEASURED unless a physical sensor confirms.

## GPS Validation (Phase E/F)

MooringResponse has GPS validation fields:
- `observed_offset_m` — null until GPS track available
- `position_error_m` — null until GPS track available
- `buoy_motion_validation_status` = NOT_VALIDATED

When a GPS position track becomes available, compare:
- predicted_offset_m (from equilibrium)
- observed_offset_m (from GPS)
→ position_error_m = |predicted - observed|
→ This is BUOY MOTION VALIDATION, not tension validation.

## Coordinate System

    +X = East, +Y = North
    Bearing: 0° = North, 90° = East (navigation standard)

## Direction Convention (INCOIS / Meteorological)

    Wind/current direction: FROM which bearing the agent arrives.
    A "0° (North) wind" blows FROM north, pushes buoy SOUTHWARD.
    Conversion: force_direction = (from_bearing + 180) % 360
    Fx = F_mag * sin(radians(force_direction))
    Fy = F_mag * cos(radians(force_direction))

    This is verified by test_coordinate_convention.

## Physics Residuals Exposed

At convergence, both Fx and Fy residuals are verified:
    |Fx_residual| < CONVERGENCE_TOL_N
    |Fy_residual| < CONVERGENCE_TOL_N
    force_residual_magnitude_n < CONVERGENCE_TOL_N

These are the primary physics diagnostics.

## Why Radial Formulation Is Valid for Single-Point Mooring

For a symmetric single-point mooring:
- The restoring force is purely radial (pulls toward anchor)
- At equilibrium, the buoy moves in the direction of net environmental force
- The magnitude equation H(offset) = |F_env| fully determines the solution
- Vector components are reconstructed from the environmental force bearing

If a multi-line asymmetric mooring were added, a full 2D Newton solver
would be required.

## Assumptions

- Quasi-static (no dynamic response)
- 2D horizontal equilibrium only
- Single mooring line
- All line properties are ASSUMPTION unless authoritative data exists
- Buoy geometry is REFERENCE/ASSUMPTION
- Water depth from GEBCO (INFERRED)

## Solver Status Values

| Status | Meaning |
|--------|---------|
| CONVERGED | Equilibrium found within tolerance |
| WARNING | Weak convergence (large residual) |
| FAILED | Mooring restoring never reaches env force |
| INSUFFICIENT_CONFIGURATION | Missing geometry |

## Limitations

- No dynamic amplification
- No current or wave forcing on the line shape (only on buoy)
- Anchor assumed stationary
- No VIV, fatigue, or snap loading
- Not validated against GPS or tension measurements
