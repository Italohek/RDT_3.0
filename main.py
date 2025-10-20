# main.py
import threading
import time
from utils import PAYLOAD_SIZE
from rdt_client import RDT30Sender
from rdt_server import RDT30Receiver

def main():
    stop_event = threading.Event()
    receiver_address = ('localhost', 12000)
    receiver = RDT30Receiver(receiver_address, stop_event)
    threading.Thread(target=receiver.run, daemon=True).start()

    sender = RDT30Sender(receiver_address, stop_event)

    def listen_acks():
        while not stop_event.is_set():
            try:
                pkt_bytes, _ = sender.sock.recvfrom(1024)
                sender.rdt_receive(pkt_bytes)
            except OSError:
                break
    threading.Thread(target=listen_acks, daemon=True).start()

    counter = 1
    try:
        while not stop_event.is_set():
            while sender.state not in (0, 2):
                time.sleep(0.001)
            msg = f"M{counter}".ljust(PAYLOAD_SIZE, '_').encode()
            sender.rdt_send(msg)
            counter += 1
            elapsed = time.time() - sender.start_time
            kbps = (sender.sent_bytes_total*8/1000)/elapsed
            print(f"[THROUGHPUT] Vazão até agora: {kbps:.2f} kbps")
    except KeyboardInterrupt:
        print("Ctrl+C pressionado, encerrando...")
        stop_event.set()
    finally:
        sender.sock.close()
        receiver.sock.close()

if __name__ == "__main__":
    main()

