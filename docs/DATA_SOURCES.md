# Data Sources

## Official INCOIS OMNI Buoy Network

MoorSense retrieves observations from the Indian National Centre for Ocean Information Services (INCOIS) Ocean Observation Network (OON) OMNI buoy programme.

### Station Catalog

- **Endpoint**: `https://www.incois.gov.in/geoserver/JointPortal/ows`
- **Service**: WFS 1.0.0 GetFeature
- **TypeName**: `JointPortal:Omni_Buoy`
- **Format**: GeoJSON
- **Fields**: ID, Programme, Agency, Reporting, registry coordinates

Only stations with `Programme == "OMNI"` are included. Registry coordinates represent deployment positions, not real-time GPS.

### Observation Data

- **Endpoint**: `https://www.incois.gov.in/site/datainfo/moored_omnidata_stock.jsp` (UTC)
- **Parameters**: Discovered from actual HTML `<select>` options per station
- **Format**: Embedded JSON arrays in Highcharts-style HTML
- **Timestamps**: Unix epoch milliseconds, genuine UTC (validated by `useUTC: true` contract)

**Timestamp correction (October 2026):** The older endpoint `moored_data_stock_download.jsp` used IST-offset epochs (UTC+5:30), which caused a 5.5-hour display error. MoorSense now uses the UTC endpoint `moored_omnidata_stock.jsp` which provides correct UTC epochs. The provider validates the UTC contract (`useUTC: true` and `Time (UTC)` axis label) and fails closed if the contract is broken.

### Supported Parameters

#### Meteorology (12 source keys → 10 canonical)

| Source Key | Canonical | Unit | Notes |
|-----------|-----------|------|-------|
| air_temperature | airTemperature | °C | Most stations |
| air_pressure | pressure | hPa | Most stations |
| humidity | humidity | % | Most stations |
| rainfall | rainfall | mm | Some stations |
| wind_speed | windSpeed | m/s | RESTRICTED on some stations |
| wind_direction | windDirection | ° | RESTRICTED on some stations |
| wind_gust | windGust | m/s | RESTRICTED on some stations |
| irradiance | radiation | W/m² | Some stations |
| shortwave_radiation / swr | shortWaveRadiation | W/m² | Some stations |
| longwave_radiation / lwr | longWaveRadiation | W/m² | Some stations |

#### Waves (13 source keys → 8 canonical)

| Source Key | Canonical | Unit |
|-----------|-----------|------|
| hm0 / significant_wave_height | waveHeight | m |
| tp / wave_period / mean_wave_period | wavePeriod | s |
| wave_direction / mwd / mean_wave_direction | waveDirection | ° |
| swell_height | swellHeight | m |
| swell_period | swellPeriod | s |
| swell_direction | swellDirection | ° |
| wind_wave_height | windWaveHeight | m |
| wind_wave_period | windWavePeriod | s |

#### Currents (2 source keys + depth profiles)

| Source Key | Canonical | Unit |
|-----------|-----------|------|
| current_speed | currentSpeed | m/s |
| current_direction | currentDirection | ° |
| current_speed_Nm | profile: current | m/s |
| current_direction_Nm | profile: current | ° |

#### Ocean (4 source keys + depth profiles)

| Source Key | Canonical | Unit |
|-----------|-----------|------|
| sst / sea_surface_temperature | sst | °C |
| conductivity | conductivity | S/m |
| surface_salinity | salinity | PSU |
| water_temperature_Nm | profile: temperature | °C |
| salinity_Nm | profile: salinity | PSU |

### Per-Buoy Availability

Not every station offers every parameter. The provider discovers what each station actually offers by reading the HTML `<select>` element. Each parameter per buoy is classified:

| Status | Meaning |
|--------|---------|
| AVAILABLE | Station offers parameter, usable observation exists |
| RESTRICTED | Station/parameter exists but download access is restricted by INCOIS |
| NOT_OFFERED | Station's parameter selector does not contain this parameter |
| NO_DATA | Parameter accessible but no observation currently exists |
| SOURCE_UNAVAILABLE | Source could not be reached or did not return usable data |

Use `GET /api/buoys/{id}/parameters` to inspect per-parameter availability for any station.

### Restrictions

- Wind data is RESTRICTED on several stations (INCOIS restricts downloads)
- Stations AD09, AD10, BD12 return no usable public observations (RESTRICTED_STATIONS)
- Not all stations offer wave or current parameters
- Commercial reproduction requires INCOIS permission per their disclaimer

### Observed Cadence

Approximately 3-hourly observation reporting. Source epochs are the authoritative timestamps. HTTP response time is NOT observation time.

### Access Policy

- Public research access
- No authentication bypass
- Rate limited via semaphore (max 3 concurrent requests)
- User-Agent: `MoorSense/1.0 public OMNI research viewer`
- robots.txt and access restrictions are honored

## Data Classification

| Classification | Meaning |
|---------------|---------|
| MEASURED | Directly observed by the buoy sensor, sourced from INCOIS |
| STATIC_AUTHORITATIVE | Engineering/deployment metadata from authoritative NIOT/OOS documents |
| DERIVED | Calculated by MoorSense from measured + static inputs (screening level) |
| UNAVAILABLE | Required conceptually but not obtainable from currently authorized sources |

## Static Mooring Configuration — REQUIRED FROM NIOT

The following engineering parameters are currently UNAVAILABLE and require authoritative NIOT/OOS deployment documentation:

- Buoy dimensions (length, width, height)
- Buoy mass / displacement / buoyancy
- Fairlead geometry
- Water depth at deployment
- Anchor coordinates
- Number of mooring lines
- Line length, diameter, material
- Line stiffness (EA), density
- Pretension
- Chain/wire/rope segment properties
- Seabed type and friction coefficient

Until authoritative configuration is provided, all mooring-derived quantities (tension, angle, utilization, safety factor) return `INSUFFICIENT_CONFIGURATION`.
