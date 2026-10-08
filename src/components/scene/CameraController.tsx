import { useRef, useEffect, useCallback } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import type { CameraStage } from '../../types/ocean';
import { easeInOutCubic, latLonToXYZ } from '../../utils/oceanCalc';
import { CinematicCameraControllerLogic } from '../../camera/CinematicCameraController';
import type { CinematicTransitionConfig } from '../../camera/cameraTransitions';

// Camera position presets focused on India, Bay of Bengal, and Indian Ocean
const CAMERA_PRESETS: Record<CameraStage, { pos: THREE.Vector3; target: THREE.Vector3 }> = {
  intro:       { pos: new THREE.Vector3(1.5, 2.5, -22.0), target: new THREE.Vector3(0, 0, 0) },
  space:       { pos: new THREE.Vector3(1.2, 2.0, -15.0), target: new THREE.Vector3(0, 0, 0) },
  earth:       { pos: new THREE.Vector3(0.9, 1.5, -8.5),  target: new THREE.Vector3(0, 0, 0) },
  indianOcean: { pos: new THREE.Vector3(0.6, 0.4, -6.0),  target: new THREE.Vector3(0, 0, 0) },
  bayOfBengal: { pos: new THREE.Vector3(0.35, 1.05, -4.5), target: new THREE.Vector3(0, 0, 0) },
  exploration: { pos: new THREE.Vector3(0.35, 1.05, -4.5), target: new THREE.Vector3(0, 0, 0) },
};


interface CameraControllerProps {
  stage: CameraStage;
  onStageComplete?: (stage: CameraStage) => void;
  targetStation?: { latitude: number; longitude: number } | null;
  isExploring: boolean;
  handDelta?: React.MutableRefObject<{ dx: number; dy: number }>;
  handZoom?: React.MutableRefObject<number>;
  isFist?: React.MutableRefObject<boolean>;
  cinematicController?: CinematicCameraControllerLogic | null;
  currentTargetRef?: React.MutableRefObject<THREE.Vector3>;
  orbitControlsRef?: React.RefObject<any>; // using any to avoid importing OrbitControlsImpl type if not needed
}

export function CameraController({
  stage,
  onStageComplete,
  targetStation,
  isExploring,
  handDelta,
  handZoom,
  isFist,
  cinematicController,
  currentTargetRef: externalTargetRef,
  orbitControlsRef,
}: CameraControllerProps) {
  const { camera } = useThree();
  const progress = useRef(0);
  const lastStage = useRef<CameraStage>(stage);
  const fromPos = useRef(new THREE.Vector3());
  const fromTarget = useRef(new THREE.Vector3());
  const currentTarget = useRef(new THREE.Vector3(0, 0, 0));
  const orbitTarget = useRef(new THREE.Vector3(0, 0, 0));


  // Sync external target ref if provided
  useEffect(() => {
    if (externalTargetRef) {
      externalTargetRef.current = currentTarget.current;
    }
  }, [externalTargetRef]);

  // Capture transition start on stage change
  useEffect(() => {
    if (stage !== lastStage.current) {
      fromPos.current.copy(camera.position);
      fromTarget.current.copy(orbitTarget.current);
      progress.current = 0;
      lastStage.current = stage;
    }
  }, [stage, camera]);

  // Capture transition on station target (both selection and return to global)
  const lastTargetStation = useRef(targetStation);
  useEffect(() => {
    if (isExploring && targetStation !== lastTargetStation.current) {
      fromPos.current.copy(camera.position);
      fromTarget.current.copy(orbitTarget.current);
      progress.current = 0;
      lastTargetStation.current = targetStation;
    }
  }, [targetStation, isExploring, camera]);

  const getDesiredPos = useCallback((): THREE.Vector3 => {
    if (targetStation && isExploring) {
      const [x, y, z] = latLonToXYZ(
        targetStation.latitude,
        targetStation.longitude,
        4.4
      );
      return new THREE.Vector3(x, y, z);
    }
    return CAMERA_PRESETS[stage].pos;
  }, [stage, targetStation, isExploring]);

  const getDesiredTarget = useCallback((): THREE.Vector3 => {
    if (targetStation && isExploring) {
      const [x, y, z] = latLonToXYZ(
        targetStation.latitude,
        targetStation.longitude,
        1.2
      );
      return new THREE.Vector3(x, y, z);
    }
    return CAMERA_PRESETS[stage].target;
  }, [stage, targetStation, isExploring]);

  useFrame((_, delta) => {
    // If cinematic transition is active, let it drive the camera
    if (cinematicController?.isActive) {
      cinematicController.update(camera, currentTarget.current, performance.now());
      camera.lookAt(currentTarget.current);
      orbitTarget.current.copy(currentTarget.current);
      if (externalTargetRef) {
        externalTargetRef.current.copy(currentTarget.current);
      }
      return;
    }

    let didUpdateCamera = false;

    // 1. Stage transition lerp
    if (progress.current < 1) {
      progress.current = Math.min(1, progress.current + delta * 0.45);
      const t = easeInOutCubic(progress.current);
      camera.position.lerpVectors(fromPos.current, getDesiredPos(), t);
      currentTarget.current.lerpVectors(fromTarget.current, getDesiredTarget(), t);

      if (progress.current >= 1 && onStageComplete) {
        onStageComplete(stage);
      }
      didUpdateCamera = true;
    } else if (stage === 'exploration') {
      // 2. Hand Gesture control in exploration mode
      const hDelta = handDelta?.current;
      const hZoom = handZoom?.current ?? 1.0;

      if (hDelta && (hDelta.dx !== 0 || hDelta.dy !== 0 || Math.abs(hZoom - 1.0) > 0.001)) {
        // Spherical rotation around current target
        const offset = new THREE.Vector3().subVectors(camera.position, currentTarget.current);
        const spherical = new THREE.Spherical().setFromVector3(offset);

        // Apply hand rotation with smoothing
        spherical.theta -= hDelta.dx * 0.04;
        spherical.phi = THREE.MathUtils.clamp(
          spherical.phi - hDelta.dy * 0.04,
          0.1,
          Math.PI - 0.1
        );

        // Apply hand pinch zoom
        if (Math.abs(hZoom - 1.0) > 0.001) {
          spherical.radius = THREE.MathUtils.clamp(
            spherical.radius * hZoom,
            2.8,
            12.0
          );
        }

        offset.setFromSpherical(spherical);
        camera.position.copy(currentTarget.current).add(offset);
        didUpdateCamera = true;
      }
    }

    if (didUpdateCamera) {
      camera.lookAt(currentTarget.current);
      if (orbitControlsRef?.current) {
        orbitControlsRef.current.target.copy(currentTarget.current);
        orbitControlsRef.current.update();
      }
    } else {
      // If we are not forcing the camera, let OrbitControls drive!
      // We just sync our internal target to what OrbitControls is looking at
      if (orbitControlsRef?.current && stage === 'exploration') {
        currentTarget.current.copy(orbitControlsRef.current.target);
      }
    }

    orbitTarget.current.copy(currentTarget.current);
    if (externalTargetRef) {
      externalTargetRef.current.copy(currentTarget.current);
    }
  });

  return null;
}
