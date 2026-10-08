import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { DepthLevel } from '../../types/ocean';

interface RealisticEarthProps {
  depth?: DepthLevel;
  sunPosition?: [number, number, number];
}

// Vertex shader for Realistic Earth with day/night blending and normal mapping
const earthVertexShader = `
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

// Fragment shader for Realistic Earth
const earthFragmentShader = `
  uniform sampler2D dayTexture;
  uniform sampler2D nightTexture;
  uniform sampler2D specularTexture;
  uniform sampler2D normalTexture;
  uniform sampler2D cloudTexture;
  uniform vec3 sunDirection;
  uniform float depthOpacity;
  uniform float depthLevel;
  uniform float uTime;

  varying vec2 vUv;
  varying vec3 vNormal;
  varying vec3 vWorldPosition;


  void main() {
    // Normal map perturbation for terrain & ocean ripples
    vec3 normalMap = texture2D(normalTexture, vUv).xyz * 2.0 - 1.0;
    vec3 N = normalize(vNormal + normalMap * 0.25);
    vec3 L = normalize(sunDirection);
    vec3 V = normalize(cameraPosition - vWorldPosition);
    vec3 H = normalize(L + V);

    // Sun dot normal (day / night terminator)
    float dotNL = dot(N, L);

    // Smooth day/night transition factor
    float dayFactor = smoothstep(-0.15, 0.25, dotNL);

    // Sample textures
    vec4 dayTex = texture2D(dayTexture, vUv);
    vec4 nightColor = texture2D(nightTexture, vUv);
    float isOcean = texture2D(specularTexture, vUv).r;

    // ── 1. PHOTOREALISTIC CONTINENTS & LUSH VEGETATION ──
    // Detect vegetation vs arid land
    float greenDominance = dayTex.g - max(dayTex.r * 0.70, dayTex.b * 0.70);
    float vegScore = smoothstep(0.01, 0.16, greenDominance * 2.5 + dayTex.g * 0.40);
    
    // Rich greens matching Amazon & temperate forests in Reference Image 2
    vec3 deepForest   = vec3(0.07, 0.35, 0.05);  // Vibrant emerald Amazon / Congo
    vec3 brightCanopy = vec3(0.20, 0.52, 0.10);  // Rich canopy and grasslands
    vec3 greenBiome   = mix(deepForest, brightCanopy, clamp(dayTex.g * 1.6, 0.0, 1.0));

    // Warm desert ochre, golden sands & mountain tan (Sahara, Mojave, Gobi)
    vec3 desertOchre  = vec3(0.78, 0.62, 0.26);  // Golden Sahara, Atacama, Mojave
    vec3 mountainTan  = vec3(0.50, 0.40, 0.22);  // Andes, Rockies
    vec3 aridBiome    = mix(mountainTan, desertOchre, clamp(dayTex.r * 1.3, 0.0, 1.0));

    // Base photographic satellite albedo enhanced with lush vegetation & warm desert tones
    vec3 enrichedLand = mix(dayTex.rgb * 1.15, greenBiome, vegScore * 0.70);
    enrichedLand = mix(enrichedLand, aridBiome, (1.0 - vegScore) * 0.35 * clamp(dayTex.r - dayTex.b, 0.0, 1.0));

    // ── 2. DEEP DARK OCEAN BLUE WATER (NASA Blue Marble) ──
    // Real ocean water strongly absorbs red and green, producing deep, rich, dark navy blue
    float bathymetry = clamp(dayTex.b * 1.3, 0.0, 1.0);
    
    // Deep dark ocean navy palette
    vec3 abyssalNavy  = vec3(0.005, 0.022, 0.120); // Deep abyssal trenches & midnight ocean (#01061f)
    vec3 deepOcean    = vec3(0.010, 0.055, 0.230); // Deep open ocean blue (#030e3b)
    vec3 royalBlue    = vec3(0.018, 0.095, 0.380); // Sunlit surface oceanic royal blue (#051861)

    // Smooth bathymetric blend from deep abyss to sunlit surface
    vec3 oceanWater = mix(abyssalNavy, deepOcean, smoothstep(0.05, 0.35, bathymetry));
    oceanWater = mix(oceanWater, royalBlue, smoothstep(0.35, 0.75, bathymetry) * max(dotNL, 0.0));

    // Vibrant coastal aqua fringe along shallow continental shelves (Caribbean, Bahamas, reefs)
    float coastalEdge = smoothstep(0.02, 0.25, isOcean) * (1.0 - smoothstep(0.25, 0.85, isOcean));
    vec3 coastalTurquoise = vec3(0.03, 0.45, 0.60);
    vec3 enrichedOcean = mix(oceanWater, coastalTurquoise, coastalEdge * 0.68);

    // Blend Land vs Ocean strictly using specular mask
    vec3 surfaceAlbedo = mix(enrichedLand, enrichedOcean, smoothstep(0.12, 0.65, isOcean));

    // ── 3. DIFFUSE LIGHTING & CLOUD SHADOW ATTENUATION ──
    vec3 dayDiffuse = surfaceAlbedo * max(dotNL * 0.95 + 0.05, 0.0);

    // Cast soft, moving volumetric cloud shadow on land and oceans (synchronized with cloud drift)
    vec2 shadowOffset = -L.xy * 0.0035 + vec2(uTime * 0.0038, 0.0);
    float cloudCover = texture2D(cloudTexture, vUv + shadowOffset).a;
    float cloudShadow = smoothstep(0.08, 0.65, cloudCover) * 0.45 * dayFactor;
    dayDiffuse *= (1.0 - cloudShadow);


    // Specular ocean glint (crisp, focused sun reflection strictly on ocean water)
    float specFactor = pow(max(dot(N, H), 0.0), 64.0) * smoothstep(0.4, 0.95, isOcean);
    vec3 specularGlint = vec3(1.0, 0.98, 0.90) * specFactor * 1.35 * dayFactor * (1.0 - cloudShadow * 0.85);

    // ── 4. SUBTLE SILHOUETTE LIMB GLOW (Deep Rayleigh Blue) ──
    float fresnel = pow(1.0 - max(dot(N, V), 0.0), 5.0);
    vec3 surfaceLimb = vec3(0.05, 0.25, 0.80) * fresnel * max(dotNL + 0.1, 0.0) * 0.35;

    // ── 5. NIGHT LIGHTS & FINAL COMPOSITING ──
    vec3 cityLights = nightColor.rgb * vec3(1.6, 1.2, 0.8) * (1.0 - dayFactor) * 1.5;
    vec3 ambient = surfaceAlbedo * 0.015;

    vec3 finalColor = mix(cityLights, dayDiffuse + specularGlint, dayFactor) + surfaceLimb + ambient;


    // Subsurface depth modulation
    if (depthLevel > 0.0) {
      float depthDim = clamp(depthLevel / 1000.0, 0.0, 0.65);
      finalColor = mix(finalColor, vec3(0.01, 0.05, 0.14), depthDim * 0.5);
    }

    gl_FragColor = vec4(finalColor, depthOpacity);
  }
`;


export function RealisticEarth({ depth = 0, sunPosition = [12, 5, 8] }: RealisticEarthProps) {
  const earthMeshRef = useRef<THREE.Mesh>(null!);
  const textureLoader = useMemo(() => new THREE.TextureLoader(), []);

  // Load NASA / Three.js equirectangular textures with optimal filtering
  const { dayTex, nightTex, specTex, normalTex, cloudTex } = useMemo(() => {
    const day = textureLoader.load('/textures/earth_day.jpg');
    const night = textureLoader.load('/textures/earth_night.png');
    const spec = textureLoader.load('/textures/earth_specular.jpg');
    const norm = textureLoader.load('/textures/earth_normal.jpg');
    const cloud = textureLoader.load('/textures/earth_clouds_noaa_latest.png');



    [day, night, spec, norm, cloud].forEach((t) => {
      t.wrapS = THREE.RepeatWrapping;
      t.wrapT = THREE.ClampToEdgeWrapping;
      t.minFilter = THREE.LinearMipmapLinearFilter;
      t.magFilter = THREE.LinearFilter;
      t.generateMipmaps = true;
    });

    return { dayTex: day, nightTex: night, specTex: spec, normalTex: norm, cloudTex: cloud };
  }, [textureLoader]);

  // Sun direction vector
  const sunDir = useMemo(() => {
    return new THREE.Vector3(...sunPosition).normalize();
  }, [sunPosition]);

  // Shader uniforms
  const uniforms = useMemo(() => ({
    dayTexture: { value: dayTex },
    nightTexture: { value: nightTex },
    specularTexture: { value: specTex },
    normalTexture: { value: normalTex },
    cloudTexture: { value: cloudTex },
    sunDirection: { value: sunDir },
    depthOpacity: { value: 1.0 },
    depthLevel: { value: depth as number },
    uTime: { value: 0.0 },
  }), [dayTex, nightTex, specTex, normalTex, cloudTex, sunDir, depth]);

  useFrame((state) => {
    if (!earthMeshRef.current) return;
    uniforms.uTime.value = state.clock.elapsedTime;
    // Update uniforms
    uniforms.depthLevel.value = THREE.MathUtils.lerp(uniforms.depthLevel.value, depth, 0.08);
    uniforms.depthOpacity.value = THREE.MathUtils.lerp(
      uniforms.depthOpacity.value,
      depth > 100 ? 0.75 : 1.0,
      0.08
    );
  });


  return (
    <group>
      {/* High detail Earth sphere with 96x96 segments */}
      <mesh ref={earthMeshRef} receiveShadow castShadow>
        <sphereGeometry args={[2, 96, 96]} />
        <shaderMaterial
          vertexShader={earthVertexShader}
          fragmentShader={earthFragmentShader}
          uniforms={uniforms}
          transparent={depth > 0}
          depthWrite={true}
        />
      </mesh>

      {/* Subsurface depth shell indicator when depth > 0 */}
      {depth > 0 && (
        <mesh>
          <sphereGeometry args={[2 - (depth / 1000) * 0.04, 48, 48]} />
          <meshBasicMaterial
            color="#06b6d4"
            transparent
            opacity={Math.min(0.25, 0.08 + (depth / 1000) * 0.2)}
            wireframe
            depthWrite={false}
          />
        </mesh>
      )}
    </group>
  );
}
