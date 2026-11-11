import asyncio
from typing import Optional

import aiohttp

from . import service
from .config import USER_AGENT, Config, load_config
from .models import Location, LocationInfo

_OSM_CATEGORIES = {
    ("highway", "bus_stop"): "остановка",
    ("public_transport", "platform"): "остановка",
    ("public_transport", "stop_position"): "остановка",
    ("railway", "tram_stop"): "остановка",
    ("amenity", "bus_station"): "автовокзал",
    ("amenity", "school"): "школа",
    ("amenity", "university"): "университет",
    ("amenity", "college"): "учебное заведение",
    ("amenity", "museum"): "музей",
    ("tourism", "museum"): "музей",
    ("amenity", "place_of_worship"): "храм",
    ("leisure", "park"): "парк",
    ("leisure", "garden"): "сад",
    ("historic", "monument"): "памятник",
    ("historic", "memorial"): "мемориал",
    ("railway", "station"): "станция",
    ("place", "city"): "город",
    ("place", "town"): "город",
    ("place", "village"): "село",
    ("highway", "residential"): "улица",
    ("highway", "unclassified"): "местная дорога",
    ("highway", "service"): "служебный проезд",
    ("highway", "living_street"): "жилая улица",
    ("highway", "pedestrian"): "пешеходная улица",
}


def _location_category(location: Location) -> str:
    key = location.osm_key.lower()
    value = location.osm_value.lower()
    category = _OSM_CATEGORIES.get((key, value))
    if category:
        return category
    if key and value:
        return f"{key}={value}"
    return value or key


def _session(cfg: Config) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        headers={"User-Agent": USER_AGENT},
        timeout=aiohttp.ClientTimeout(total=cfg.timeout_s),
    )


async def _search(cfg: Config, query: str) -> list[Location]:
    async with _session(cfg) as session:
        return await service.find_locations(session, cfg, query)


async def _load(cfg: Config, loc: Location) -> LocationInfo:
    async with _session(cfg) as session:
        return await service.load_location_info(session, cfg, loc)


def _choose(locations: list[Location]) -> Optional[Location]:
    print("\nНайденные локации:")
    for i, l in enumerate(locations, 1):
        label = _location_category(l)
        category = f" ({label})" if label else ""
        print(f"  {i}. {l.name}{category} ({l.description}) [{l.lat:.5f}, {l.lon:.5f}]")
    while True:
        raw = input("Выберите номер (Enter — отмена): ").strip()
        if not raw:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(locations):
            return locations[int(raw) - 1]
        print("Некорректный номер.")


def _show(info: LocationInfo) -> None:
    loc = info.location
    print("\n" + "=" * 60)
    print(f"{loc.name} ({loc.description})")
    print("=" * 60)
    w = info.weather
    if w:
        temp = f"{w.temp_c:.1f} °C" if w.temp_c is not None else "нет данных"
        feels_like = f"{w.feels_like_c:.1f} °C" if w.feels_like_c is not None else "нет данных"
        humidity = f"{w.humidity}%" if w.humidity is not None else "нет данных"
        pressure = (
            f"{w.pressure_hpa * 0.750061683:.1f} мм рт. ст."
            if w.pressure_hpa is not None else "нет данных"
        )
        wind = f"{w.wind_ms} м/с" if w.wind_ms is not None else "нет данных"
        print(f"\nПогода: {w.description}, {temp} (ощущается как {feels_like})")
        print(f"Влажность: {humidity}, давление: {pressure}, ветер: {wind}")
    if info.places:
        print(f"\nИнтересные места рядом ({len(info.places)}):")
        for i, p in enumerate(info.places, 1):
            print(f"\n{i}. {p.title} — {p.distance_m:.0f} м")
            print(f"   {p.description}")
    elif not any("недоступ" in e.lower() for e in info.errors):
        print("\nИнтересных мест поблизости не найдено.")
    for e in info.errors:
        print(f"\n[!] {e}")


def main() -> None:
    cfg = load_config()
    query = input("Введите название места: ").strip()
    if not query:
        print("Пустой запрос.")
        return
    try:
        locations = asyncio.run(_search(cfg, query))
        if not locations:
            print("Ничего не найдено.")
            return
        chosen = _choose(locations)
        if chosen is None:
            return
        print("Загрузка данных...")
        info = asyncio.run(_load(cfg, chosen))
    except aiohttp.ClientError as e:
        print(f"Ошибка сети/API: {e}")
        return
    _show(info)
