# Multicast Discovery

Утилита для обнаружения запущенных на разных хостах (или процессах)
копий приложения через multicast-рассылку (поддерживает IPv4 и IPv6).

## Структура проекта

```
multicast_discovery/
├── README.md              # эта инструкция
├── run.py                 # точка входа (запускаемый скрипт)
└── discovery/
    ├── __init__.py        # экспортирует MulticastDiscovery
    ├── core.py             # класс MulticastDiscovery (вся логика обнаружения)
    └── cli.py              # разбор аргументов командной строки и main()
```

- `discovery/core.py` — сетевой сокет, join к multicast-группе,
  отправка/приём ANNOUNCE/BYE, отслеживание живых пиров.
- `discovery/cli.py` — `parse_args()` и `main()`, обработка сигналов
  SIGINT/SIGTERM.
- `run.py` — тонкая точка входа, которая просто вызывает `main()`.

Используются модули как стандартной библиотеки Python так и библиотека psuitil

## Требования

- Python 3.7+
- ОС: macOS/Windows/Linux

## Подготовка

Установите зависимости в корне проекта
```bash
pip install -r requirements.txt
```

## Запуск

Из корня проекта (там, где лежит `run.py`):

```bash
# IPv4-пример
python3 run.py <IPv4 multicast> [port] [net_interface]

# IPv6-пример
python3 run.py <IPv6 multicast> [port] [net_interface]
```
Где IPv4/6 в диапозоне мультикаст адресов, (optinal) port - порт от 1 до 65535 и (optional) net_interface - сетевой интерфейс на устройстве

Запустите скрипт в нескольких терминалах (или на нескольких машинах в
одной сети) с одинаковым multicast-адресом и портом — каждый экземпляр
начнёт видеть остальные и выводить список живых копий с их IP-адресами.

Остановка — `Ctrl+C` (или `SIGTERM`), при этом инстанс разошлёт `BYE`
перед выходом.

## Импорт как модуля

Класс также можно использовать программно:

```python
from discovery import MulticastDiscovery

app = MulticastDiscovery("239.255.0.1", 60000)
app.run()
```
