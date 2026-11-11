from typing import Any

import aiohttp
import asyncio

from .config import (Config, GRAPHHOPPER_URL, OPENWEATHER_URL, WIKI_API_URL)
from .models import Location, Weather

async def _get_json(session: aiohttp.ClientSession, url: str, params: dict[str, Any],
                    retries: int = 4) -> dict:
    for attempt in range(retries + 1):
        async with session.get(url, params=params) as resp:
            if resp.status != 429 or attempt == retries:
                resp.raise_for_status()
                return await resp.json(content_type=None)
            try:
                delay = float(resp.headers.get("Retry-After", ""))
            except ValueError:
                delay = 2 ** attempt
        await asyncio.sleep(delay)
    raise RuntimeError("unreachable")

async def geocode(session: aiohttp.ClientSession, cfg: Config, query: str) -> list[Location]:
    data = await _get_json(session, GRAPHHOPPER_URL, {
        "q": query, "key": cfg.graphhopper_key,
        "limit": cfg.max_locations, "locale": "ru",
    })
    result = []
    for hit in data.get("hits", []):
        point = hit.get("point") or {}
        if "lat" not in point or "lng" not in point:
            continue
        parts = [hit.get(k) for k in ("street", "city", "state", "country")]
        result.append(Location(
            name=hit.get("name", "—"),
            lat=point["lat"], lon=point["lng"],
            description=", ".join(p for p in parts if p),
        ))
    return result

async def get_weather(session: aiohttp.ClientSession, cfg: Config, loc: Location) -> Weather:
    d = await _get_json(session, OPENWEATHER_URL, {
        "lat": loc.lat, "lon": loc.lon, "appid": cfg.openweather_key,
        "units": "metric", "lang": "ru",
    })
    main, wind = d.get("main", {}), d.get("wind", {})
    weather_list = d.get("weather") or [{}]
    return Weather(
        description=weather_list[0].get("description", "—"),
        temp_c=main.get("temp"),
        feels_like_c=main.get("feels_like"),
        humidity=main.get("humidity"),
        pressure_hpa=main.get("pressure"),
        wind_ms=wind.get("speed"),
    )

async def geosearch(session: aiohttp.ClientSession, cfg: Config, loc: Location,
                    limit: int) -> list[dict]:
    data = await _get_json(session, WIKI_API_URL, {
        "action": "query", "list": "geosearch",
        "gscoord": f"{loc.lat}|{loc.lon}",
        "gsradius": cfg.search_radius_m, "gslimit": limit,
        "gsprop": "type",
        "format": "json",
    })
    return data.get("query", {}).get("geosearch", [])

async def get_extracts(session: aiohttp.ClientSession,
                       page_ids: list[int]) -> dict[int, tuple[str, str]]:
    data = await _get_json(session, WIKI_API_URL, {
        "action": "query", "prop": "extracts|description",
        "pageids": "|".join(map(str, page_ids)),
        "exintro": 1, "explaintext": 1, "exchars": 500, "exlimit": "max",
        "format": "json",
    })
    pages = data.get("query", {}).get("pages", {})
    return {
        int(pid): ((p.get("extract") or "").strip(), p.get("description") or "")
        for pid, p in pages.items()
    }
