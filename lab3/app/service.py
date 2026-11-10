import asyncio
import aiohttp

from . import clients
from .config import Config
from .models import Location, LocationInfo, Place, kind_ru

async def find_locations(session: aiohttp.ClientSession, cfg: Config, query: str) -> list[Location]:
    return await clients.geocode(session, cfg, query)

_TAG_RULES = {
    "остановка": ["остановк"],
    "музей": ["музе"],
    "парк": ["парк", "сад", "сквер"],
    "храм": ["церк", "храм", "собор"],
    "вокзал": ["вокзал", "станци", "railwaystation"],
    "памятник": ["памятник", "монумент"],
    "мост": ["мост"],
    "школа": ["школ", "гимнази"],
    "университет": ["университет", "институт", "edu"],
    "улица": ["улиц"],
    "площадь": ["площад"],
    "достопримечательность": ["landmark"],
}

_TAG_ALIASES = {
    "bus_stop": "остановка", "остановка": "остановка",
    "museum": "музей", "музей": "музей",
    "park": "парк", "парк": "парк",
    "church": "храм", "храм": "храм", "церковь": "храм",
    "station": "вокзал", "вокзал": "вокзал", "станция": "вокзал",
    "monument": "памятник", "памятник": "памятник",
    "bridge": "мост", "мост": "мост",
    "school": "школа", "школа": "школа",
    "university": "университет", "университет": "университет",
    "street": "улица", "улица": "улица",
    "square": "площадь", "площадь": "площадь",
    "landmark": "достопримечательность",
    "достопримечательность": "достопримечательность",
}


def _stem(word: str) -> str:
    word = word.lower()
    if len(word) > 6:
        return word[:-2]
    if len(word) > 4:
        return word[:-1]
    return word


def _matches(tag: str, haystack: str) -> bool:
    key = tag.strip().lower().replace(" ", "_")
    canonical = _TAG_ALIASES.get(key, key)
    if canonical in _TAG_RULES:
        return any(a in haystack for a in _TAG_RULES[canonical])
    return all(_stem(w) in haystack for w in tag.lower().split())


def _classify(haystack: str) -> str:
    for tag, aliases in _TAG_RULES.items():
        if any(alias in haystack for alias in aliases):
            return tag
    return "прочее"

async def _places_chain(session: aiohttp.ClientSession, cfg: Config, loc: Location,
                        tags: tuple[str, ...]) -> list[Place]:
    limit = cfg.search_pool if tags else cfg.max_places
    found = await clients.geosearch(session, cfg, loc, limit)
    if not found:
        return []
    ids = [item["pageid"] for item in found]
    chunks = [ids[i:i + 20] for i in range(0, len(ids), 20)]   # лимит описаний: 20 за запрос
    parts = await asyncio.gather(*(clients.get_extracts(session, c) for c in chunks))
    details: dict[int, tuple[str, str]] = {}
    for part in parts:
        details.update(part)

    places: list[Place] = []
    for item in found:
        extract, short = details.get(item["pageid"], ("", ""))
        kind = item.get("type") or ""
        haystack = f"{kind} {kind_ru(kind)} {short}".lower()
        matched_tag = next((tag for tag in tags if _matches(tag, haystack)), None)
        if tags and matched_tag is None:
            continue
        assigned_tag = matched_tag or _classify(haystack)
        places.append(Place(
            page_id=item["pageid"], title=item["title"],
            distance_m=item.get("dist", 0.0),
            description=extract or short or "Описание отсутствует.",
            kind=kind, short=short, tag=assigned_tag,
        ))
        if len(places) >= cfg.max_places:
            break
    return places

async def load_location_info(session: aiohttp.ClientSession, cfg: Config, loc: Location,
                             tags: tuple[str, ...] = ()) -> LocationInfo:
    weather_res, places_res = await asyncio.gather(
        clients.get_weather(session, cfg, loc),
        _places_chain(session, cfg, loc, tags),
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
        info.places = places_res
    return info
