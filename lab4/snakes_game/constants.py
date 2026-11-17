"""Константы протокола и игры. Значения взяты из задания (snakes_task.md)."""

PROTOCOL_VERSION = 2

# --- Обнаружение игр ---
MULTICAST_GROUP = "239.192.0.4"
MULTICAST_PORT = 9193
COURSE_SERVER_HOST = "snakes.ippolitov.me"
COURSE_SERVER_PORT = 9193

# --- Ограничения игры ---
MAX_DATAGRAM_SIZE = 1200
MAX_PLAYERS = 6          # включая наблюдателей
MAX_SNAKES = 4
MIN_SNAKE_LEN = 2
MAX_SNAKE_LEN = 32
MAX_PLAYER_NAME_BYTES = 24
MAX_GAME_NAME_BYTES = 32
MAX_ERROR_BYTES = 128
SPAWN_SQUARE_RADIUS = 2  # квадрат 5x5 вокруг головы

INT32_MAX = 2 ** 31 - 1
INT64_MAX = 2 ** 63 - 1

# --- Диапазоны параметров ---
FIELD_MIN, FIELD_MAX = 10, 100
FOOD_STATIC_MIN, FOOD_STATIC_MAX = 0, 10
STATE_DELAY_MIN, STATE_DELAY_MAX = 100, 3000

# --- Таймеры (секунды, монотонные часы) ---
RETRY_INTERVAL = 0.1            # повтор неподтверждённого сообщения
PING_INTERVAL = 0.1             # Ping, если соседу ничего не отправляли
LINK_TIMEOUT = 1.0              # тишина => предполагаемый отказ
ANNOUNCE_INTERVAL = 1.0         # анонсы MASTER
ANNOUNCE_TTL = 3.0              # запись в списке игр устаревает
DISCOVER_INTERVAL = 1.0         # опрос каталога сервера при показе списка
CONFIG_DISCOVER_INTERVAL = 0.5  # Discover до получения конфига
JOIN_TIMEOUT = 5.0              # ACK на Join + конфиг
REJOIN_SEARCH_TIMEOUT = 3.0     # поиск нового анонса после отказа MASTER
LEAVE_TIMEOUT = 1.0             # ожидание ACK при выходе
IFACE_REFRESH_INTERVAL = 5.0

# --- Надёжная доставка ---
DEDUP_WINDOW = 1024
MAX_PENDING_PER_PEER = 64
MAX_DEDUP_ENDPOINTS = 256       # бюджет кеша ответов (число endpoint)

# --- Прочее ---
LOOP_SELECT_TIMEOUT = 0.02
