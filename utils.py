# utils.py
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
            if chksum != checksum(payload):
                pkt.is_corrupt = True
            return pkt
        except Exception as e:
            print(f"Erro ao decodificar pacote: {e} -> {data!r}")
            return Packet(-1, -1, is_corrupt=True)

