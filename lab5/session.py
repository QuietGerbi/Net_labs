GREETING, REQUEST, RESOLVING, CONNECTING, RELAY, CLOSING = range(6)


class Session:
    __slots__ = ("csock", "rsock", "state", "hs", "c2r", "r2c", "c_eof", "r_eof",
                 "c_shut", "r_shut", "closed", "cmask", "rmask", "timer_gen",
                 "port", "addrs", "qname", "qwire", "dns_id", "attempts", "last_rep")

    def __init__(self, csock):
        self.csock = csock
        self.rsock = None
        self.state = GREETING
        self.hs = bytearray()
        self.c2r = bytearray()
        self.r2c = bytearray()
        self.c_eof = self.r_eof = False
        self.c_shut = self.r_shut = False
        self.closed = False
        self.cmask = 0
        self.rmask = 0
        self.timer_gen = 0
        self.port = 0
        self.addrs = []
        self.qname = None
        self.qwire = None
        self.dns_id = None
        self.attempts = 0
        self.last_rep = 0x01
