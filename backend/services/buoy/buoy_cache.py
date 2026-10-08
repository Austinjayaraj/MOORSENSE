from datetime import datetime, timezone
from .buoy_models import Observation

class BuoyCache:
    def __init__(self, live=10800, stale=21600, offline=86400):
        if not 0 < live < stale < offline:
            raise ValueError("Freshness thresholds must be positive and increasing")
        self.thresholds = (live, stale, offline)
        self.latest: dict[str, Observation] = {}
        self.checks: dict[str, datetime] = {}
        self.errors: dict[str, str] = {}
        self.pending = False

    def update(self, observation):
        old = self.latest.get(observation.buoyId)
        if old is None or observation.timestamp >= old.timestamp:
            self.latest[observation.buoyId] = observation

    def checked(self, buoy_id, error=None):
        self.checks[buoy_id] = datetime.now(timezone.utc)
        if error: self.errors[buoy_id] = error
        else: self.errors.pop(buoy_id, None)

    def freshness_state(self, age, has_error):
        """Cadence-aware freshness classification.

        INCOIS OMNI observed cadence is approximately 3 hours.
        Thresholds are configured as:
          live: cadence + grace (e.g. 3h + 1h = 4h, default 10800s = 3h)
          stale: 2x cadence + grace (default 21600s = 6h)
          offline: long absence (default 86400s = 24h)

        LATEST_AVAILABLE: source is reachable, observation exists, but age
        exceeds live threshold within the expected cadence window.
        """
        live, stale, offline = self.thresholds
        if age is None:
            return "OFFLINE"
        if has_error:
            return "SOURCE_UNAVAILABLE" if age > stale else "STALE"
        if age > offline:
            return "OFFLINE"
        if age > stale:
            return "STALE"
        if age > live:
            return "LATEST_AVAILABLE"
        return "FRESH"

    def detail(self, buoy):
        obs = self.latest.get(buoy.id)
        age = max(0, (datetime.now(timezone.utc) - obs.timestamp).total_seconds()) if obs else None
        live, stale, offline = self.thresholds
        has_error = buoy.id in self.errors
        state = self.freshness_state(age, has_error)
        return {**buoy.model_dump(), "observationTimestamp": obs.timestamp.isoformat() if obs else None,
                "telemetry": obs.telemetry.model_dump(mode="json") if obs else None,
                "source": obs.source if obs else "NIOT / INCOIS",
                "freshness": {"state": state, "ageSeconds": age,
                    "lastSourceCheck": self.checks[buoy.id].isoformat() if buoy.id in self.checks else None,
                    "sourceUnavailable": has_error,
                    "thresholds": {"live": live, "stale": stale, "offline": offline},
                    "source_cadence_seconds": live},
                "providerStatus": "SOURCE_UNAVAILABLE" if has_error else "CONNECTED" if buoy.id in self.checks else "CONNECTING",
                "sourceTimestamp": obs.timestamp.isoformat() if obs else None,
                "receivedAt": obs.receivedAt.isoformat() if obs else None,
                "location": {"latitude": buoy.latitude, "longitude": buoy.longitude},
                "error": self.errors.get(buoy.id)}
