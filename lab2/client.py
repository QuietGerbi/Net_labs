import argparse
import os
import socket
import stat
import sys

from protocol import (MAX_FILE_SIZE, ProtocolError, read_response,
                      send_request_header)

CHUNK_SIZE = 1 << 20
CONNECT_TIMEOUT = 10.0
IO_TIMEOUT = 60.0


def send_file(path, host, port):
    with open(path, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise ProtocolError("указанный путь не является обычным файлом")
        size = st.st_size
        if size > MAX_FILE_SIZE:
            raise ProtocolError("размер файла превышает 1 ТиБ")
        name = os.path.basename(os.path.abspath(path))

        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT) as sock:
            sock.settimeout(IO_TIMEOUT)
            try:
                send_request_header(sock, name, size)

                buf = bytearray(CHUNK_SIZE)
                view = memoryview(buf)
                sent = 0
                while sent < size:
                    n = f.readinto(view[:min(CHUNK_SIZE, size - sent)])
                    if not n:
                        raise ProtocolError("файл стал короче во время отправки")
                    sock.sendall(view[:n])
                    sent += n
            except (BrokenPipeError, ConnectionResetError):
                try:
                    sock.settimeout(3.0)
                    return read_response(sock)
                except (OSError, ProtocolError):
                    raise
            return read_response(sock)


def main():
    parser = argparse.ArgumentParser(description="Клиент отправки файла")
    parser.add_argument("file", help="путь к файлу")
    parser.add_argument("host", help="DNS-имя или IP-адрес сервера")
    parser.add_argument("port", type=int, help="порт сервера")
    args = parser.parse_args()

    try:
        ok, message = send_file(args.file, args.host, args.port)
    except (OSError, ProtocolError) as e:
        print(f"Передача НЕ удалась: {e}")
        return 1
    if ok:
        print(f"Передача успешна: {message}")
        return 0
    print(f"Передача НЕ удалась: {message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())