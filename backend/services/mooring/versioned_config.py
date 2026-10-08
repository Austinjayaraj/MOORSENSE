"""Versioned mooring configuration with temporal resolution.

Supports multiple configuration versions per station (e.g. after recovery/redeployment).
A telemetry timestamp resolves to the configuration valid at that time.

Precedence order for resolve_configuration():
1. Verified deployment-specific configuration (AUTHORITATIVE)
2. Authoritative station configuration
3. Published OMNI fleet reference (PUBLISHED_REFERENCE)
4. Engineering reference (REFERENCE)
5. Assumption (ASSUMPTION)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

ConfigPrecedence = Literal[
    "AUTHORITATIVE", "STATION_AUTHORITATIVE",
    "PUBLISHED_REFERENCE", "REFERENCE", "ASSUMPTION",
]

MODEL_VERSION = "moorsense-0.4"
PHYSICS_VERSION = "catenary-0.4"
CONFIGURATION_VERSION = "omni-reference-1"
ENVIRONMENT_VERSION = "incois-telemetry"


@dataclass
class MooringConfigVersionEntry:
    """Single versioned configuration record for a station."""
    station_id: str
    deployment_id: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    configuration: dict  # serialized MooringConfiguration or dict
    precedence: ConfigPrecedence
    source: str
    source_url: str | None = None
    source_document: str | None = None
    confidence: str = "LOW"
    notes: str | None = None


class MooringConfigRegistry:
    """In-memory registry of versioned mooring configurations per station.

    Station-specific authoritative configurations can be registered here.
    All currently registered configurations are REFERENCE or ASSUMPTION
    (no authoritative NIOT deployment specs have been obtained).
    """

    def __init__(self):
        self._registry: dict[str, list[MooringConfigVersionEntry]] = {}

    def register(self, entry: MooringConfigVersionEntry):
        """Register a versioned configuration entry for a station."""
        self._registry.setdefault(entry.station_id, []).append(entry)
        self._registry[entry.station_id].sort(key=lambda e: e.valid_from or datetime.min)

    def resolve_at(self, station_id: str, observation_timestamp: datetime) -> MooringConfigVersionEntry | None:
        """Return the highest-precedence configuration valid at the given timestamp.

        Time-safety: only configurations with valid_from <= observation_timestamp are considered.
        Returns None if no configuration is registered.
        """
        entries = self._registry.get(station_id, [])
        if not entries:
            return None
        ts = observation_timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        eligible = [
            e for e in entries
            if (e.valid_from is None or e.valid_from <= ts)
            and (e.valid_to is None or e.valid_to > ts)
        ]
        if not eligible:
            return None
        prec_order = ["AUTHORITATIVE", "STATION_AUTHORITATIVE",
                      "PUBLISHED_REFERENCE", "REFERENCE", "ASSUMPTION"]
        for prec in prec_order:
            candidates = [e for e in eligible if e.precedence == prec]
            if candidates:
                return candidates[-1]  # latest valid_from wins
        return eligible[-1]

    def all_versions(self, station_id: str) -> list[MooringConfigVersionEntry]:
        return list(self._registry.get(station_id, []))


def model_version_metadata() -> dict:
    """Return a dict describing the current model version stack."""
    return {
        "model_version": MODEL_VERSION,
        "physics_version": PHYSICS_VERSION,
        "configuration_version": CONFIGURATION_VERSION,
        "environment_version": ENVIRONMENT_VERSION,
    }
