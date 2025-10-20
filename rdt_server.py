# rdt_server.py
import socket
import threading
import random
from utils import Packet, checksum, PACKET_SIZE, LOSS_PROBABILITY

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
            if random.random() < LOSS_PROBABILITY:
                print(f"[RECEIVER] Pacote seq_num perdido")
                continue
            pkt = Packet.decode(data)
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

