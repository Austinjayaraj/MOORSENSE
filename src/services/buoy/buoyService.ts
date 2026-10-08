import { useState, useEffect, useCallback, useMemo } from 'react';
import type { BuoyLocation } from './buoyTypes';
import { fetchBuoyLocations } from './buoyAdapter';

// Location/selection state lives in Explorer; observations live in the panel.
// A telemetry event cannot update this hook or recreate globe geometry.
export function useBuoyData() {
  const [buoys, setBuoys] = useState<BuoyLocation[]>([]);
  const [selectedBuoyId, setSelectedBuoyId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => void fetchBuoyLocations(controller.signal).then(next => {
      setBuoys(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next);
    }).catch(() => {}).finally(() => {
      if (!controller.signal.aborted) setIsLoading(false);
    });
    refresh();
    const timer = setInterval(refresh, 30000);
    return () => { controller.abort(); clearInterval(timer); };
  }, []);
  const selectBuoy = useCallback((id: string | null) => setSelectedBuoyId(id), []);
  const selectedBuoy = useMemo(() => buoys.find(b => b.id === selectedBuoyId) ?? null, [buoys, selectedBuoyId]);
  return { buoys, selectedBuoy, selectedBuoyId, selectBuoy, isLoading };
}
