"""Формирование и разбор DNS-сообщений (только A-запросы по UDP)."""

import socket
import struct


def decode_hostname(raw):
    """bytes из SOCKS-запроса -> ASCII-имя (punycode при необходимости). ValueError при ошибке."""
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        try:
            return raw.decode("utf-8").encode("idna").decode("ascii")
        except UnicodeError as e:
            raise ValueError("bad hostname") from e


def encode_name(name):
    name = name.rstrip(".")
    if not name or len(name) > 253:
        raise ValueError("bad name")
    out = bytearray()
    for label in name.split("."):
        raw = label.encode("ascii")
        if not 1 <= len(raw) <= 63:
            raise ValueError("bad label")
        out.append(len(raw))
        out += raw
    out.append(0)
    return bytes(out)


def build_query(qid, qname_wire):
    """RD=1, один вопрос, QTYPE=A, QCLASS=IN."""
    return struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0) + qname_wire + struct.pack("!HH", 1, 1)


def read_name(data, off):
    """(имя в нижнем регистре, смещение после имени в исходном потоке)."""
    labels = []
    end = None
    jumps = 0
    while True:
        length = data[off]
        if length & 0xC0 == 0xC0:
            ptr = ((length & 0x3F) << 8) | data[off + 1]
            if end is None:
                end = off + 2
            off = ptr
            jumps += 1
            if jumps > 32:
                raise ValueError("compression loop")
        elif length == 0:
            if end is None:
                end = off + 1
            break
        else:
            labels.append(data[off + 1:off + 1 + length].decode("ascii", "replace").lower())
            off += 1 + length
    return ".".join(labels), end


def parse_response(data, expected_name):
    """None — пакет игнорировать (не ответ / чужой вопрос);
    иначе список IPv4-адресов (пустой — ошибка резолвинга: RCODE != 0,
    усечённый ответ TC=1 без адресов, нет A-записей)."""
    if len(data) < 12:
        return None
    _, flags, qd, an, _, _ = struct.unpack("!HHHHHH", data[:12])
    if not flags & 0x8000:           # QR=0 — это не ответ
        return None
    try:
        if qd != 1:
            return None
        name, off = read_name(data, 12)
        off += 4
        if name != expected_name:
            return None
        if flags & 0x000F:
            return []
        addrs = []
        for _ in range(an):
            _, off = read_name(data, off)
            rtype, rclass, _ttl, rdlen = struct.unpack("!HHIH", data[off:off + 10])
            off += 10
            rdata = data[off:off + rdlen]
            off += rdlen
            if rtype == 1 and rclass == 1 and rdlen == 4 and len(rdata) == 4:
                addrs.append(socket.inet_ntoa(rdata))
        return addrs
    except (IndexError, struct.error, ValueError):
        return []
