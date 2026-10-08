CREATE TABLE IF NOT EXISTS buoy_observations (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    buoy_id TEXT NOT NULL,
    observation_timestamp TIMESTAMPTZ NOT NULL,
    received_timestamp TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    wind_speed DOUBLE PRECISION, wind_direction DOUBLE PRECISION,
    air_temperature DOUBLE PRECISION, pressure DOUBLE PRECISION,
    humidity DOUBLE PRECISION, rainfall DOUBLE PRECISION,
    sst DOUBLE PRECISION, salinity DOUBLE PRECISION,
    current_speed DOUBLE PRECISION, current_direction DOUBLE PRECISION,
    wave_height DOUBLE PRECISION, wave_period DOUBLE PRECISION, wave_direction DOUBLE PRECISION,
    raw_payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS buoy_observations_buoy_id_idx ON buoy_observations(buoy_id);
CREATE INDEX IF NOT EXISTS buoy_observations_timestamp_idx ON buoy_observations(observation_timestamp);
CREATE INDEX IF NOT EXISTS buoy_observations_history_idx ON buoy_observations(buoy_id, observation_timestamp DESC);

ALTER TABLE buoy_observations ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;
ALTER TABLE buoy_observations ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;

-- Preserve original source JSON, but recognize INCOIS's lowercase psu unit.
UPDATE buoy_observations SET salinity = (raw_payload #>> '{telemetry,ocean,salinity,value}')::double precision
WHERE salinity IS NULL AND raw_payload #>> '{telemetry,ocean,salinity,unit}' IN ('psu','PSU')
AND raw_payload #>> '{telemetry,ocean,salinity,value}' IS NOT NULL;
