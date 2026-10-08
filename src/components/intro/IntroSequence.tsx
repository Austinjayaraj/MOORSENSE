import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

interface IntroSequenceProps {
  onComplete: () => void;
}

// Subtle star background canvas (from Ocean Sentry)
function useStarCanvas(canvasRef: React.RefObject<HTMLCanvasElement | null>) {
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d')!;
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const stars = Array.from({ length: 220 }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 1.1 + 0.2,
      a: Math.random() * 0.5 + 0.2,
      speed: Math.random() * 0.15 + 0.05,
      phase: Math.random() * Math.PI * 2,
    }));

    let frame = 0;
    let raf: number;
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      stars.forEach((s) => {
        const alpha = s.a * (0.65 + 0.35 * Math.sin(frame * 0.015 * s.speed + s.phase));
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(180,215,255,${alpha})`;
        ctx.fill();
      });
      frame++;
      raf = requestAnimationFrame(draw);
    };
    draw();

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    window.addEventListener('resize', resize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
    };
  }, [canvasRef]);
}

export function IntroSequence({ onComplete }: IntroSequenceProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // phase: 0=black, 1=title & tagline, 2=loading progress, 3=ready
  const [phase, setPhase] = useState(0);
  const [progress, setProgress] = useState(15);
  const [loadingStep, setLoadingStep] = useState('INITIALIZING MOORING INTEGRITY SYSTEM...');
  const [exiting, setExiting] = useState(false);

  useStarCanvas(canvasRef);

  // Preload textures in the background while intro is playing
  useEffect(() => {
    const loader = new THREE.TextureLoader();
    const textures = [
      '/textures/earth_day.jpg',
      '/textures/earth_night.png',
      '/textures/earth_specular.jpg',
      '/textures/earth_normal.jpg',
      '/textures/earth_clouds.png?v=5',
    ];
    textures.forEach((url) => {
      loader.load(url);
    });
  }, []);

  // Progressive MoorSense intro timeline
  useEffect(() => {
    const t0 = setTimeout(() => {
      setPhase(1);
      setLoadingStep('INITIALIZING MOORING INTEGRITY SYSTEM...');
      setProgress(20);
    }, 350);

    const t1 = setTimeout(() => {
      setProgress(48);
      setLoadingStep('OCEAN DATA STREAM ……… READY');
    }, 1100);

    const t2 = setTimeout(() => {
      setProgress(74);
      setLoadingStep('DIGITAL TWIN ………….. READY');
    }, 1900);

    const t3 = setTimeout(() => {
      setProgress(90);
      setLoadingStep('EARTH SYSTEM ………….. READY');
    }, 2700);

    const t4 = setTimeout(() => {
      setProgress(100);
      setLoadingStep('SYSTEM ONLINE');
      setPhase(2);
    }, 3400);

    return () => {
      clearTimeout(t0);
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      clearTimeout(t4);
    };
  }, []);

  const handleEnter = () => {
    setExiting(true);
    setTimeout(onComplete, 850);
  };

  // Auto-advance after 4.6s
  useEffect(() => {
    const t = setTimeout(handleEnter, 4600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center overflow-hidden"
      style={{
        background: 'radial-gradient(ellipse at center, #020617 0%, #000208 100%)',
        transition: 'opacity 0.9s cubic-bezier(0.4, 0, 0.2, 1)',
        opacity: exiting ? 0 : 1,
        pointerEvents: exiting ? 'none' : 'auto',
      }}
    >
      {/* Star Canvas */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0 pointer-events-none"
        style={{ opacity: 0.8 }}
      />

      {/* Main MoorSense Scientific Intro Container */}
      <div className="relative z-10 flex flex-col items-center gap-6 text-center px-6 max-w-xl">
        {/* MoorSense Mooring Vector Monogram */}
        <div
          style={{
            opacity: phase >= 1 ? 1 : 0,
            transform: phase >= 1 ? 'scale(1) translateY(0)' : 'scale(0.8) translateY(12px)',
            transition: 'opacity 1s ease, transform 1s ease',
          }}
        >
          <svg width="48" height="26" viewBox="0 0 48 26" fill="none">
            {/* Mooring chain & ocean wave telemetry vectors */}
            <path
              d="M2 18 C8 10, 14 6, 20 12 C26 18, 32 22, 38 16 C42 12, 44 10, 46 8"
              stroke="url(#moorG)"
              strokeWidth="2.4"
              strokeLinecap="round"
              fill="none"
            />
            <path
              d="M2 24 C8 16, 16 12, 22 18 C28 24, 34 26, 40 20 C43 17, 45 15, 46 14"
              stroke="url(#moorG2)"
              strokeWidth="1.4"
              strokeLinecap="round"
              fill="none"
              opacity="0.65"
            />
            {/* Mooring buoy node beacon */}
            <circle cx="20" cy="12" r="2.5" fill="#22d3ee" />
            <circle cx="20" cy="12" r="5" stroke="#22d3ee" strokeWidth="0.8" opacity="0.5" />
            <defs>
              <linearGradient id="moorG" x1="2" y1="14" x2="46" y2="14" gradientUnits="userSpaceOnUse">
                <stop stopColor="#22d3ee" />
                <stop offset="1" stopColor="#3b82f6" />
              </linearGradient>
              <linearGradient id="moorG2" x1="2" y1="20" x2="46" y2="20" gradientUnits="userSpaceOnUse">
                <stop stopColor="#0ea5e9" />
                <stop offset="1" stopColor="#6366f1" />
              </linearGradient>
            </defs>
          </svg>
        </div>

        {/* Title: MOORSENSE */}
        <div
          style={{
            opacity: phase >= 1 ? 1 : 0,
            transform: phase >= 1 ? 'translateY(0)' : 'translateY(16px)',
            transition: 'opacity 1.1s ease 0.1s, transform 1.1s ease 0.1s',
          }}
        >
          <h1
            style={{
              fontSize: 'clamp(2rem, 5.5vw, 3.4rem)',
              fontWeight: 300,
              letterSpacing: '0.28em',
              color: '#ffffff',
              fontFamily: "'Space Grotesk', system-ui, -apple-system, sans-serif",
              textShadow: '0 0 32px rgba(34,211,238,0.25)',
            }}
          >
            MOORSENSE
          </h1>
          <div
            style={{
              height: '1px',
              background: 'linear-gradient(90deg, transparent, rgba(34,211,238,0.6), transparent)',
              marginTop: '10px',
            }}
          />
        </div>

        {/* Tagline / Subtitle: MOORING INTEGRITY DIGITAL TWIN SYSTEM */}
        <div
          style={{
            opacity: phase >= 1 ? 1 : 0,
            transform: phase >= 1 ? 'translateY(0)' : 'translateY(10px)',
            transition: 'opacity 1s ease 0.25s, transform 1s ease 0.25s',
          }}
        >
          <p
            style={{
              fontSize: 'clamp(0.75rem, 1.6vw, 0.95rem)',
              letterSpacing: '0.22em',
              color: 'rgba(34,211,238,0.9)',
              fontWeight: 400,
              lineHeight: 1.8,
              fontFamily: "'Chakra Petch', 'Space Grotesk', sans-serif",
            }}
          >
            MOORING INTEGRITY
            <br />
            DIGITAL TWIN SYSTEM
          </p>
        </div>

        {/* Scientific Loading / Progress Indicator */}
        <div
          style={{
            width: '290px',
            marginTop: '8px',
            opacity: phase >= 1 ? 1 : 0,
            transition: 'opacity 0.8s ease 0.3s',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: '8.5px',
              letterSpacing: '0.12em',
              color: '#94a3b8',
              fontFamily: 'monospace',
            }}
          >
            <span style={{ color: phase >= 2 ? '#38bdf8' : '#94a3b8' }}>{loadingStep}</span>
            <span style={{ fontFamily: 'monospace', color: '#22d3ee', fontWeight: 600 }}>{progress}%</span>
          </div>

          <div
            style={{
              width: '100%',
              height: '2px',
              background: 'rgba(255,255,255,0.06)',
              borderRadius: '1px',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${progress}%`,
                height: '100%',
                background: 'linear-gradient(90deg, #0284c7, #22d3ee)',
                boxShadow: '0 0 10px rgba(34,211,238,0.7)',
                transition: 'width 0.6s ease',
              }}
            />
          </div>
        </div>

        {/* Enter / Explore Button */}
        <div
          style={{
            opacity: phase >= 2 ? 1 : 0,
            transform: phase >= 2 ? 'translateY(0)' : 'translateY(10px)',
            transition: 'opacity 0.6s ease, transform 0.6s ease',
            marginTop: '10px',
          }}
        >
          <button
            onClick={handleEnter}
            style={{
              border: '1px solid rgba(34,211,238,0.5)',
              background: 'rgba(34,211,238,0.08)',
              color: 'rgba(34,211,238,0.95)',
              padding: '10px 30px',
              fontSize: '0.74rem',
              letterSpacing: '0.24em',
              cursor: 'pointer',
              borderRadius: '3px',
              transition: 'all 0.25s ease',
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              fontWeight: 500,
              boxShadow: '0 0 18px rgba(34,211,238,0.2)',
            }}
            onMouseEnter={(e) => {
              (e.target as HTMLElement).style.background = 'rgba(34,211,238,0.18)';
              (e.target as HTMLElement).style.borderColor = 'rgba(34,211,238,0.9)';
              (e.target as HTMLElement).style.boxShadow = '0 0 28px rgba(34,211,238,0.4)';
            }}
            onMouseLeave={(e) => {
              (e.target as HTMLElement).style.background = 'rgba(34,211,238,0.08)';
              (e.target as HTMLElement).style.borderColor = 'rgba(34,211,238,0.5)';
              (e.target as HTMLElement).style.boxShadow = '0 0 18px rgba(34,211,238,0.2)';
            }}
          >
            ENTER DIGITAL TWIN GLOBE →
          </button>
        </div>

        <div
          style={{
            fontSize: '0.62rem',
            letterSpacing: '0.2em',
            color: 'rgba(148,163,184,0.45)',
            marginTop: '4px',
            fontFamily: 'monospace',
          }}
        >
          MOORSENSE · MOORING INTEGRITY DIGITAL TWIN SYSTEM
        </div>
      </div>
    </div>
  );
}
