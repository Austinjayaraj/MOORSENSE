import asyncio
import json
import logging
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from .incois_provider import IncoisBuoyProvider
from .buoy_cache import BuoyCache
from .buoy_models import Observation
from .event_outbox import EventOutbox
from .persistence import ObservationStore
from .mooring_models import MooringConfiguration, MooringEstimate
from .mooring_store import MooringStore
from .physics_service import compute_mooring_estimate
from services.mooring.config_resolver import MooringConfigResolver
from services.mooring.fleet_runner import FleetRunner
from services.mooring.mooring_response import compute_mooring_response
from workers.buoy_ingestion_worker import BuoyIngestionWorker

log = logging.getLogger(__name__)
TOPIC = "moorsense.telemetry"
MOORING_TOPIC = "moorsense.mooring"

class BuoySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    buoy_poll_interval_seconds: int = Field(default=60, ge=60)
    buoy_live_threshold_seconds: int = Field(default=10800, gt=0)
    buoy_stale_threshold_seconds: int = Field(default=21600, gt=0)
    buoy_offline_threshold_seconds: int = Field(default=86400, gt=0)
    buoy_source_cadence_seconds: int = Field(default=10800, gt=0)
    buoy_freshness_grace_seconds: int = Field(default=3600, gt=0)
    buoy_debug_source_enabled: bool = False
    environment: str = "production"
    buoy_ingestion_enabled: bool = True
    buoy_outbox_path: str = "data/buoy_outbox.sqlite3"
    kafka_bootstrap_servers: str = "localhost:9092"
    buoy_database_url: str = "postgresql://moorsense:moorsense@localhost:15432/moorsense"
    buoy_ws_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"

class WebSocketManager:
    def __init__(self): self.clients = {}

    def add(self, ws): self.clients[ws] = {"buoyId": None, "queue": asyncio.Queue(maxsize=32)}
    def remove(self, ws): self.clients.pop(ws, None)

    async def broadcast(self, event):
        update = {"type": "buoy_update", "buoyId": event["buoyId"],
                  "timestamp": event["timestamp"], "observationTimestamp": event["timestamp"], "telemetry": event["telemetry"]}
        for client in list(self.clients.values()):
            if client["buoyId"] == event["buoyId"]:
                queue = client["queue"]
                if queue.full(): queue.get_nowait() # UI requires only latest state
                queue.put_nowait(update)
        log.info("[WEBSOCKET] Broadcast %s update", event["buoyId"])

class BuoyRuntime:
    def __init__(self, provider=None, config=None):
        self.config = config or BuoySettings()
        self.provider = provider or IncoisBuoyProvider()
        self.cache = BuoyCache(self.config.buoy_live_threshold_seconds,
                              self.config.buoy_stale_threshold_seconds, self.config.buoy_offline_threshold_seconds)
        self.store = ObservationStore(self.config.buoy_database_url)
        self.mooring_store = MooringStore(self.store)
        self.manager = WebSocketManager()
        self.tasks = []
        self.outbox = None
        self.buoys = {}
        self.mooring_configs: dict[str, MooringConfiguration] = {}
        self.latest_estimates: dict[str, MooringEstimate] = {}
        self.kafka_status = "CONNECTING"
        self.persistence_status = "CONNECTING"
        # New Digital Twin subsystem
        self.config_resolver = MooringConfigResolver()
        self.fleet_runner = FleetRunner(self.config_resolver)

    async def start(self):
        try: self.buoys.update({b.id: b for b in await self.provider.get_buoys()})
        except Exception: log.warning("[INCOIS] Initial catalog unavailable; worker will retry")
        self.tasks = [asyncio.create_task(self.consume("ui")), asyncio.create_task(self.consume("persistence"))]
        if self.config.buoy_ingestion_enabled:
            self.outbox = EventOutbox(self.config.buoy_outbox_path)
            worker = BuoyIngestionWorker(self.provider,self.cache,self.outbox,self.config.buoy_poll_interval_seconds, self.buoys)
            self.tasks.extend([asyncio.create_task(worker.run()),asyncio.create_task(self.publish())])
        try:
            await self.mooring_store.ensure_schema()
            await self._load_mooring_configs()
        except Exception as exc:
            log.warning("[MOORING] Schema/config init deferred (%s)", type(exc).__name__)

    async def stop(self):
        for task in self.tasks: task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.store.close()
        if hasattr(self.provider,"close"): await self.provider.close()
        if self.outbox: self.outbox.close()

    async def publish(self):
        delay = 1
        while True:
            producer = AIOKafkaProducer(bootstrap_servers=self.config.kafka_bootstrap_servers,
                enable_idempotence=True, request_timeout_ms=5000)
            try:
                await producer.start()
                delay = 1
                self.kafka_status = "CONNECTED"
                while True:
                    for key, event in self.outbox.pending():
                        await asyncio.wait_for(producer.send_and_wait(TOPIC,
                            json.dumps(event).encode(), key=event["buoyId"].encode()),timeout=15)
                        self.outbox.acknowledge(key)
                        log.info("[KAFKA] Published %s key=%s", TOPIC,event["buoyId"])
                    await asyncio.sleep(1)
            except Exception as exc:
                self.kafka_status = "RECONNECTING"
                log.warning("[KAFKA] Publisher retry (%s)",type(exc).__name__)
            finally:
                with suppress(Exception): await producer.stop()
            await asyncio.sleep(delay)
            delay = min(30,delay*2)

    async def consume(self, purpose):
        # Every API instance needs its own UI consumer group. Persistence is shared.
        group = f"{TOPIC}.persistence" if purpose == "persistence" else f"{TOPIC}.ui.{uuid.uuid4()}"
        delay = 1
        delivered = {}
        while True:
            consumer = AIOKafkaConsumer(TOPIC, bootstrap_servers=self.config.kafka_bootstrap_servers,
                group_id=group, enable_auto_commit=False, auto_offset_reset="earliest",
                request_timeout_ms=10000)
            try:
                await consumer.start()
                if purpose == "persistence":
                    await self.store.connect()
                    self.persistence_status = "CONNECTED"
                elif not self.config.buoy_ingestion_enabled: self.kafka_status = "CONNECTED"
                delay = 1
                async for message in consumer:
                    try:
                        event = json.loads(message.value)
                        if event.get("eventType") != "BUOY_TELEMETRY": raise ValueError("Unexpected event type")
                        if TOPIC == "moorsense.telemetry" and event.get("source") != "INCOIS":
                            raise ValueError("Production topic only accepts INCOIS observations")
                        obs = Observation.model_validate(event)
                        if obs.buoyId not in self.buoys or message.key != obs.buoyId.encode():
                            raise ValueError("Unknown station or incorrect partition key")
                        event["eventId"] = obs.identity
                        datetime.fromisoformat(event["receivedAt"])
                    except Exception:
                        log.warning("[KAFKA] Invalid telemetry event rejected")
                        await consumer.commit()
                        continue
                    if purpose == "persistence":
                        while True:
                            try:
                                await self.store.save(event)
                                self.persistence_status = "CONNECTED"
                                break
                            except Exception as exc:
                                self.persistence_status = "RECONNECTING"
                                log.warning("[POSTGRES] Retrying uncommitted observation (%s)",type(exc).__name__)
                                await asyncio.sleep(5)
                    else:
                        old = delivered.get(obs.buoyId)
                        self.cache.update(obs)
                        if not old or obs.timestamp > old.timestamp or (obs.timestamp == old.timestamp and obs.identity != old.identity):
                            delivered[obs.buoyId] = obs
                            await self.manager.broadcast(event)
                            try:
                                await self._run_mooring_calculation(event)
                            except Exception as exc:
                                log.warning("[MOORING] Calculation failed for %s (%s)", obs.buoyId, type(exc).__name__)
                    await consumer.commit()
            except Exception as exc:
                if purpose == "persistence": self.persistence_status = "RECONNECTING"
                log.warning("[KAFKA] %s consumer retry (%s)",purpose,type(exc).__name__)
            finally:
                with suppress(Exception): await consumer.stop()
            await asyncio.sleep(delay)
            delay = min(30,delay*2)

    def detail(self, buoy_id):
        base = {**self.cache.detail(self.buoys[buoy_id]),
                "parameterAvailability": getattr(self.provider,"parameter_status",{}).get(buoy_id,{}),
                "pipeline": {"kafka": self.kafka_status,"persistence": self.persistence_status}}
        estimate = self.latest_estimates.get(buoy_id)
        if estimate:
            base["mooring_estimate"] = estimate.model_dump(mode="json")
        return base

    async def _load_mooring_configs(self):
        for buoy_id in list(self.buoys):
            try:
                db_config = await self.mooring_store.get_config(buoy_id)
                if db_config:
                    segments = [{"line_id": s["line_id"], "segment": s["segment"],
                                 "length_m": s.get("length_m"), "diameter_mm": s.get("diameter_mm"),
                                 "material": s.get("material"), "mass_per_m": s.get("mass_per_m"),
                                 "weight_per_m": s.get("weight_per_m"),
                                 "axial_stiffness": s.get("axial_stiffness"),
                                 "breaking_strength_N": s.get("breaking_strength_N")}
                                for s in db_config.get("line_segments", [])]
                    self.mooring_configs[buoy_id] = MooringConfiguration(
                        buoy_id=buoy_id, deployment_id=db_config.get("deployment_id"),
                        water_depth_m=db_config.get("water_depth_m"),
                        anchor_latitude=db_config.get("anchor_latitude"),
                        anchor_longitude=db_config.get("anchor_longitude"),
                        number_of_lines=db_config.get("number_of_lines"),
                        buoy_mass_kg=db_config.get("buoy_mass_kg"),
                        buoy_buoyancy_N=db_config.get("buoy_buoyancy_N"),
                        buoy_length_m=db_config.get("buoy_length_m"),
                        buoy_width_m=db_config.get("buoy_width_m"),
                        buoy_height_m=db_config.get("buoy_height_m"),
                        projected_area_m2=db_config.get("projected_area_m2"),
                        waterplane_area_m2=db_config.get("waterplane_area_m2"),
                        pretension_N=db_config.get("pretension_N"),
                        seabed_type=db_config.get("seabed_type"),
                        seabed_friction_coefficient=db_config.get("seabed_friction_coefficient"),
                        line_segments=segments,
                        source=db_config.get("source"),
                        source_document=db_config.get("source_document"),
                        verified=db_config.get("verified", False),
                        availability="STATIC" if db_config.get("verified") else "UNAVAILABLE",
                    )
            except Exception:
                pass

    def _default_mooring_config(self, buoy_id: str) -> MooringConfiguration:
        return MooringConfiguration(
            buoy_id=buoy_id,
            availability="UNAVAILABLE",
            requires_authoritative_mooring_configuration=True,
        )

    async def get_mooring_config(self, buoy_id: str) -> dict:
        config = self.mooring_configs.get(buoy_id, self._default_mooring_config(buoy_id))
        result = config.model_dump(mode="json")
        result["data_classification"] = "STATIC" if config.availability == "STATIC" else "UNAVAILABLE"
        return result

    async def get_mooring_status(self, buoy_id: str) -> dict:
        estimate = self.latest_estimates.get(buoy_id)
        if estimate:
            return estimate.model_dump(mode="json")
        config = self.mooring_configs.get(buoy_id, self._default_mooring_config(buoy_id))
        return {"buoy_id": buoy_id, "model_status": "INSUFFICIENT_CONFIGURATION" if not config.is_sufficient_for_analysis() else "NO_OBSERVATION",
                "requires_authoritative_mooring_configuration": config.requires_authoritative_mooring_configuration}

    async def get_mooring_tension(self, buoy_id: str) -> dict:
        estimate = self.latest_estimates.get(buoy_id)
        if estimate:
            return {"buoy_id": buoy_id, "lines": [l.model_dump(mode="json") for l in estimate.lines],
                    "max_tension_N": estimate.max_tension_N, "max_utilization": estimate.max_utilization,
                    "risk_level": estimate.risk_level, "model_status": estimate.model_status,
                    "calculated_at": estimate.calculated_at}
        return {"buoy_id": buoy_id, "lines": [], "model_status": "INSUFFICIENT_CONFIGURATION"}

    async def _run_mooring_calculation(self, event: dict):
        buoy_id = event["buoyId"]
        config = self.mooring_configs.get(buoy_id, self._default_mooring_config(buoy_id))
        telemetry = event.get("telemetry", {})
        obs_ts = event.get("timestamp", "")
        event_id = f"mooring:{event.get('eventId', buoy_id + ':' + obs_ts)}"

        # Legacy estimate (for backward compat)
        estimate = compute_mooring_estimate(buoy_id, obs_ts, telemetry, config, event_id)
        self.latest_estimates[buoy_id] = estimate

        # New Digital Twin response
        buoy = self.buoys.get(buoy_id)
        if buoy:
            try:
                obs = self.cache.latest.get(buoy_id)
                age = (datetime.now(timezone.utc) - obs.timestamp).total_seconds() if obs else None
                response = compute_mooring_response(
                    buoy_id=buoy_id, latitude=buoy.latitude, longitude=buoy.longitude,
                    telemetry=telemetry, observation_timestamp=obs_ts,
                    resolver=self.config_resolver, telemetry_age_seconds=age)
                self.fleet_runner.latest_responses[buoy_id] = response
                self.fleet_runner.latest_configs[buoy_id] = self.config_resolver.resolve(
                    buoy_id, buoy.latitude, buoy.longitude)
                # Broadcast mooring update via WebSocket
                await self.manager.broadcast({
                    "type": "mooring_response", "buoyId": buoy_id,
                    "timestamp": obs_ts,
                    "response": {
                        "fairlead_tension_kN": round(response.fairlead_tension_n / 1000, 2) if response.fairlead_tension_n else None,
                        "anchor_tension_kN": round(response.anchor_tension_n / 1000, 2) if response.anchor_tension_n else None,
                        "line_angle_deg": response.line_angle_deg,
                        "utilization": response.utilization,
                        "safety_factor": response.safety_factor,
                        "risk": response.risk_state,
                        "confidence": response.confidence,
                    }})
            except Exception as exc:
                log.warning("[MOORING] Digital Twin calc failed for %s (%s)", buoy_id, type(exc).__name__)

        try:
            await self.mooring_store.save_estimate(estimate.model_dump(mode="json"))
        except Exception as exc:
            log.warning("[MOORING] Failed to persist estimate (%s)", type(exc).__name__)

    def run_fleet_digital_twin(self):
        """Run Digital Twin for the entire accessible fleet. Returns fleet summary."""
        return self.fleet_runner.run_fleet(self.buoys, self.cache)
