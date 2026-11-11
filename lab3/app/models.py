from dataclasses import dataclass, field
from typing import Optional

@dataclass(frozen=True)
class Location:
    name: str
    lat: float
    lon: float
    description: str
    osm_key: str = ""
    osm_value: str = ""

@dataclass(frozen=True)
class Weather:
    description: str
    temp_c: Optional[float]
    feels_like_c: Optional[float]
    humidity: Optional[int]
    pressure_hpa: Optional[int]
    wind_ms: Optional[float]

@dataclass(frozen=True)
class Place:
    page_id: Optional[int]
    title: str
    distance_m: float
    description: str
    kind: str = ""
    short: str = "" 
    tag: str = ""

@dataclass
class LocationInfo:
    location: Location
    weather: Optional[Weather] = None
    places: list[Place] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

KIND_RU = {
    "country": "страна",
    "adm1st": "регион",
    "adm2nd": "округ",
    "adm3rd": "район",
    "city": "населённый пункт",
    "isle": "остров",
    "mountain": "гора",
    "airport": "аэропорт",
    "landmark": "достопримечательность",
    "railwaystation": "ж/д станция",
    "river": "река",
    "forest": "лес",
    "edu": "учебное заведение",
    "event": "событие",
    "waterbody": "водоём",
    "glacier": "ледник",
    "camera": "точка съёмки",
}

def kind_ru(kind: str) -> str:
    return KIND_RU.get(kind, kind)
