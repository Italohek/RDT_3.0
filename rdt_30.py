import random
import socket
import threading
import time

PACKET_SIZE = 1024
LOSS_PROBABILITY = 0.1
ALPHA = 0.125  # EWMA smoothing factor para RTT
BETA = 0.25    # Desvio RTT

WAIT_FOR_CALL_0 = 0
WAIT_FOR_ACK_0 = 1
WAIT_FOR_CALL_1 = 2
WAIT_FOR_ACK_1 = 3

class Packet:
    def __init__(self, seq_num, ack_num, data=b'', is_ack=False, is_corrupt=False):
        self.seq_num = seq_num
        self.ack_num = ack_num
        self.data = data
        self.is_ack = is_ack
        self.is_corrupt = is_corrupt
        self.checksum = self.calc_checksum()

    def calc_checksum(self):
        return sum(self.data) % 256  # checksum simples

    def encode(self):
        header = f"{self.seq_num}|{self.ack_num}|{int(self.is_ack)}|{int(self.is_corrupt)}|{self.checksum}|"
        return header.encode() + self.data

    @staticmethod
    def decode(data: bytes):
        try:
            decoded = data.decode(errors="replace")
            parts = decoded.split('|')
            if len(parts) < 6:
                raise ValueError(f"Pacote malformado: {parts}")
            seq_num = int(parts[0])
            ack_num = int(parts[1])
            is_ack = bool(int(parts[2]))
            is_corrupt = bool(int(parts[3]))
            checksum = int(parts[4])
            message = '|'.join(parts[5:]).encode()
            pkt = Packet(seq_num, ack_num, message, is_ack, is_corrupt)
            # valida checksum
            if pkt.calc_checksum() != checksum:
                pkt.is_corrupt = True
            return pkt
        except Exception as e:
            print(f"Erro ao decodificar pacote: {e} -> {data!r}")
            return Packet(seq_num=-1, ack_num=-1, is_corrupt=True)

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
        self.estimated_rtt = 0.5
        self.dev_rtt = 0.25
        self.timeout_interval = self.estimated_rtt + 4 * self.dev_rtt
        self.send_time = None
        self.total_bytes_sent = 0
        self.start_time = time.time()

    def _start_timer(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(self.timeout_interval, self._timeout)
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
        print(f"[TIMEOUT] Reenviando pacote seq_num={self.last_packet_sent.seq_num}")
        self.sock.sendto(self.last_packet_sent.encode(), self.receiver_address)
        self._start_timer()

    def rdt_send(self, data: bytes):
        seq = 0 if self.state == WAIT_FOR_CALL_0 else 1
        print(f"[SEND] Enviando pacote seq_num={seq}, tamanho={len(data)} bytes")
        pkt = Packet(seq_num=seq, ack_num=0, data=data)
        self.last_packet_sent = pkt
        self.sock.sendto(pkt.encode(), self.receiver_address)
        self.send_time = time.time()
        self._start_timer()

        self.state = WAIT_FOR_ACK_0 if seq == 0 else WAIT_FOR_ACK_1
        self.total_bytes_sent += len(data)

    def rdt_receive(self, rcv_pkt_bytes):
        rcv_pkt = Packet.decode(rcv_pkt_bytes)
        if rcv_pkt.is_corrupt or not rcv_pkt.is_ack:
            print(f"[RECV] ACK corrompido ou inválido, ignorando")
            return

        seq = 0 if self.state == WAIT_FOR_ACK_0 else 1
        if rcv_pkt.ack_num == seq:
            rtt_sample = time.time() - self.send_time
            # Atualiza RTT e timeout (EWMA)
            self.estimated_rtt = (1 - ALPHA) * self.estimated_rtt + ALPHA * rtt_sample
            self.dev_rtt = (1 - BETA) * self.dev_rtt + BETA * abs(rtt_sample - self.estimated_rtt)
            self.timeout_interval = self.estimated_rtt + 4 * self.dev_rtt

            print(f"[ACK RECEBIDO] seq_num={seq}, RTT={rtt_sample:.3f}s, Timeout={self.timeout_interval:.3f}s")
            self._stop_timer()
            self.state = WAIT_FOR_CALL_1 if seq == 0 else WAIT_FOR_CALL_0
        else:
            print(f"[RECV] ACK incorreto, reenviando seq_num={self.last_packet_sent.seq_num}")
            self._timeout()

    def print_throughput(self):
        elapsed = time.time() - self.start_time
        rate_kbps = (self.total_bytes_sent * 8) / elapsed / 1000
        print(f"[THROUGHPUT] Vazão até agora: {rate_kbps:.2f} kbps")

class RDT30Receiver:
    def __init__(self, address, stop_event: threading.Event):
        self.address = address
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(address)
        self.expected_seq_num = 0
        self.stop_event = stop_event

    def run(self):
        print(f"[RECEIVER] Rodando em {self.address}")
        while not self.stop_event.is_set():
            try:
                packet_bytes, sender_addr = self.sock.recvfrom(PACKET_SIZE)
            except OSError:
                break

            # simula perda
            if random.random() < LOSS_PROBABILITY:
                print("[RECEIVER] Pacote perdido")
                continue

            pkt = Packet.decode(packet_bytes)

            # simula corrupção
            is_corrupt = pkt.is_corrupt or random.random() < LOSS_PROBABILITY
            if is_corrupt:
                print(f"[RECEIVER] Pacote seq_num={pkt.seq_num} corrompido, descartando")
                continue

            if pkt.seq_num == self.expected_seq_num:
                print(f"[RECEIVER] Pacote esperado seq_num={pkt.seq_num} recebido, enviando ACK")
                ack_pkt = Packet(seq_num=-1, ack_num=pkt.seq_num, is_ack=True)
                self.sock.sendto(ack_pkt.encode(), sender_addr)
                self.expected_seq_num = 1 - self.expected_seq_num
            else:
                # duplicado
                last_ack = 1 - self.expected_seq_num
                print(f"[RECEIVER] Pacote duplicado ou fora de ordem seq_num={pkt.seq_num}, reenviando ACK {last_ack}")
                ack_pkt = Packet(seq_num=-1, ack_num=last_ack, is_ack=True)
                self.sock.sendto(ack_pkt.encode(), sender_addr)

def main():
    stop_event = threading.Event()
    receiver_addr = ('localhost', 12000)

    receiver = RDT30Receiver(receiver_addr, stop_event)
    threading.Thread(target=receiver.run, daemon=True).start()

    sender = RDT30Sender(receiver_addr, stop_event)

    def listen_acks():
        while not stop_event.is_set():
            try:
                pkt_bytes, _ = sender.sock.recvfrom(PACKET_SIZE)
                sender.rdt_receive(pkt_bytes)
                sender.print_throughput()
            except OSError:
                break

    threading.Thread(target=listen_acks, daemon=True).start()

    counter = 1
    try:
        while True:
            msg = f"Mensagem {counter}".encode()
            sender.rdt_send(msg)
            counter += 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Ctrl+C pressionado, encerrando...")
        stop_event.set()
        sender._stop_timer()
        sender.sock.close()
        receiver.sock.close()

if __name__ == "__main__":
    main()
