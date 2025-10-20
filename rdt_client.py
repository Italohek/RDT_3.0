# rdt_client.py
import socket
import threading
import time
from utils import Packet, checksum, WAIT_FOR_CALL_0, WAIT_FOR_CALL_1, WAIT_FOR_ACK_0, WAIT_FOR_ACK_1, ALPHA

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
        self.estimated_rtt = 0.1
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

