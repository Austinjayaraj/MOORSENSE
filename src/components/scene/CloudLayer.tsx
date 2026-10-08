import { useRef, useMemo, useEffect, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { DepthLevel } from '../../types/ocean';
import {
  fetchCloudMetadata,
  getLatestCloudTextureUrl,
  FALLBACK_TEXTURE_URL,
  type CloudMetadata,
} from '../../services/cloudService';

interface CloudLayerProps {
  depth?: DepthLevel;
  sunPosition?: [number, number, number];
  liveEnabled?: boolean;
  onMetadataUpdate?: (meta: CloudMetadata) => void;
}

const cloudVertexShader = `
  varying vec2 vUv;
  varying vec3 vNormal;
  varying vec3 vWorldPosition;

  void main() {
    vUv = uv;
    vNormal = normalize(normalMatrix * normal);
    vec4 worldPosition = modelMatrix * vec4(position, 1.0);
    vWorldPosition = worldPosition.xyz;
    gl_Position = projectionMatrix * viewMatrix * worldPosition;
  }
`;

const cloudFragmentShader = `
  uniform sampler2D cloudTextureA;
  uniform sampler2D cloudTextureB;
  uniform float uMix;
  uniform vec3 sunDirection;
  uniform float cloudOpacity;
  uniform float uTime;

  varying vec2 vUv;
  varying vec3 vNormal;
  varying vec3 vWorldPosition;

  void main() {
    // Subtle living fluid atmospheric advection (ripples and breathes naturally without displacing geographic position)
    vec2 flow = vec2(
      sin(vUv.y * 12.56 + uTime * 0.08) * 0.0012,
      cos(vUv.x * 12.56 + uTime * 0.07) * 0.0008
    );
    
    // Smooth crossfade between consecutive NOAA satellite frames
    vec4 texA = texture2D(cloudTextureA, vUv + flow);
    vec4 texB = texture2D(cloudTextureB, vUv + flow);
    vec4 cloudTex = mix(texA, texB, clamp(uMix, 0.0, 1.0));
    float density = cloudTex.a;

    if (density < 0.012) {
      discard;
    }

    vec3 N = normalize(vNormal);
    vec3 L = normalize(sunDirection);
    vec3 V = normalize(cameraPosition - vWorldPosition);

    float dotNL = dot(N, L);
    float dotNV = max(dot(N, V), 0.0);

    // Smooth daylight falloff with warm terminator transition
    float sunFactor = smoothstep(-0.18, 0.28, dotNL);
    float terminator = smoothstep(-0.18, 0.12, dotNL) * (1.0 - smoothstep(0.12, 0.38, dotNL));

    // Volumetric Beer-Lambert self-shadowing in dense storm cores
    float internalExtinction = exp(-density * 0.65);
    vec3 cloudLit = mix(vec3(0.92, 0.94, 0.98), vec3(1.0, 1.0, 1.0), internalExtinction);

    // Warm golden peach tint at the twilight terminator
    vec3 sunsetTint = vec3(1.0, 0.72, 0.45);
    cloudLit = mix(cloudLit, sunsetTint, terminator * 0.35);

    // Shadowed underbelly (natural ambient sky scatter)
    vec3 cloudDark = vec3(0.012, 0.025, 0.065);
    vec3 color = mix(cloudDark, cloudLit, sunFactor);

    // Forward Mie scattering (silver lining glint when viewing toward the sun)
    float forwardScatter = pow(max(dot(V, -L), 0.0), 4.5);
    color += vec3(0.18, 0.17, 0.14) * forwardScatter * sunFactor;

    // Atmospheric limb Rayleigh blue blend at the silhouette
    float fresnel = pow(1.0 - dotNV, 3.8);
    color = mix(color, vec3(0.18, 0.48, 0.92), fresnel * 0.35 * sunFactor);

    // Silky alpha curve
    float alpha = density * cloudOpacity;
    float limbEnhance = 1.0 + fresnel * 0.45;
    alpha = clamp(alpha * limbEnhance, 0.0, 1.0);

    gl_FragColor = vec4(color, alpha);
  }
`;

function configureTexture(tex: THREE.Texture): THREE.Texture {
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.generateMipmaps = true;
  tex.anisotropy = 16;
  return tex;
}

export function CloudLayer({
  depth = 0,
  sunPosition = [12, 5, 8],
  liveEnabled = true,
  onMetadataUpdate,
}: CloudLayerProps) {
  const meshRef = useRef<THREE.Mesh>(null!);
  const textureLoader = useMemo(() => new THREE.TextureLoader(), []);

  // Current frame state
  const currentTimestampRef = useRef<string>('');
  const mixProgressRef = useRef<number>(0);
  const isTransitioningRef = useRef<boolean>(false);

  // Initial base texture
  const initialTexture = useMemo(() => {
    const tex = textureLoader.load(FALLBACK_TEXTURE_URL);
    return configureTexture(tex);
  }, [textureLoader]);

  const sunDir = useMemo(() => {
    return new THREE.Vector3(...sunPosition).normalize();
  }, [sunPosition]);

  const uniforms = useMemo(
    () => ({
      cloudTextureA: { value: initialTexture },
      cloudTextureB: { value: initialTexture },
      uMix: { value: 0.0 },
      sunDirection: { value: sunDir },
      cloudOpacity: { value: 0.92 },
      uTime: { value: 0.0 },
    }),
    [initialTexture, sunDir]
  );

  // Poll for NOAA real-time cloud updates
  useEffect(() => {
    if (!liveEnabled) return;

    let isMounted = true;

    async function checkUpdates() {
      try {
        const meta = await fetchCloudMetadata();
        if (!isMounted) return;

        if (onMetadataUpdate) {
          onMetadataUpdate(meta);
        }

        const newTimestamp = meta.timestamp || meta.frame_id;
        if (newTimestamp && newTimestamp !== currentTimestampRef.current) {
          // If this is initial load or a newly published NOAA frame
          const isInitial = currentTimestampRef.current === '';
          currentTimestampRef.current = newTimestamp;

          const targetUrl = getLatestCloudTextureUrl(newTimestamp);

          textureLoader.load(
            targetUrl,
            (newTex) => {
              if (!isMounted) return;
              configureTexture(newTex);

              if (isInitial) {
                // Instantly apply initial live frame
                uniforms.cloudTextureA.value = newTex;
                uniforms.cloudTextureB.value = newTex;
                uniforms.uMix.value = 0.0;
              } else {
                // Crossfade smoothly to the new 10-minute satellite frame
                uniforms.cloudTextureB.value = newTex;
                mixProgressRef.current = 0.0;
                isTransitioningRef.current = true;
              }
            },
            undefined,
            () => {
              // On error, fallback remains intact
            }
          );
        }
      } catch (err) {
        console.warn('NOAA Cloud polling check:', err);
      }
    }

    checkUpdates();
    // Re-check NOAA SOS every 60 seconds
    const interval = setInterval(checkUpdates, 60000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [liveEnabled, onMetadataUpdate, textureLoader, uniforms]);

  useFrame((state, delta) => {
    if (!meshRef.current) return;

    // Real-time satellite clouds are geographically anchored to Earth's coordinates:
    meshRef.current.rotation.set(0, 0, 0);

    uniforms.uTime.value = state.clock.elapsedTime;

    // Smooth frame crossfade transition
    if (isTransitioningRef.current) {
      // 2.5 second smooth crossfade
      mixProgressRef.current += delta / 2.5;
      if (mixProgressRef.current >= 1.0) {
        mixProgressRef.current = 1.0;
        uniforms.uMix.value = 1.0;
        // Swap textures and reset mix
        uniforms.cloudTextureA.value = uniforms.cloudTextureB.value;
        uniforms.uMix.value = 0.0;
        isTransitioningRef.current = false;
      } else {
        uniforms.uMix.value = THREE.MathUtils.smoothstep(mixProgressRef.current, 0.0, 1.0);
      }
    }

    // Maintain strong cloud visibility while adjusting for depth layer navigation
    const targetOpacity = depth > 0 ? Math.max(0.20, 0.92 - (depth / 1000) * 0.65) : 0.92;
    uniforms.cloudOpacity.value = THREE.MathUtils.lerp(uniforms.cloudOpacity.value, targetOpacity, 0.1);
  });

  return (
    <mesh ref={meshRef} name="NOAARealTimeCloudSphere">
      <sphereGeometry args={[2.012, 96, 96]} />
      <shaderMaterial
        vertexShader={cloudVertexShader}
        fragmentShader={cloudFragmentShader}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.NormalBlending}
      />
    </mesh>
  );
}
