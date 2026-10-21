import argparse
import os
import selectors
import socket
import threading
import time


from client_handler import handle_client, reject_client
from speed_monitor import SpeedMonitor
from storage import check_uploads_dir

MAX_CLIENTS = 50
MAX_REJECTS = 8                 
DROP_REPORT_INTERVAL = 5.0
SHUTDOWN_JOIN_TIMEOUT = 5.0
BACKLOG = 128


def create_listeners(port):
    if socket.has_dualstack_ipv6():
        try:
            return [socket.create_server(("::", port), family=socket.AF_INET6,
                                         dualstack_ipv6=True, backlog=BACKLOG)]
        except OSError:
            pass         

    listeners, errors = [], []
    if socket.has_ipv6:
        try:
            listeners.append(socket.create_server(
                ("::", port), family=socket.AF_INET6, backlog=BACKLOG))
        except OSError as e:
            errors.append(("IPv6", e))
    try:
        listeners.append(socket.create_server(("0.0.0.0", port), backlog=BACKLOG))
    except OSError as e:
        errors.append(("IPv4", e))

    if not listeners:
        raise errors[-1][1]
    for proto, e in errors:
        print(f"предупреждение: {proto} недоступен: {e}", flush=True)
    return listeners


def shutdown_clients(active, active_lock):
    with active_lock:
        items = list(active.items())
    for thread, conn in items:
        try:
            conn.shutdown(socket.SHUT_RDWR)  
        except OSError:
            pass                           
    deadline = time.monotonic() + SHUTDOWN_JOIN_TIMEOUT
    for thread, _ in items:
        thread.join(max(0.0, deadline - time.monotonic()))


def main():
    parser = argparse.ArgumentParser(description="Сервер приёма файлов")
    parser.add_argument("port", type=int, help="порт для входящих соединений")
    args = parser.parse_args()
    if not 0 < args.port <= 65535:
        parser.error("порт должен быть в диапазоне 1..65535")

    uploads_dir = os.path.join(os.getcwd(), "uploads")
    try:
        os.makedirs(uploads_dir, exist_ok=True)
        check_uploads_dir(uploads_dir)
    except OSError as e:
        raise SystemExit(f"каталог uploads недопустим: {e}")

    monitor = SpeedMonitor(interval=3.0)
    monitor.start()

    slots = threading.BoundedSemaphore(MAX_CLIENTS)
    reject_slots = threading.BoundedSemaphore(MAX_REJECTS)
    active = {}                 
    active_lock = threading.Lock()

    def forget_current():
        with active_lock:
            active.pop(threading.current_thread(), None)

    def serve(conn, addr):
        try:
            handle_client(conn, addr, uploads_dir, monitor)
        finally:
            forget_current()
            slots.release()

    def reject(conn, addr, msg):
        try:
            reject_client(conn, addr, msg)
        finally:
            forget_current()
            reject_slots.release()

    def spawn(target, conn, *args_):
        t = threading.Thread(target=target, args=(conn, *args_))
        with active_lock:
            active[t] = conn
        try:
            t.start()
        except RuntimeError:
            with active_lock:
                active.pop(t, None)
            raise

    dropped = 0
    last_drop_report = time.monotonic()

    try:
        listeners = create_listeners(args.port)
    except OSError as e:
        monitor.stop()
        raise SystemExit(f"не удалось открыть порт {args.port}: {e}")

    sel = selectors.DefaultSelector()
    for lst in listeners:
        lst.setblocking(False)
        sel.register(lst, selectors.EVENT_READ)

    try:
        print(f"Слушаю порт {listeners[0].getsockname()[1]}, лимит клиентов: "
              f"{MAX_CLIENTS}, файлы сохраняются в {uploads_dir}", flush=True)
        while True:
            for key, _ in sel.select(timeout=1.0):
                try:
                    conn, addr = key.fileobj.accept()
                except (BlockingIOError, InterruptedError):
                    continue
                except OSError as e:
                    print(f"ошибка accept: {e}", flush=True)
                    time.sleep(0.1)
                    continue

                conn.setblocking(True)

                if slots.acquire(blocking=False):
                    try:
                        spawn(serve, conn, addr)
                    except RuntimeError as e:
                        slots.release()
                        print(f"не удалось запустить поток: {e}", flush=True)
                        conn.close()
                    continue

                msg = f"сервер занят: достигнут лимит {MAX_CLIENTS} клиентов"
                if reject_slots.acquire(blocking=False):
                    try:
                        spawn(reject, conn, addr, msg)
                        continue
                    except RuntimeError:
                        reject_slots.release()
                conn.close()
                dropped += 1
                now = time.monotonic()
                if now - last_drop_report >= DROP_REPORT_INTERVAL:
                    print(f"перегрузка: сброшено соединений без ответа: "
                          f"{dropped}", flush=True)
                    dropped = 0
                    last_drop_report = now
    except KeyboardInterrupt:
        print("\nОстановка сервера", flush=True)
    finally:
        sel.close()
        for lst in listeners:
            lst.close()
        shutdown_clients(active, active_lock)  
        if dropped:
            print(f"перегрузка: сброшено соединений без ответа: {dropped}",
                  flush=True)
        monitor.stop()
        monitor.join(1.0)


if __name__ == "__main__":
    main()