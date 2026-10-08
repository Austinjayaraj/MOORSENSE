/**
 * MoorSense Buoy Service & Hook
 *
 * Provides reactive access to buoy telemetry and locations,
 * abstracting transport protocol away from rendering layer.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import type { BuoyLocation, IBuoyDataAdapter } from './buoyTypes';
import { IncoisOmniBuoyAdapter } from './buoyAdapter';

class BuoyServiceManager {
  private static instance: BuoyServiceManager | null = null;
  private adapter: IBuoyDataAdapter;

  private constructor() {
    this.adapter = new IncoisOmniBuoyAdapter(true);
  }

  public static getInstance(): BuoyServiceManager {
    if (!BuoyServiceManager.instance) {
      BuoyServiceManager.instance = new BuoyServiceManager();
    }
    return BuoyServiceManager.instance;
  }

  public getAdapter(): IBuoyDataAdapter {
    return this.adapter;
  }

  public setAdapter(newAdapter: IBuoyDataAdapter): void {
    this.adapter.dispose();
    this.adapter = newAdapter;
  }
}

export const buoyService = BuoyServiceManager.getInstance();

export interface UseBuoyDataReturn {
  buoys: BuoyLocation[];
  selectedBuoy: BuoyLocation | null;
  selectedBuoyId: string | null;
  selectBuoy: (id: string | null) => void;
  isLoading: boolean;
  sourceName: string;
}

export function useBuoyData(): UseBuoyDataReturn {
  const [buoys, setBuoys] = useState<BuoyLocation[]>([]);
  const [selectedBuoyId, setSelectedBuoyId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const adapter = useMemo(() => buoyService.getAdapter(), []);

  useEffect(() => {
    setIsLoading(true);
    const unsubscribe = adapter.subscribe((updatedBuoys) => {
      setBuoys(updatedBuoys);
      setIsLoading(false);
    });

    return () => {
      unsubscribe();
    };
  }, [adapter]);

  const selectBuoy = useCallback((id: string | null) => {
    setSelectedBuoyId(id);
  }, []);

  const selectedBuoy = useMemo(() => {
    if (!selectedBuoyId) return null;
    return buoys.find((b) => b.id === selectedBuoyId) ?? null;
  }, [buoys, selectedBuoyId]);

  return {
    buoys,
    selectedBuoy,
    selectedBuoyId,
    selectBuoy,
    isLoading,
    sourceName: adapter.sourceName,
  };
}
