import { useRef, useMemo } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import type { BuoyLocation, BuoyStatus } from '../../../services/buoy/buoyTypes';
import { latLonToXYZ } from '../../../utils/oceanCalc';

interface BuoyMarkerProps {
  buoy: BuoyLocation;
  isSelected: boolean;
  isHandHovered?: boolean;
  onSelect: (buoy: BuoyLocation) => void;
  onHover?: (buoy: BuoyLocation | null) => void;
}

/**
 * Buoy state color mapping matching Ocean Sentry visual standard:
 * - Green → SAFE
 * - Yellow/amber → WARNING
 * - Red → CRITICAL / ADRIFT
 * - Grey/dim → OFFLINE
 */
export function getBuoyColor(status?: BuoyStatus): string {
  switch (status) {
    case 'SAFE':
      return '#10b981'; // Green
    case 'WARNING':
      return '#f59e0b'; // Yellow/amber
    case 'CRITICAL':
    case 'ADRIFT':
      return '#ef4444'; // Red
    case 'OFFLINE':
      return '#6b7280'; // Grey/dim
    default:
      return '#10b981';
  }
}

/**
 * Reusable Buoy point/marker:
 * Directly reproduces Ocean Sentry's exact point/marker implementation,
 * geometry, standard material, emissive intensity, and pulse ring.
 *
 * Rendered purely as a small luminous dot on the globe without any
 * HTML labels, floating cards, or clutter.
 */
export function BuoyMarker({
  buoy,
  isSelected,
  isHandHovered = false,
  onSelect,
  onHover,
}: BuoyMarkerProps) {
  const meshRef = useRef<THREE.Mesh>(null!);
  const ringRef = useRef<THREE.Mesh>(null!);
  const groupRef = useRef<THREE.Group>(null!);
  const pulseRef = useRef<number>(0);
  const { gl } = useThree();

  // Ocean Sentry marker altitude radius (2.032)
  const markerRadius = 2.032;

  // Exact Ocean Sentry lat/lon → 3D Cartesian Vector3
  const targetPosition = useMemo(() => {
    const [x, y, z] = latLonToXYZ(buoy.latitude, buoy.longitude, markerRadius);
    return new THREE.Vector3(x, y, z);
  }, [buoy.latitude, buoy.longitude, markerRadius]);

  // Current interpolated position for smooth telemetry movement
  const currentPosition = useRef(targetPosition.clone());

  const color = useMemo(() => getBuoyColor(buoy.status), [buoy.status]);

  // Exact Ocean Sentry marker size: 0.022 default, 0.034 when selected
  const size = isSelected ? 0.034 : 0.022;

  // Pulse ring active for warning, critical, or selected states
  const showPulse = buoy.status !== 'SAFE' || isSelected;

  useFrame((state, delta) => {
    if (!groupRef.current) return;

    // Smooth position interpolation
    currentPosition.current.lerp(targetPosition, Math.min(1.0, delta * 4.0));
    groupRef.current.position.copy(currentPosition.current);

    // Orient marker tangent to Earth's curvature
    const normal = currentPosition.current.clone().normalize();
    groupRef.current.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);

    pulseRef.current += 0.05;

    // Exact Ocean Sentry pulse ring animation
    if (ringRef.current && showPulse) {
      const scale = 1 + Math.abs(Math.sin(pulseRef.current * 0.9)) * 1.5;
      ringRef.current.scale.setScalar(scale);
      const mat = ringRef.current.material as THREE.MeshBasicMaterial;
      if (mat) {
        mat.opacity = Math.max(0, 0.75 - (scale - 1) * 0.5);
      }
    }

    // Exact Ocean Sentry glowing pulsation on selection / status
    if (meshRef.current?.material) {
      const mat = meshRef.current.material as THREE.MeshStandardMaterial;
      if (isSelected) {
        mat.emissiveIntensity = 0.8 + Math.sin(state.clock.elapsedTime * 6) * 0.2;
      } else if (isHandHovered) {
        mat.emissiveIntensity = 0.7 + Math.sin(state.clock.elapsedTime * 5) * 0.2;
      } else if (buoy.status === 'CRITICAL' || buoy.status === 'ADRIFT') {
        mat.emissiveIntensity = 0.5 + Math.sin(state.clock.elapsedTime * 3) * 0.2;
      } else {
        mat.emissiveIntensity = 0.25;
      }
    }
  });

  return (
    <group ref={groupRef} name={`buoy-marker-${buoy.id}`}>
      {/* Invisible hit box for forgiving mouse/hand tap selection */}
      <mesh
        onClick={(e) => {
          e.stopPropagation();
          onSelect(buoy);
        }}
        onPointerEnter={(e) => {
          e.stopPropagation();
          gl.domElement.style.cursor = 'pointer';
          onHover?.(buoy);
        }}
        onPointerLeave={(e) => {
          e.stopPropagation();
          gl.domElement.style.cursor = 'default';
          onHover?.(null);
        }}
      >
        <sphereGeometry args={[size * 4.5, 12, 12]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* Pulse ring (Ocean Sentry additive pulse) */}
      {showPulse && (
        <mesh ref={ringRef} position={[0, 0, 0.001]}>
          <ringGeometry args={[size * 1.5, size * 2.2, 32]} />
          <meshBasicMaterial
            color={color}
            transparent
            opacity={0.8}
            side={THREE.DoubleSide}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
      )}

      {/* Core glowing marker sphere (Exact Ocean Sentry visual style) */}
      <mesh
        ref={meshRef}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(buoy);
        }}
        onPointerEnter={(e) => {
          e.stopPropagation();
          gl.domElement.style.cursor = 'pointer';
          onHover?.(buoy);
        }}
        onPointerLeave={(e) => {
          e.stopPropagation();
          gl.domElement.style.cursor = 'default';
          onHover?.(null);
        }}
      >
        <sphereGeometry args={[size, 24, 24]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={isSelected ? 1.0 : isHandHovered ? 0.85 : buoy.status === 'CRITICAL' ? 0.6 : 0.25}
          roughness={0.15}
          metalness={0.3}
        />
      </mesh>

      {/* Technical selection radar halo (Exact Ocean Sentry selection style) */}
      {isSelected && (
        <group position={[0, 0, 0.002]}>
          <mesh>
            <ringGeometry args={[size * 1.35, size * 1.55, 32]} />
            <meshBasicMaterial
              color="#22d3ee"
              transparent
              opacity={0.9}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
          <mesh>
            <ringGeometry args={[size * 2.1, size * 2.2, 32]} />
            <meshBasicMaterial
              color="#22d3ee"
              transparent
              opacity={0.45}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
          <mesh>
            <ringGeometry args={[size * 2.8, size * 2.88, 32]} />
            <meshBasicMaterial
              color="#22d3ee"
              transparent
              opacity={0.2}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
        </group>
      )}
    </group>
  );
}
