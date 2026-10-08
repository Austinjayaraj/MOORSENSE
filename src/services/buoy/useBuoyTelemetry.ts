import { useCallback, useEffect, useRef, useState } from 'react';
import type { BuoyDetail, BuoyLocation, HistoryObservation, Telemetry } from './buoyTypes';

export function useBuoyTelemetry(selected: BuoyLocation | null) {
  const [detail, setDetail] = useState<BuoyDetail | null>(null);
  const [history, setHistory] = useState<HistoryObservation[]>([]);
  const [historyStatus, setHistoryStatus] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [websocketStatus, setWebsocketStatus] = useState('CONNECTING');
  const socketRef = useRef<WebSocket | null>(null);
  const selectionRef = useRef(selected?.id ?? null);
  useEffect(() => { selectionRef.current = selected?.id ?? null; }, [selected?.id]);
  const historyAbort = useRef<AbortController | null>(null);
  const loadHistory = useCallback((id: string) => {
    historyAbort.current?.abort();
    const controller = new AbortController();
    historyAbort.current = controller;
    void fetch(`/api/buoys/${encodeURIComponent(id)}/history`, { signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(); return response.json(); })
      .then(data => {
        if (selectionRef.current === id && !controller.signal.aborted) {
          setHistory(data.observations); setHistoryStatus(data.status);
        }
      }).catch(() => { if (!controller.signal.aborted && selectionRef.current === id) setHistoryStatus('HISTORY UNAVAILABLE'); });
  }, []);

  // Exactly one connection for the lifetime of the panel host, including when closed.
  useEffect(() => {
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let delay = 1000;
    function connect() {
      const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/buoys`);
      socketRef.current = ws;
      setWebsocketStatus('CONNECTING');
      ws.onopen = () => {
        delay = 1000; setWebsocketStatus('CONNECTED');
        if (selectionRef.current) {
          ws.send(JSON.stringify({ type: 'subscribe', buoyId: selectionRef.current }));
          loadHistory(selectionRef.current);
        }
      };
      ws.onmessage = event => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.buoyId !== selectionRef.current) return;
          if (msg.type === 'buoy_state') {
            setDetail(previous => previous && previous.id === msg.buoyId && previous.observationTimestamp &&
              (!msg.buoy.observationTimestamp || Date.parse(previous.observationTimestamp) > Date.parse(msg.buoy.observationTimestamp))
              ? { ...msg.buoy, observationTimestamp: previous.observationTimestamp, telemetry: previous.telemetry }
              : msg.buoy);
            setLoading(false); setError(null);
          } else if (msg.type === 'buoy_status') {
            setDetail(previous => previous && previous.id === msg.buoyId ? { ...previous,
              freshness: msg.freshness, providerStatus: msg.providerStatus, error: msg.error, pipeline: msg.pipeline } : previous);
          } else if (msg.type === 'buoy_update') {
            setDetail(previous => {
              if (!previous || previous.id !== msg.buoyId || (previous.observationTimestamp &&
                Date.parse(previous.observationTimestamp) > Date.parse(msg.timestamp))) return previous;
              return { ...previous, observationTimestamp: msg.timestamp, telemetry: msg.telemetry as Telemetry,
                source: "INCOIS", providerStatus: "CONNECTED", error: null };
            });
            // Keep only a bounded recent window for this selected station.
            setHistory(previous => [...previous.filter(o => o.timestamp !== msg.timestamp),
              { timestamp: msg.timestamp, telemetry: msg.telemetry }].sort((a,b) => Date.parse(a.timestamp)-Date.parse(b.timestamp)).slice(-120));
          }
        } catch { /* Invalid frames leave the last known values visible. */ }
      };
      ws.onerror = () => ws.close();
      ws.onclose = () => {
        if (!stopped) {
          setWebsocketStatus('RECONNECTING');
          retry = setTimeout(connect, delay); delay = Math.min(30000, delay * 2);
        }
      };
    }
    connect();
    return () => { stopped = true; clearTimeout(retry); socketRef.current?.close(); historyAbort.current?.abort(); };
  }, [loadHistory]);

  useEffect(() => {
    const id = selected?.id ?? null;
    setDetail(null); setHistory([]); setHistoryStatus(''); setError(null);
    historyAbort.current?.abort();
    const ws = socketRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(id ? { type: 'subscribe', buoyId: id } : { type: 'unsubscribe' }));
    if (!id) { setLoading(false); return; }
    setLoading(true);
    const controller = new AbortController();
    void fetch(`/api/buoys/${encodeURIComponent(id)}`, { signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(); return response.json() as Promise<BuoyDetail>; })
      .then(data => {
        if (selectionRef.current !== id || controller.signal.aborted) return;
        setDetail(previous => previous?.id === id && previous.observationTimestamp &&
          (!data.observationTimestamp || Date.parse(previous.observationTimestamp) > Date.parse(data.observationTimestamp)) ? previous : data);
      }).catch(() => {
        if (!controller.signal.aborted && selectionRef.current === id) setError('TELEMETRY UNAVAILABLE');
      }).finally(() => { if (!controller.signal.aborted && selectionRef.current === id) setLoading(false); });
    loadHistory(id);
    return () => controller.abort();
  }, [selected?.id, loadHistory]);
  return { detail, history, historyStatus, loading, error, websocketStatus };
}
