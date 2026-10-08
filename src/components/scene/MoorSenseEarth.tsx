import { Suspense } from 'react';
import { RealisticEarth } from './RealisticEarth';
import { CloudLayer } from './CloudLayer';
import { RealisticAtmosphere } from './RealisticAtmosphere';
import { GlobalWindLayer } from './GlobalWindLayer';
import type { WindSystemType } from '../ui/WindControlPanel';
import type { DepthLevel } from '../../types/ocean';
import type { CloudMetadata } from '../../services/cloudService';

export interface MoorSenseEarthProps {
  depth?: DepthLevel;
  sunPosition?: [number, number, number];
  showWind?: boolean;
  activeWindSystems?: Set<WindSystemType>;
  onCloudMetadataUpdate?: (meta: CloudMetadata) => void;
  children?: React.ReactNode;
}

const DEFAULT_WIND_SYSTEMS: Set<WindSystemType> = new Set([
  'trade',
  'westerlies',
  'polar',
  'monsoons',
  'breeze',
]);

/**
 * MoorSenseEarth:
 * Direct preservation of the Ocean Sentry Earth experience.
 * Encapsulates the high-fidelity Earth, cloud layer, wind streams, and atmospheric scattering
 * into a single reusable base layer for the MoorSense Mooring Integrity Digital Twin System.
 */
export function MoorSenseEarth({
  depth = 0,
  sunPosition = [12, 5, 8],
  showWind = true,
  activeWindSystems = DEFAULT_WIND_SYSTEMS,
  onCloudMetadataUpdate,
  children,
}: MoorSenseEarthProps) {
  return (
    <group name="MoorSenseEarthBaseLayer">
      <Suspense fallback={null}>
        <RealisticEarth depth={depth} sunPosition={sunPosition} />
        <CloudLayer
          depth={depth}
          sunPosition={sunPosition}
          onMetadataUpdate={onCloudMetadataUpdate}
        />
        {showWind && <GlobalWindLayer depth={depth} activeSystems={activeWindSystems} />}

        <RealisticAtmosphere sunPosition={sunPosition} />
      </Suspense>
      {/* Reusable extension slot for future real-time OMNI buoy markers, telemetry & watch circles */}
      {children}
    </group>
  );
}
