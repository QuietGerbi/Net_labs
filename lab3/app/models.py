from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Location:
    name: str
    lat: float
    lon: float
    description: str  


@dataclass(frozen=True)
class Weather:
    description: str
    temp_c: float
    feels_like_c: float
    humidity: int
    pressure_hpa: int
    wind_ms: float


@dataclass(frozen=True)
class Place:
    page_id: int
    title: str
    distance_m: float
    description: str
    kind: str = ""
    short: str = "" 


@dataclass
class LocationInfo:
    """Общий объект результата: погода + интересные места (+ ошибки частей)."""
    location: Location
    weather: Optional[Weather] = None
    places: list[Place] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
