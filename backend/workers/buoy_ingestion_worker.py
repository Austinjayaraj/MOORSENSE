import asyncio
import logging

log = logging.getLogger(__name__)

class BuoyIngestionWorker:
    def __init__(self, provider, cache, outbox, interval=60, catalog=None):
        self.provider, self.cache, self.outbox = provider, cache, outbox
        self.interval = max(60, interval)
        self.catalog = catalog if catalog is not None else {}
        self.new_observations = []

    async def poll_once(self):
        try:
            await self.provider.refresh()
            buoys = await self.provider.get_buoys()
            self.catalog.update({b.id:b for b in buoys})
            self.cache.pending = False
        except Exception as exc:
            for buoy in self.catalog.values(): self.cache.checked(buoy.id, "SOURCE UNAVAILABLE")
            log.warning("[BUOY INGESTION] Source unavailable (%s)", type(exc).__name__)
            return
        for buoy in buoys:
            try:
                observation = await self.provider.get_latest_observation(buoy.id)
                self.cache.checked(buoy.id, "SOURCE UNAVAILABLE" if observation is None else None)
                if observation:
                    log.info("[BUOY INGESTION] %s latest observation: %s", buoy.id, observation.timestamp)
                    # Source history is genuine, never a fabricated arrival. Catch up
                    # in chronological order, with the same durable deduplication.
                    history = getattr(self.provider,"observations",{}).get(buoy.id,[observation])
                    for previous in history[:-1]: self.outbox.add(previous)
                    if self.outbox.add(observation):
                        log.info("[BUOY INGESTION] %s new observation detected", buoy.id)
                    self.cache.update(observation)
            except Exception as exc:
                self.cache.checked(buoy.id, "TELEMETRY UNAVAILABLE")
                log.warning("[BUOY INGESTION] %s failed (%s)", buoy.id, type(exc).__name__)

    async def run(self):
        while True:
            try: await self.poll_once()
            except Exception as exc: log.warning("[BUOY INGESTION] Cycle failed (%s)", type(exc).__name__)
            await asyncio.sleep(self.interval)
