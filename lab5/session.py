"""Состояние одного клиентского соединения."""

GREETING, REQUEST, RESOLVING, CONNECTING, RELAY, CLOSING = range(6)


class Session:
    __slots__ = ("csock", "rsock", "state", "hs", "c2r", "r2c", "c_eof", "r_eof",
                 "c_shut", "r_shut", "closed", "cmask", "rmask", "timer_gen",
                 "port", "addrs", "qname", "qwire", "dns_id", "attempts", "last_rep")

    def __init__(self, csock):
        self.csock = csock          # сокет клиента
        self.rsock = None           # сокет целевого сервера
        self.state = GREETING
        self.hs = bytearray()       # входные данные рукопожатия
        self.c2r = bytearray()      # клиент -> сервер (ожидает отправки на сервер)
        self.r2c = bytearray()      # сервер -> клиент (в т.ч. SOCKS-ответы)
        self.c_eof = self.r_eof = False      # прочитан FIN от стороны
        self.c_shut = self.r_shut = False    # мы сделали shutdown(WR) в её сторону
        self.closed = False
        self.cmask = 0              # события, на которые подписан csock
        self.rmask = 0              # события, на которые подписан rsock
        self.timer_gen = 0
        self.port = 0
        self.addrs = []             # оставшиеся адреса для попыток connect
        self.qname = None           # имя для DNS (нижний регистр)
        self.qwire = None           # имя в формате DNS-пакета
        self.dns_id = None
        self.attempts = 0
        self.last_rep = 0x01
