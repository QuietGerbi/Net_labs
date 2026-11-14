"""Параметры прокси."""

BUF_SIZE = 64 * 1024          # лимит буфера на одно направление (при заполнении чтение приостанавливается)
HS_RECV_SIZE = 4096           # размер чтения на этапе рукопожатия
HANDSHAKE_TIMEOUT = 30.0      # на получение greeting + request, сек
CONNECT_TIMEOUT = 15.0        # на одну попытку TCP connect, сек
DNS_TIMEOUT = 3.0             # тайм-аут одной попытки DNS, сек
DNS_ATTEMPTS = 3              # всего попыток (первая + 2 повтора)
LISTEN_BACKLOG = 256
