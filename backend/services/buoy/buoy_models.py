from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

class Metric(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    value: float | None = None
    unit: str

class ProfilePoint(Metric):
    depth: float = Field(ge=0)
    depthUnit: Literal["m"] = "m"

class Telemetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meteorology: dict[str, Metric] = Field(default_factory=dict)
    ocean: dict[str, Metric] = Field(default_factory=dict)
    waves: dict[str, Metric] = Field(default_factory=dict)
    profiles: dict[str, list[ProfilePoint]] = Field(default_factory=dict)

class Buoy(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str
    type: str
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    status: Literal["SAFE", "WARNING", "CRITICAL", "ADRIFT", "OFFLINE", "UNKNOWN"] = "UNKNOWN"
    coordinateKind: str = "deployment"
    metadataSource: str = "NIOT"
    metadataRetrievedAt: str | None = None
    reportingStatus: str | None = None
    agency: str | None = None

class Observation(BaseModel):
    buoyId: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    timestamp: datetime
    receivedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "INCOIS"
    observationId: str | None = None
    telemetry: Telemetry
    rawPayload: dict = Field(default_factory=dict)
    location: dict[str, float] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError("Source timestamp must include a timezone")
        if value > datetime.now(timezone.utc):
            raise ValueError("Source timestamp cannot be in the future")
        return value.astimezone(timezone.utc)

    @property
    def identity(self):
        return f"{self.buoyId}:{self.timestamp.isoformat()}"

    def event(self):
        return {"eventType": "BUOY_TELEMETRY", "eventId": self.identity,
                "buoyId": self.buoyId, "timestamp": self.timestamp.isoformat(),
                "observationTimestamp": self.timestamp.isoformat(), "sourceTimestamp": self.timestamp.isoformat(),
                "location": self.location,
                "receivedAt": self.receivedAt.isoformat(), "source": self.source,
                "observationId": self.observationId,
                "telemetry": self.telemetry.model_dump(mode="json"), "rawPayload": self.rawPayload}
