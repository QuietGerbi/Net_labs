import asyncio
import aiohttp

from . import clients
from .config import Config
from .models import Location, LocationInfo, Place

async def find_locations(session: aiohttp.ClientSession, cfg: Config,
                         query: str) -> list[Location]:
    return await clients.geocode(session, cfg, query)

async def _places_chain(session: aiohttp.ClientSession, cfg: Config,
                        loc: Location) -> tuple[list[Place], list[str]]:
    found = await clients.geosearch(session, cfg, loc, cfg.max_places)
    if not found:
        return [], []
    ids = [item["pageid"] for item in found]
    chunks = [ids[i:i + 20] for i in range(0, len(ids), 20)]
    details: dict[int, tuple[str, str]] = {}
    errors: list[str] = []
    parts = await asyncio.gather(
        *(clients.get_extracts(session, c) for c in chunks),
        return_exceptions=True,
    )
    for i, part in enumerate(parts, 1):
        if isinstance(part, Exception):
            errors.append(f"Пакет описаний {i} недоступен: {part}")
        else:
            details.update(part)

    places: list[Place] = []
    for item in found:
        extract, short = details.get(item["pageid"], ("", ""))
        kind = item.get("type") or ""
        places.append(Place(
            page_id=item["pageid"], title=item["title"],
            distance_m=item.get("dist", 0.0),
            description=extract or short or "Описание отсутствует.",
            kind=kind, short=short,
        ))
    return places, errors

async def load_location_info(session: aiohttp.ClientSession, cfg: Config,
                             loc: Location) -> LocationInfo:
    weather_res, places_res = await asyncio.gather(
        clients.get_weather(session, cfg, loc),
        _places_chain(session, cfg, loc),
        return_exceptions=True,
    )
    info = LocationInfo(location=loc)
    if isinstance(weather_res, BaseException):
        info.errors.append(f"Погода недоступна: {weather_res}")
    else:
        info.weather = weather_res
    if isinstance(places_res, BaseException):
        info.errors.append(f"Места недоступны: {places_res}")
    else:
        info.places, place_errors = places_res
        info.errors.extend(place_errors)
    return info
