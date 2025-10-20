import random
import socket
import threading
import time
import hashlib

PACKET_SIZE = 1024
TIMEOUT_INIT = 0.1
LOSS_PROBABILITY = 0.1
PAYLOAD_SIZE = 500

WAIT_FOR_CALL_0 = 0
WAIT_FOR_ACK_0 = 1
WAIT_FOR_CALL_1 = 2
WAIT_FOR_ACK_1 = 3

ALPHA = 0.125  # para EWMA RTT

def checksum(data: bytes):
    """Simples checksum MD5"""
    return hashlib.md5(data).hexdigest()

class Packet:
    def __init__(self, seq_num, ack_num, data=b'', is_ack=False, chksum='', is_corrupt=False):
        self.seq_num = seq_num
        self.ack_num = ack_num
        self.data = data
        self.is_ack = is_ack
        self.checksum = chksum
        self.is_corrupt = is_corrupt

    def encode(self):
        header = f"{self.seq_num}|{self.ack_num}|{int(self.is_ack)}|{self.checksum}|"
        return header.encode() + self.data

    @staticmethod
    def decode(data: bytes):
        try:
            decoded = data.decode(errors="replace")
            parts = decoded.split('|', 4)
            if len(parts) < 5:
                raise ValueError(f"Pacote malformado: {parts}")
            seq_num = int(parts[0])
            ack_num = int(parts[1])
            is_ack = bool(int(parts[2]))
            chksum = parts[3]
            payload = parts[4].encode() if len(parts) > 4 else b''
            pkt = Packet(seq_num, ack_num, payload, is_ack, chksum)
            # verificar integridade
            if chksum != checksum(payload):
                pkt.is_corrupt = True
            return pkt
        except Exception as e:
            print(f"Erro ao decodificar pacote: {e} -> {data!r}")
            return Packet(-1, -1, is_corrupt=True)

class RDT30Sender:
    def __init__(self, receiver_address, stop_event: threading.Event):
        self.state = WAIT_FOR_CALL_0
        self.receiver_address = receiver_address
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('localhost', 0))
        self.last_packet_sent = None
        self.timer = None
        self.lock = threading.Lock()
        self.stop_event = stop_event
        self.estimated_rtt = TIMEOUT_INIT
        self.sent_time = None
        self.sent_bytes_total = 0
        self.start_time = time.time()

    def _start_timer(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(self.estimated_rtt, self._timeout)
            self.timer.daemon = True
            self.timer.start()

    def _stop_timer(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None

    def _timeout(self):
        if self.stop_event.is_set():
            return
        print(f"[TIMEOUT] Timeout! Resending seq_num={self.last_packet_sent.seq_num}")
        self.sock.sendto(self.last_packet_sent.encode(), self.receiver_address)
        self._start_timer()

    def rdt_send(self, data: bytes):
        if self.state not in (WAIT_FOR_CALL_0, WAIT_FOR_CALL_1):
            return
        seq = 0 if self.state == WAIT_FOR_CALL_0 else 1
        pkt = Packet(seq, 0, data, False, checksum(data))
        self.last_packet_sent = pkt
        self.sent_time = time.time()
        self.sock.sendto(pkt.encode(), self.receiver_address)
        print(f"[SEND] seq_num={seq}, tamanho={len(data)} bytes")
        self._start_timer()
        self.state = WAIT_FOR_ACK_0 if seq == 0 else WAIT_FOR_ACK_1
        self.sent_bytes_total += len(data)

    def rdt_receive(self, rcv_bytes):
        pkt = Packet.decode(rcv_bytes)
        if pkt.is_corrupt or not pkt.is_ack:
            print(f"[RECEIVER] ACK corrompido ou inválido, ignorando")
            return
        rtt = time.time() - self.sent_time
        self.estimated_rtt = (1 - ALPHA) * self.estimated_rtt + ALPHA * rtt
        print(f"[ACK RECEBIDO] seq_num={pkt.ack_num}, RTT={rtt:.3f}s, Timeout={self.estimated_rtt:.3f}s")
        self._stop_timer()
        if self.state == WAIT_FOR_ACK_0 and pkt.ack_num == 0:
            self.state = WAIT_FOR_CALL_1
        elif self.state == WAIT_FOR_ACK_1 and pkt.ack_num == 1:
            self.state = WAIT_FOR_CALL_0
        else:
            print(f"[RETRANSMISSÃO] ACK incorreto, reenviando seq_num={self.last_packet_sent.seq_num}")
            self._timeout()

class RDT30Receiver:
    def __init__(self, address, stop_event: threading.Event):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(address)
        self.expected_seq = 0
        self.stop_event = stop_event

    def run(self):
        while not self.stop_event.is_set():
            try:
                data, addr = self.sock.recvfrom(PACKET_SIZE)
            except OSError:
                break
            # simular perda
            if random.random() < LOSS_PROBABILITY:
                print(f"[RECEIVER] Pacote seq_num perdido")
                continue
            pkt = Packet.decode(data)
            # simular corrupção
            if not pkt.is_corrupt and random.random() < LOSS_PROBABILITY:
                pkt.is_corrupt = True
                print(f"[RECEIVER] Pacote seq_num={pkt.seq_num} corrompido (simulado)")

            if pkt.is_corrupt or pkt.seq_num != self.expected_seq:
                last_ack = 1 - self.expected_seq
                print(f"[RECEIVER] Pacote duplicado ou fora de ordem seq_num={pkt.seq_num}, reenviando ACK {last_ack}")
                ack_pkt = Packet(-1, last_ack, b'', True, checksum(b''))
                self.sock.sendto(ack_pkt.encode(), addr)
                continue

            print(f"[RECEIVER] Pacote esperado seq_num={pkt.seq_num} recebido, enviando ACK")
            ack_pkt = Packet(-1, pkt.seq_num, b'', True, checksum(b''))
            self.sock.sendto(ack_pkt.encode(), addr)
            self.expected_seq = 1 - self.expected_seq

def main():
    stop_event = threading.Event()
    receiver_address = ('localhost', 12000)
    receiver = RDT30Receiver(receiver_address, stop_event)
    threading.Thread(target=receiver.run, daemon=True).start()

    sender = RDT30Sender(receiver_address, stop_event)
    def listen_acks():
        while not stop_event.is_set():
            try:
                pkt_bytes, _ = sender.sock.recvfrom(PACKET_SIZE)
                sender.rdt_receive(pkt_bytes)
            except OSError:
                break
    threading.Thread(target=listen_acks, daemon=True).start()

    counter = 1
    try:
        while not stop_event.is_set():
            while sender.state not in (WAIT_FOR_CALL_0, WAIT_FOR_CALL_1):
                time.sleep(0.001)
            msg = f"M{counter}".ljust(PAYLOAD_SIZE, '_').encode()
            sender.rdt_send(msg)
            counter += 1
            # calcular vazão
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

