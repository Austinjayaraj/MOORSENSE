/**
 * Cloud Service for NOAA Science On a Sphere (SOS) "Clouds - Real-time" Dataset.
 * Fetches near-real-time satellite cloud composite metadata and provides URLs
 * for dynamically updated, transparent cloud textures.
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface CloudMetadata {
  status: 'LIVE' | 'CACHED' | 'STANDBY';
  dataset: string;
  source_agency: string;
  satellites: string[];
  cadence: string;
  resolution: string;
  projection: string;
  timestamp: string;
  frame_id: string;
  texture_url: string;
  last_fetch_attempt?: string | null;
  last_successful_fetch?: string | null;
  available: boolean;
}

const DEFAULT_METADATA: CloudMetadata = {
  status: 'LIVE',
  dataset: 'NOAA Clouds - Real-time (Science On a Sphere)',
  source_agency: 'NOAA / Aviation Weather Center',
  satellites: [
    'GOES-West (136.9°W)',
    'GOES-East (75°W)',
    'Meteosat-10 (0°)',
    'Meteosat-9 (45.5°E)',
    'Himawari (140.7°E)',
    'Suomi-NPP & JPSS',
  ],
  cadence: '10 minutes',
  resolution: '2048x1024',
  projection: 'Cylindrical Equirectangular',
  timestamp: new Date().toISOString(),
  frame_id: 'noaa_live_cyl_current.jpg',
  texture_url: `${API_BASE}/api/clouds/texture/latest`,
  available: true,
};

export const FALLBACK_TEXTURE_URL = '/textures/earth_clouds_noaa_latest.png';

export async function fetchCloudMetadata(): Promise<CloudMetadata> {
  try {
    const res = await fetch(`${API_BASE}/api/clouds/latest`, {
      headers: { Accept: 'application/json' },
    });
    if (!res.ok) {
      return DEFAULT_METADATA;
    }
    const data: CloudMetadata = await res.json();
    return data;
  } catch {
    // If backend isn't reachable, return client fallback with local texture
    return {
      ...DEFAULT_METADATA,
      texture_url: FALLBACK_TEXTURE_URL,
    };
  }
}

export function getLatestCloudTextureUrl(timestamp?: string): string {
  const base = `${API_BASE}/api/clouds/texture/latest`;
  if (timestamp) {
    return `${base}?t=${encodeURIComponent(timestamp)}`;
  }
  return base;
}
