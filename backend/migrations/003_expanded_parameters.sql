-- Expanded telemetry columns for wave, current, and radiation parameters.
-- Existing rows retain NULLs for new columns; no data is destroyed.
-- wave_height/wave_period/wave_direction already exist from migration 001.

ALTER TABLE buoy_observations ADD COLUMN IF NOT EXISTS shortwave_radiation DOUBLE PRECISION;
ALTER TABLE buoy_observations ADD COLUMN IF NOT EXISTS longwave_radiation DOUBLE PRECISION;
ALTER TABLE buoy_observations ADD COLUMN IF NOT EXISTS wind_gust DOUBLE PRECISION;

ALTER TABLE buoy_observations ADD COLUMN IF NOT EXISTS swell_height DOUBLE PRECISION;
ALTER TABLE buoy_observations ADD COLUMN IF NOT EXISTS swell_period DOUBLE PRECISION;
ALTER TABLE buoy_observations ADD COLUMN IF NOT EXISTS swell_direction DOUBLE PRECISION;
ALTER TABLE buoy_observations ADD COLUMN IF NOT EXISTS wind_wave_height DOUBLE PRECISION;
ALTER TABLE buoy_observations ADD COLUMN IF NOT EXISTS wind_wave_period DOUBLE PRECISION;

ALTER TABLE buoy_observations ADD COLUMN IF NOT EXISTS conductivity DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS buoy_observations_source_idx ON buoy_observations(source);
CREATE INDEX IF NOT EXISTS buoy_observations_event_idx ON buoy_observations(event_id);
