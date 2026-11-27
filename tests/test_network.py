import socket
import struct
import time
import unittest

from client.network import ClientNetwork
from server.main import GameServer
from shared.protocol import ProtocolError, decode_message, encode_message, encode_tcp, extract_tcp_messages


class ProtocolTests(unittest.TestCase):
    def test_fragmented_and_combined_tcp_frames(self):
        expected = [{"type": "hello", "name": "플레이어"}, {"type": "rematch"}]
        wire = b"".join(encode_tcp(message) for message in expected)
        incoming = bytearray()
        received = []
        for byte in wire:
            incoming.append(byte)
            received.extend(extract_tcp_messages(incoming))
        self.assertEqual(received, expected)
        self.assertEqual(incoming, bytearray())
        self.assertEqual(extract_tcp_messages(bytearray(wire)), expected)

    def test_bad_lengths_and_nonfinite_json_are_rejected(self):
        with self.assertRaises(ProtocolError):
            extract_tcp_messages(bytearray(struct.pack("!I", 1000000)))
        with self.assertRaises(ProtocolError):
            decode_message(b'{"type":"input","aim":[NaN,0]}')


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.server = GameServer("127.0.0.1", 0, 0)
        self.port = self.server.network.tcp.getsockname()[1]
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.server.network.close()

    def connect(self, name):
        client = ClientNetwork("127.0.0.1", name, self.port)
        self.clients.append(client)
        return client

    def pump(self, frames=60, shooter=None):
        for _ in range(frames):
            for client in self.clients:
                client.poll()
                direction = (1, 0) if client is self.clients[0] else (-1, 0)
                client.send_input((0, 0), direction, client is shooter)
            self.server.step(1 / 60)
            time.sleep(0.001)
        for client in self.clients:
            client.poll()

    def test_real_tcp_udp_match_rematch_and_forfeit(self):
        alice = self.connect("Alice")
        bob = self.connect("Bob")
        self.pump()
        self.assertEqual(self.server.game.phase, "playing")
        self.assertEqual(len(self.server.network.sessions), 2)
        self.assertGreater(alice.udp_received, 0)
        self.assertGreater(bob.udp_received, 0)
        self.assertEqual(alice.state["match_id"], 1)
        self.pump(250, shooter=alice)
        self.assertEqual(self.server.game.phase, "finished")
        self.assertEqual(self.server.game.result["winner_id"], alice.player_id)
        self.assertEqual(alice.state["phase"], "finished")
        self.assertEqual(bob.state["phase"], "finished")
        self.assertEqual(alice.records[0]["wins"], 1)
        alice.request_rematch()
        bob.request_rematch()
        self.pump()
        self.assertEqual(alice.state["match_id"], 2)
        self.assertTrue(all(p["health"] == 100 for p in bob.state["players"]))
        bob.close()
        self.pump()
        self.assertEqual(self.server.game.records["Alice"]["wins"], 2)
        self.assertEqual(self.server.game.records["Bob"]["losses"], 2)
        self.assertEqual(alice.state["phase"], "waiting")

    def test_full_room_and_duplicate_name_errors_reach_client(self):
        alice = self.connect("Alice")
        self.pump()
        duplicate = self.connect("Alice")
        self.pump()
        self.assertIn("이름", duplicate.error)
        self.assertTrue(alice.connected)
        bob = self.connect("Bob")
        self.pump()
        third = self.connect("Charlie")
        self.pump()
        self.assertIn("두 명", third.error)
        self.assertTrue(bob.connected)

    def test_udp_auth_sequence_and_stale_snapshot(self):
        alice = self.connect("Alice")
        self.connect("Bob")
        self.pump()
        session = next(s for s in self.server.network.sessions.values() if s.player_id == alice.player_id)
        original_sequence = session.last_udp_sequence
        message = {"type": "input", "player_id": alice.player_id, "token": "wrong",
                   "seq": original_sequence + 10, "match_id": 1, "move": [1, 0],
                   "aim": [1, 0], "shooting": False}
        alice.udp.sendto(encode_message(message), alice.udp_address)
        self.server.step(1 / 60)
        self.assertEqual(session.last_udp_sequence, original_sequence)
        message["token"] = alice.token
        alice.udp.sendto(encode_message(message), alice.udp_address)
        self.server.step(1 / 60)
        position = self.server.game.players[alice.player_id].x
        self.assertGreater(position, 150)
        message["seq"] -= 1
        message["move"] = [-1, 0]
        alice.udp.sendto(encode_message(message), alice.udp_address)
        self.server.step(1 / 60)
        self.assertGreater(self.server.game.players[alice.player_id].x, position)
        before = alice.state
        alice.accept_state({"seq": alice.last_state_sequence, "phase": "wrong"})
        self.assertIs(alice.state, before)

    def test_fragmented_hello_over_real_tcp(self):
        raw = socket.create_connection(("127.0.0.1", self.port))
        raw.settimeout(1)
        try:
            frame = encode_tcp({"type": "hello", "name": "Fragmented"})
            raw.sendall(frame[:2])
            self.server.step(1 / 60)
            self.server.step(1 / 60)
            self.assertEqual(len(self.server.game.players), 0)
            raw.sendall(frame[2:])
            for _ in range(5):
                self.server.step(1 / 60)
                time.sleep(0.001)
            messages = extract_tcp_messages(bytearray(raw.recv(65536)))
            self.assertEqual(messages[0]["type"], "welcome")
        finally:
            raw.close()


if __name__ == "__main__":
    unittest.main()
