import type { BuoyLocation } from './buoyTypes';

// Locations come only from the backend's authoritative INCOIS station catalog.
export async function fetchBuoyLocations(signal: AbortSignal): Promise<BuoyLocation[]> {
  const response = await fetch('/api/buoys', { signal });
  if (!response.ok) throw new Error('Station metadata unavailable');
  const data = await response.json();
  if (!Array.isArray(data)) throw new Error('Invalid catalog response');
  return data.map(({ id, name, type, latitude, longitude, status, coordinateKind, metadataSource, metadataRetrievedAt }) =>
    ({ id, name, type, latitude, longitude, status, coordinateKind, metadataSource, metadataRetrievedAt }));
}
