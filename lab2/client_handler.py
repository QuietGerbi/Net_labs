import os

import storage
from protocol import ProtocolError, read_request_header, send_response

BUFFER_SIZE = 1 << 20        
IDLE_TIMEOUT = 30.0          


def handle_client(conn, addr, uploads_dir, monitor):
    label = f"{addr[0]}:{addr[1]}"
    out = None
    path = None
    ok = False
    message = ""
    try:
        conn.settimeout(IDLE_TIMEOUT)
        name, size = read_request_header(conn)
        out, path = storage.create_upload_file(uploads_dir, name)
        print(f"[{label}] приём файла {os.path.basename(path)!r}, {size} байт", flush=True)

        stats = monitor.register(label)
        try:
            buf = bytearray(min(BUFFER_SIZE, max(size, 1)))
            view = memoryview(buf)
            received = 0
            while received < size:
                n = conn.recv_into(view, min(len(buf), size - received))
                if n == 0:
                    raise ProtocolError("клиент закрыл соединение до конца передачи")
                out.write(view[:n])
                received += n
                stats.add(n)
        finally:
            monitor.unregister(stats)

        out.close()
        out = None
        actual = os.path.getsize(path)
        if received != size or actual != size:
            raise ProtocolError(f"размер не совпал: ожидалось {size}, сохранено {actual}")
        ok, message = True, f"файл сохранён как {os.path.basename(path)}"
        print(f"[{label}] успешно: {path}", flush=True)
    except Exception as e:            
        message = f"ошибка: {e}"
        print(f"[{label}] {message}", flush=True)
    finally:
        if out is not None:
            try:
                out.close()
            except OSError:
                pass
        if not ok and path is not None:
            try:
                os.remove(path)              
            except OSError:
                pass
        try:
            send_response(conn, ok, message)
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass
