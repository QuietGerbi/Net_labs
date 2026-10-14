import argparse
import os
import socket
import threading
import time

from client_handler import handle_client, reject_client
from speed_monitor import SpeedMonitor

MAX_CLIENTS = 40 


def create_listener(port):
    if socket.has_dualstack_ipv6():
        return socket.create_server(("::", port), family=socket.AF_INET6,
                                    dualstack_ipv6=True, backlog=128)
    return socket.create_server(("0.0.0.0", port), backlog=128)


def main():
    parser = argparse.ArgumentParser(description="Сервер приёма файлов")
    parser.add_argument("port", type=int, help="порт для входящих соединений")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("порт должен быть в диапазоне 0..65535")

    uploads_dir = os.path.join(os.getcwd(), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    monitor = SpeedMonitor(interval=3.0)
    monitor.start()

    slots = threading.BoundedSemaphore(MAX_CLIENTS)

    def serve(conn, addr):
        try:
            handle_client(conn, addr, uploads_dir, monitor)
        finally:
            slots.release()                        

    with create_listener(args.port) as listener:
        print(f"Слушаю порт {listener.getsockname()[1]}, лимит клиентов: "
              f"{MAX_CLIENTS}, файлы сохраняются в {uploads_dir}", flush=True)
        try:
            while True:
                try:
                    conn, addr = listener.accept()
                except OSError as e:         
                    print(f"ошибка accept: {e}", flush=True)
                    time.sleep(0.1)
                    continue

                if slots.acquire(blocking=False):
                    try:
                        threading.Thread(target=serve, args=(conn, addr),
                                         daemon=True).start()
                    except RuntimeError as e:
                        slots.release()
                        print(f"не удалось запустить поток: {e}", flush=True)
                        conn.close()
                else:
                    msg = f"сервер занят: достигнут лимит {MAX_CLIENTS} клиентов"
                    try:
                        threading.Thread(target=reject_client,
                                         args=(conn, addr, msg), daemon=True).start()
                    except RuntimeError:
                        conn.close()
        except KeyboardInterrupt:
            print("\nОстановка сервера", flush=True)
        finally:
            monitor.stop()


if __name__ == "__main__":
    main()