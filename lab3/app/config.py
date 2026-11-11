import os
from dataclasses import dataclass
from pathlib import Path

GRAPHHOPPER_URL = "https://graphhopper.com/api/1/geocode"
OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
WIKI_API_URL = "https://ru.wikipedia.org/w/api.php"

USER_AGENT = "PlacesAsyncApp/1.0 (https://github.com/QuietGerbi/Net_labs.git; arhipos497@gmail.com) aiohttp"


@dataclass(frozen=True)
class Config:
    graphhopper_key: str
    openweather_key: str
    search_radius_m: int = 1000     
    max_places: int = 20            
    max_locations: int = 10          
    timeout_s: int = 15


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config() -> Config:
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    gh = os.environ.get("GRAPHHOPPER_API_KEY", "")
    ow = os.environ.get("OPENWEATHER_API_KEY", "")
    missing = [n for n, v in (("GRAPHHOPPER_API_KEY", gh), ("OPENWEATHER_API_KEY", ow)) if not v]
    if missing:
        raise SystemExit(
            "Не заданы ключи API: " + ", ".join(missing) +
            "\nСоздайте файл .env по образцу .env.example или задайте переменные окружения."
        )
    return Config(graphhopper_key=gh, openweather_key=ow)
