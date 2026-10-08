/**
 * MoorSense Buoy Domain Types
 * Phase 2: Real-Time OMNI Buoy Location Mapping
 */

export type BuoyStatus = 'SAFE' | 'WARNING' | 'CRITICAL' | 'ADRIFT' | 'OFFLINE';

export interface BuoyLocation {
  /** Unique Buoy identifier, e.g. 'OMNI-BD08', 'OMNI-AD06' */
  id: string;
  /** Human-readable station name */
  name: string;
  /** Geographic Latitude in decimal degrees (-90 to +90) */
  latitude: number;
  /** Geographic Longitude in decimal degrees (-180 to +180) */
  longitude: number;
  /** ISO 8601 timestamp of last reported telemetry */
  timestamp?: string;
  /** Operational mooring & integrity status */
  status?: BuoyStatus;
  /** Oceanic Basin / Region (e.g., 'Bay of Bengal', 'Arabian Sea') */
  region?: string;
  /** Mooring depth in meters */
  depthMeters?: number;
  /** Watch circle radius in meters */
  watchCircleRadiusMeters?: number;
  /** Optional drift velocity if ADRIFT or in free drift */
  driftVector?: {
    headingDeg: number;
    speedKnots: number;
  };
  /** Real-time sensor telemetry sample */
  telemetry?: {
    tensionKiloNewtons?: number;
    surfaceCurrentKnots?: number;
    waveHeightMeters?: number;
    batteryVolts?: number;
    seaSurfaceTemperature?: number;
  };
}

export type BuoyUpdateListener = (buoys: BuoyLocation[]) => void;

/**
 * Data adapter abstraction for buoy location streaming.
 * Decouples the rendering layer from backend transport (REST, WebSocket, Kafka, static).
 */
export interface IBuoyDataAdapter {
  /** Identifier of the data source (e.g., 'NIOT/INCOIS OMNI Network', 'WebSocket Stream') */
  readonly sourceName: string;

  /** Fetch current snapshot of buoy locations */
  fetchBuoys(): Promise<BuoyLocation[]>;

  /** Subscribe to real-time location updates */
  subscribe(listener: BuoyUpdateListener): () => void;

  /** Update single buoy position (for simulations or live telemetry ingest) */
  updateBuoyLocation?(id: string, lat: number, lon: number): void;

  /** Clean up resources and event subscriptions */
  dispose(): void;
}
