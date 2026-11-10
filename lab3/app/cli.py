import asyncio
from typing import Optional

import aiohttp

from . import service
from .config import USER_AGENT, Config, load_config
from .models import Location, LocationInfo, kind_ru


def _parse_query(raw: str) -> tuple[str, tuple[str, ...]]:
    name, *tags = [p.strip() for p in raw.split(",")]
    return name, tuple(t for t in tags if t)


def _session(cfg: Config) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        headers={"User-Agent": USER_AGENT},
        timeout=aiohttp.ClientTimeout(total=cfg.timeout_s),
    )


async def _search(cfg: Config, query: str) -> list[Location]:
    async with _session(cfg) as session:
        return await service.find_locations(session, cfg, query)


async def _load(cfg: Config, loc: Location, tags: tuple[str, ...]) -> LocationInfo:
    async with _session(cfg) as session:
        return await service.load_location_info(session, cfg, loc, tags)


def _choose(locations: list[Location]) -> Optional[Location]:
    print("\nНайденные локации:")
    for i, l in enumerate(locations, 1):
        print(f"  {i}. {l.name} ({l.description}) [{l.lat:.5f}, {l.lon:.5f}]")
    while True:
        raw = input("Выберите номер (Enter — отмена): ").strip()
        if not raw:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(locations):
            return locations[int(raw) - 1]
        print("Некорректный номер.")


def _show(info: LocationInfo, tags: tuple[str, ...] = ()) -> None:
    loc = info.location
    print("\n" + "=" * 60)
    print(f"{loc.name} ({loc.description})")
    print("=" * 60)
    w = info.weather
    if w:
        print(f"\nПогода: {w.description}, {w.temp_c:.1f} °C (ощущается как {w.feels_like_c:.1f} °C)")
        print(f"Влажность: {w.humidity}%, давление: {w.pressure_hpa} гПа, ветер: {w.wind_ms} м/с")
    if info.places:
        print(f"\nИнтересные места рядом ({len(info.places)}):")
        for i, p in enumerate(info.places, 1):
            label = p.tag or p.short or kind_ru(p.kind)
            tag = f" ({label})" if label else ""
            print(f"\n{i}. {p.title} — {p.distance_m:.0f} м{tag}")
            print(f"   {p.description}")
    elif not any("Места" in e for e in info.errors):
        what = f"с тегом «{', '.join(tags)}» " if tags else ""
        print(f"\nИнтересных мест {what}поблизости не найдено.")
    for e in info.errors:
        print(f"\n[!] {e}")


def main() -> None:
    cfg = load_config()
    raw = input("Введите название места (можно через запятую теги: Цветной проезд, музей): ").strip()
    query, tags = _parse_query(raw)
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
        info = asyncio.run(_load(cfg, chosen, tags)) 
    except aiohttp.ClientError as e:
        print(f"Ошибка сети/API: {e}")
        return
    _show(info, tags)
