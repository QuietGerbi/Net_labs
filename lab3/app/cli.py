import asyncio

import aiohttp

from . import service
from .config import USER_AGENT, Config, load_config
from .models import Location, LocationInfo
from typing import Optional

_KIND_RU = {
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
        print(f"  {i}. {l.name} ({l.description}) [{l.lat:.5f}, {l.lon:.5f}]")
    while True:
        raw = input("Выберите номер (Enter — отмена): ").strip()
        if not raw:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(locations):
            return locations[int(raw) - 1]
        print("Некорректный номер.")

def _kind_ru(kind: str) -> str:
    return _KIND_RU.get(kind, kind)

def _show(info: LocationInfo) -> None:
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
            label = p.short or _kind_ru(p.kind)
            tag = f" ({label})" if label else ""
            print(f"\n{i}. {p.title} — {p.distance_m:.0f} м{tag}")
            print(f"   {p.description}")
    elif not any("Места" in e for e in info.errors):
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
