"""Client transport. Poll from the Pygame loop without blocking the window."""

import socket
import time

from shared.protocol import (
    CONNECTION_TIMEOUT, MAX_PENDING_BYTES, MAX_UDP_PACKET, TCP_PORT,
    ProtocolError, decode_message, encode_message, encode_tcp, extract_tcp_messages,
)


class ClientNetwork:
    def __init__(self, host, name, tcp_port=TCP_PORT):
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.connected = False
        self.player_id = None
        self.token = None
        self.udp_address = None
        self.incoming = bytearray()
        self.outgoing = bytearray()
        self.state = None
        self.records = []
        self.input_sequence = 0
        self.last_state_sequence = -1
        self.last_received = time.monotonic()
        self.last_state_received = self.last_received
        self.error = None
        self.tcp_received = 0
        self.udp_sent = 0
        self.udp_received = 0
        self.udp_ignored = 0
        try:
            self.tcp.settimeout(3.0)
            self.tcp.connect((host, tcp_port))
            self.tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.tcp.setblocking(False)
            self.udp.bind(("0.0.0.0", 0))
            self.udp.setblocking(False)
        except OSError:
            self.close()
            raise
        self.connected = True
        self.send_tcp({"type": "hello", "name": name})

    def send_tcp(self, message):
        if not self.connected:
            return
        frame = encode_tcp(message)
        if len(self.outgoing) + len(frame) > MAX_PENDING_BYTES:
            self.fail("TCP 전송 대기열이 가득 찼습니다.")
            return
        self.outgoing.extend(frame)

    def poll(self):
        if not self.connected:
            return
        try:
            if self.outgoing:
                try:
                    count = self.tcp.send(self.outgoing)
                    if count == 0:
                        self.fail("서버와의 연결이 종료되었습니다.")
                        return
                    del self.outgoing[:count]
                except BlockingIOError:
                    pass
            self.receive_tcp()
            if self.connected:
                self.receive_udp()
            if time.monotonic() - self.last_received > CONNECTION_TIMEOUT:
                self.fail("서버 응답이 없습니다. 서버와 UDP 연결을 확인하세요.")
        except (OSError, ProtocolError) as error:
            self.fail(f"통신 오류: {error}")

    def receive_tcp(self):
        for _ in range(8):
            try:
                data = self.tcp.recv(65536)
            except BlockingIOError:
                break
            if not data:
                self.fail("서버와의 연결이 종료되었습니다.")
                return
            self.last_received = time.monotonic()
            self.incoming.extend(data)
            for message in extract_tcp_messages(self.incoming):
                self.tcp_received += 1
                if message["type"] == "error":
                    self.fail(message["message"])
                    return
                if message["type"] == "welcome":
                    self.player_id = message["player_id"]
                    self.token = message["token"]
                    self.udp_address = (self.tcp.getpeername()[0], message["udp_port"])
                if "records" in message:
                    self.records = message["records"]
                if "state" in message:
                    self.accept_state(message["state"], reliable=True)

    def receive_udp(self):
        for _ in range(128):
            try:
                packet, address = self.udp.recvfrom(MAX_UDP_PACKET + 1)
            except (BlockingIOError, ConnectionResetError):
                break
            if address != self.udp_address or len(packet) > MAX_UDP_PACKET:
                continue
            try:
                message = decode_message(packet)
            except ProtocolError:
                continue
            if message["type"] != "state":
                continue
            self.udp_received += 1
            self.last_received = time.monotonic()
            self.accept_state(message)

    def accept_state(self, state, reliable=False):
        sequence = state.get("seq")
        if type(sequence) is not int:
            return
        # TCP events may share a tick. Delayed UDP must never undo those events.
        if sequence < self.last_state_sequence or (not reliable and sequence == self.last_state_sequence):
            if not reliable:
                self.udp_ignored += 1
            return
        self.last_state_sequence = sequence
        self.state = state
        self.last_state_received = time.monotonic()

    def send_input(self, move, aim, shooting):
        if not self.connected or self.player_id is None:
            return
        self.input_sequence += 1
        packet = encode_message({
            "type": "input", "player_id": self.player_id, "token": self.token,
            "seq": self.input_sequence,
            "match_id": self.state["match_id"] if self.state else 0,
            "move": list(move), "aim": list(aim), "shooting": shooting,
        })
        try:
            self.udp.sendto(packet, self.udp_address)
            self.udp_sent += 1
        except BlockingIOError:
            pass
        except OSError as error:
            self.fail(f"UDP 전송 오류: {error}")

    def request_rematch(self):
        self.send_tcp({"type": "rematch"})

    def fail(self, message):
        if self.error is None:
            self.error = message
        self.close()

    def close(self):
        self.connected = False
        self.tcp.close()
        self.udp.close()
