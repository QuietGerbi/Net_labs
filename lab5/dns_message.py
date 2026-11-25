import socket
import struct


def decode_hostname(raw):
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
    return struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0) + qname_wire + struct.pack("!HH", 1, 1)


def read_name(data, off):
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
    if len(data) < 12:
        return None
    _, flags, qd, an, _, _ = struct.unpack("!HHHHHH", data[:12])
    if not flags & 0x8000:
        return None
    try:
        if qd != 1:
            return None
        name, off = read_name(data, 12)
        qtype, qclass = struct.unpack("!HH", data[off:off + 4])
        off += 4
        if name != expected_name or qtype != 1 or qclass != 1:
            return None
        if flags & 0x000F:
            return []
        addresses_by_name = {}
        cname_by_name = {}
        for _ in range(an):
            owner, off = read_name(data, off)
            rtype, rclass, _ttl, rdlen = struct.unpack("!HHIH", data[off:off + 10])
            off += 10
            rdata_off = off
            rdata = data[off:off + rdlen]
            off += rdlen
            if rtype == 1 and rclass == 1 and rdlen == 4 and len(rdata) == 4:
                addresses_by_name.setdefault(owner, []).append(socket.inet_ntoa(rdata))
            elif rtype == 5 and rclass == 1:
                target, target_end = read_name(data, rdata_off)
                if target_end != rdata_off + rdlen:
                    return []
                previous = cname_by_name.setdefault(owner, target)
                if previous != target:
                    return []

        current = expected_name
        visited = set()
        while current in cname_by_name:
            if current in visited:
                return []
            visited.add(current)
            current = cname_by_name[current]
        return addresses_by_name.get(current, [])
    except (IndexError, struct.error, ValueError):
        return []
