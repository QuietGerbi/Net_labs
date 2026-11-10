import asyncio

import aiohttp

from . import clients
from .config import Config
from .models import Location, LocationInfo, Place


async def find_locations(session: aiohttp.ClientSession, cfg: Config, query: str) -> list[Location]:
    return await clients.geocode(session, cfg, query)


async def _places_chain(session: aiohttp.ClientSession, cfg: Config, loc: Location) -> list[Place]:
    """Цепочка: geosearch -> один запрос описаний для всех найденных статей."""
    found = await clients.geosearch(session, cfg, loc)
    if not found:
        return []
    details = await clients.get_extracts(session, [item["pageid"] for item in found])
    places = []
    for item in found:
        extract, short = details.get(item["pageid"], ("", ""))
        places.append(Place(
            page_id=item["pageid"], title=item["title"],
            distance_m=item.get("dist", 0.0),
            description=extract or short or "Описание отсутствует.",
            kind=item.get("type") or "", short=short,
        ))
    return places


async def load_location_info(session: aiohttp.ClientSession, cfg: Config, loc: Location) -> LocationInfo:
    # Погода и места не зависят друг от друга — выполняются одновременно.
    weather_res, places_res = await asyncio.gather(
        clients.get_weather(session, cfg, loc),
        _places_chain(session, cfg, loc),
        return_exceptions=True,  # сбой одной части не ломает остальные
    )
    info = LocationInfo(location=loc)
    if isinstance(weather_res, BaseException):
        info.errors.append(f"Погода недоступна: {weather_res}")
    else:
        info.weather = weather_res
    if isinstance(places_res, BaseException):
        info.errors.append(f"Места недоступны: {places_res}")
    else:
        info.places = places_res
    return info
