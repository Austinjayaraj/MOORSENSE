/**
 * BuoyMarkersLayer:
 * Renders the operational array of OMNI buoy points on the 3D Earth,
 * directly using the exact Ocean Sentry point/marker visual style.
 */

import { BuoyMarker } from './BuoyMarker';
import type { BuoyLocation } from '../../../services/buoy/buoyTypes';

interface BuoyMarkersLayerProps {
  buoys: BuoyLocation[];
  selectedBuoyId: string | null;
  onSelectBuoy: (buoy: BuoyLocation) => void;
  onHoverBuoy?: (buoy: BuoyLocation | null) => void;
  visible?: boolean;
}

export function BuoyMarkersLayer({
  buoys,
  selectedBuoyId,
  onSelectBuoy,
  onHoverBuoy,
  visible = true,
}: BuoyMarkersLayerProps) {
  if (!visible) return null;

  return (
    <group name="BuoyMarkersLayer">
      {buoys.map((buoy) => (
        <BuoyMarker
          key={buoy.id}
          buoy={buoy}
          isSelected={selectedBuoyId === buoy.id}
          onSelect={onSelectBuoy}
          onHover={onHoverBuoy}
        />
      ))}
    </group>
  );
}
