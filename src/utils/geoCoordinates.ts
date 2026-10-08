/**
 * Geographic coordinate conversion for MoorSense 3D Earth.
 *
 * Implements the exact coordinate transformation used by the Ocean Sentry Earth,
 * guaranteeing correct alignment across latitude, longitude, camera orientation,
 * and surface normal vectors.
 */

import * as THREE from 'three';

export const EARTH_RADIUS = 2.0;
export const DEFAULT_BUOY_MARKER_RADIUS = 2.025;

/**
 * Converts geographic latitude and longitude to 3D Cartesian coordinates (Vector3).
 *
 * Strictly matches the Ocean Sentry coordinate convention:
 *   phi   = (90 - lat) * (PI / 180)
 *   theta = (lon + 180) * (PI / 180)
 *   x     = -radius * sin(phi) * cos(theta)
 *   y     =  radius * cos(phi)
 *   z     =  radius * sin(phi) * sin(theta)
 *
 * @param latitude Latitude in decimal degrees [-90, +90]
 * @param longitude Longitude in decimal degrees [-180, +180]
 * @param radius Distance from sphere center (Earth radius is 2.0)
 * @returns THREE.Vector3 representing 3D world position
 */
export function latLngToVector3(
  latitude: number,
  longitude: number,
  radius: number = DEFAULT_BUOY_MARKER_RADIUS
): THREE.Vector3 {
  const phi = (90 - latitude) * (Math.PI / 180);
  const theta = (longitude + 180) * (Math.PI / 180);

  const x = -radius * Math.sin(phi) * Math.cos(theta);
  const y = radius * Math.cos(phi);
  const z = radius * Math.sin(phi) * Math.sin(theta);

  return new THREE.Vector3(x, y, z);
}

/**
 * Computes the outward surface unit normal at any point on the Earth sphere.
 */
export function getSurfaceNormal(pos: THREE.Vector3): THREE.Vector3 {
  return pos.clone().normalize();
}

/**
 * Computes rotation quaternion to align an object's local +Z axis with the surface normal,
 * orienting rings and flat markers tangent to the Earth's curvature.
 */
export function getSurfaceQuaternion(normal: THREE.Vector3): THREE.Quaternion {
  const quat = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 0, 1);
  quat.setFromUnitVectors(up, normal);
  return quat;
}
