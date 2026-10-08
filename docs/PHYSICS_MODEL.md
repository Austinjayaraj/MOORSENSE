# Physics Model

## Overview

MoorSense computes environmental forces and estimated mooring tension from real telemetry observations combined with static mooring configuration. All results are classified as **DERIVED** and labeled `estimated_tension`, never `measured_tension`.

## Environmental Force Calculations

### Wind Drag

```
F_wind = 0.5 * rho_air * Cd_wind * A_projected * V_wind²
```

| Parameter | Value | Source |
|-----------|-------|--------|
| rho_air | 1.225 kg/m³ | Standard atmosphere |
| Cd_wind | 1.2 | Standard drag coefficient for bluff bodies |
| A_projected | From mooring config | STATIC (when available) |
| V_wind | From telemetry | MEASURED |

### Current Drag

```
F_current = 0.5 * rho_water * Cd_current * A_submerged * V_current²
```

| Parameter | Value | Source |
|-----------|-------|--------|
| rho_water | 1025.0 kg/m³ | Standard seawater density |
| Cd_current | 1.0 | Standard underwater drag coefficient |
| A_submerged | width × draft (0.5 × height) | STATIC (when available) |
| V_current | From telemetry | MEASURED (currently UNAVAILABLE from INCOIS) |

### Wave Forcing

```
model_level = "screening"
```

Simplified Morison-type inertia estimate:

```
particle_velocity = pi * Hs / T
F_wave = 0.5 * rho_water * Cd * width * draft * particle_velocity²
```

**This is NOT an engineering-grade wave force calculation.** It provides an order-of-magnitude screening estimate only. A validated hydrodynamic model (e.g., diffraction analysis, RAO-based) would be required for engineering-grade results.

### Force Resolution

Individual forces are resolved into a resultant horizontal force vector:

```
Fx = sum(Fi * sin(theta_i))
Fy = sum(Fi * cos(theta_i))
F_total = sqrt(Fx² + Fy²)
theta_total = atan2(Fx, Fy)
```

## Quasi-Static Catenary Mooring Solver

### Method

The solver uses classical catenary equations for each mooring line:

1. **Catenary parameter**: `a = H / w` where H is horizontal tension and w is weight per unit length
2. **Suspended length**: `s = sqrt(d² + 2*a*d)` where d is water depth
3. **Grounded length**: `L_ground = L_total - s`
4. **Seabed friction**: `F_friction = mu * w * L_ground`
5. **Vertical tension**: `V = w * s`
6. **Resultant tension**: `T = sqrt(H² + V²)`
7. **Line angle**: `theta = atan2(V, H)`

### Per-Line Output

```json
{
  "line_id": "LINE_01",
  "estimated_tension_N": 125000.0,
  "horizontal_tension_N": 85000.0,
  "vertical_tension_N": 91200.0,
  "line_angle_deg": 47.0,
  "utilization_ratio": 0.25,
  "safety_factor": 4.0,
  "model_status": "VALIDATED_INPUTS"
}
```

### Utilization and Safety

```
utilization = T / breaking_strength
safety_factor = breaking_strength / T
```

### Risk Levels

| Utilization | Risk Level |
|-------------|------------|
| ≤ 0.5 | LOW |
| 0.5 – 0.8 | MODERATE |
| > 0.8 | HIGH |

## Model Limitations

1. **Static analysis only**: No dynamic amplification, fatigue, or time-domain simulation
2. **Equal load sharing**: Horizontal force distributed equally across all lines
3. **Single-segment lines**: Multi-segment composite lines use the first segment properties
4. **No current profile**: Uses surface current only, no depth-varying current
5. **Screening-level waves**: Simplified Morison estimate, not RAO-based
6. **No VIV**: Vortex-induced vibration not modeled
7. **No line-line interaction**: Lines are treated independently

## Model Status Values

| Status | Meaning |
|--------|---------|
| VALIDATED_INPUTS | All required inputs available, calculation complete |
| PARTIAL_INPUTS | Some lines have missing configuration |
| INSUFFICIENT_CONFIGURATION | Mooring configuration not available |
| NO_OBSERVATION | No telemetry observation to drive calculation |
