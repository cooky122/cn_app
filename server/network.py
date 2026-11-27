"""Nonblocking TCP/UDP transport, adapted from the supplied socket examples."""

import logging
import secrets
import select
import socket
import time
from dataclasses import dataclass, field

from shared.protocol import (
    CONNECTION_TIMEOUT, MAX_PENDING_BYTES, MAX_UDP_PACKET, ProtocolError,
    decode_message, encode_message, encode_tcp, extract_tcp_messages,
)


@dataclass
class Session:
    sock: socket.socket
    address: tuple
    player_id: str = field(default_factory=lambda: secrets.token_hex(4))
    token: str = field(default_factory=lambda: secrets.token_hex(24))
    incoming: bytearray = field(default_factory=bytearray)
    outgoing: bytearray = field(default_factory=bytearray)
    joined: bool = False
    udp_address: tuple | None = None
    last_udp_sequence: int = -1
    last_seen: float = field(default_factory=time.monotonic)
    closing: bool = False
    close_at: float = 0.0


class ServerNetwork:
    def __init__(self, host, tcp_port, udp_port):
        self.sessions = {}
        self.events = []
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp.bind((host, tcp_port))
            self.tcp.listen(5)
            self.tcp.setblocking(False)
            self.udp.bind((host, udp_port))
            self.udp.setblocking(False)
        except OSError:
            self.close()
            raise

    def poll(self, timeout=0.0):
        reads = [self.tcp, self.udp]
        reads.extend(s.sock for s in self.sessions.values() if not s.closing)
        writes = [s.sock for s in self.sessions.values() if s.outgoing]
        readable, writable, _ = select.select(reads, writes, [], timeout)
        for sock in readable:
            if sock is self.tcp:
                self.accept_clients()
            elif sock is self.udp:
                self.receive_udp()
            else:
                session = self.sessions.get(sock)
                if session is not None:
                    self.receive_tcp(session)
        for sock in writable:
            session = self.sessions.get(sock)
            if session is not None:
                self.flush(session)
        now = time.monotonic()
        for session in list(self.sessions.values()):
            if session.closing:
                if not session.outgoing or now >= session.close_at:
                    self.disconnect(session)
            elif now - session.last_seen > CONNECTION_TIMEOUT:
                logging.info("Session timed out: %s", session.player_id)
                self.disconnect(session)
        events, self.events = self.events, []
        return events

    def accept_clients(self):
        for _ in range(8):
            try:
                sock, address = self.tcp.accept()
            except BlockingIOError:
                break
            sock.setblocking(False)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            session = Session(sock, address)
            self.sessions[sock] = session
            if len(self.sessions) > 8:
                self.reject(session, "서버가 혼잡합니다. 잠시 후 다시 접속하세요.")

    def receive_tcp(self, session):
        try:
            data = session.sock.recv(65536)
            if not data:
                self.disconnect(session)
                return
            session.last_seen = time.monotonic()
            session.incoming.extend(data)
            for message in extract_tcp_messages(session.incoming):
                self.events.append(("tcp", session, message))
        except BlockingIOError:
            return
        except (OSError, ProtocolError):
            self.disconnect(session)

    def receive_udp(self):
        for _ in range(128):
            try:
                data, address = self.udp.recvfrom(MAX_UDP_PACKET + 1)
            except (BlockingIOError, ConnectionResetError):
                break
            except OSError:
                break
            if len(data) > MAX_UDP_PACKET:
                continue
            try:
                message = decode_message(data)
            except ProtocolError:
                continue
            player_id = message.get("player_id")
            session = next((s for s in self.sessions.values()
                            if s.joined and not s.closing and s.player_id == player_id), None)
            if session is None or address[0] != session.address[0]:
                continue
            if message.get("type") != "input" or message.get("token") != session.token:
                continue
            sequence = message.get("seq")
            if type(sequence) is not int or sequence < 0 or sequence <= session.last_udp_sequence:
                continue
            session.last_udp_sequence = sequence
            session.last_seen = time.monotonic()
            session.udp_address = address
            self.events.append(("udp", session, message))

    def send_tcp(self, session, message):
        if session.sock not in self.sessions or session.closing:
            return
        frame = encode_tcp(message)
        if len(session.outgoing) + len(frame) > MAX_PENDING_BYTES:
            self.disconnect(session)
            return
        session.outgoing.extend(frame)

    def broadcast_tcp(self, message):
        for session in list(self.sessions.values()):
            if session.joined:
                self.send_tcp(session, message)

    def broadcast_state(self, state):
        packet = encode_message(state)
        if len(packet) > MAX_UDP_PACKET:
            logging.warning("Skipping oversized UDP snapshot")
            return
        for session in list(self.sessions.values()):
            if session.joined and not session.closing and session.udp_address:
                try:
                    self.udp.sendto(packet, session.udp_address)
                except OSError:
                    # The next snapshot supersedes a missing update.
                    continue

    def flush(self, session):
        try:
            count = session.sock.send(session.outgoing)
            if count == 0:
                self.disconnect(session)
                return
            del session.outgoing[:count]
        except BlockingIOError:
            return
        except OSError:
            self.disconnect(session)

    def reject(self, session, message):
        self.send_tcp(session, {"type": "error", "message": message})
        session.closing = True
        session.close_at = time.monotonic() + 1.0

    def disconnect(self, session):
        if self.sessions.pop(session.sock, None) is None:
            return
        session.sock.close()
        self.events.append(("disconnect", session, {}))

    def close(self):
        for session in list(self.sessions.values()):
            session.sock.close()
        self.sessions.clear()
        self.tcp.close()
        self.udp.close()
