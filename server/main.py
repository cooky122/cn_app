"""Run one two-player room and keep its dashboard in process memory."""

import argparse
import logging
import time

from server.game import Game
from server.network import ServerNetwork
from shared.protocol import SERVER_HZ, SNAPSHOT_HZ, TCP_PORT, UDP_PORT


class GameServer:
    def __init__(self, host="0.0.0.0", tcp_port=TCP_PORT, udp_port=UDP_PORT):
        self.game = Game()
        self.network = ServerNetwork(host, tcp_port, udp_port)
        self.last_snapshot = 0.0

    def process_events(self):
        for kind, session, message in self.network.poll():
            if kind == "disconnect":
                self.game.remove_player(session.player_id)
                continue
            if session.sock not in self.network.sessions or session.closing:
                continue
            if kind == "udp":
                self.game.mark_ready(session.player_id)
                self.game.set_input(session.player_id, message)
            elif not session.joined:
                self.join(session, message)
            elif message["type"] == "rematch":
                self.game.request_rematch(session.player_id)
            else:
                self.network.reject(session, "지원하지 않는 TCP 메시지입니다.")

    def join(self, session, message):
        if message["type"] != "hello":
            self.network.reject(session, "먼저 hello 메시지를 보내야 합니다.")
            return
        try:
            self.game.add_player(session.player_id, message.get("name"))
        except ValueError as error:
            self.network.reject(session, str(error))
            return
        session.joined = True
        self.network.send_tcp(session, {
            "type": "welcome", "player_id": session.player_id, "token": session.token,
            "udp_port": self.network.udp.getsockname()[1],
            "state": self.game.snapshot(), "records": self.game.dashboard(),
        })
        logging.info("Player joined: %s (%s)", message["name"], session.address[0])

    def step(self, dt):
        self.process_events()
        self.game.update(dt)
        for event in self.game.drain_events():
            self.network.broadcast_tcp(event)
            if event["type"] in ("match_start", "match_end"):
                logging.info("%s: %s", event["type"], event["state"]["result"])
        now = time.monotonic()
        if now - self.last_snapshot >= 1.0 / SNAPSHOT_HZ:
            self.network.broadcast_state(self.game.snapshot())
            self.last_snapshot = now

    def run(self):
        logging.info("TCP %s, UDP %s", self.network.tcp.getsockname(), self.network.udp.getsockname())
        previous = time.monotonic()
        try:
            while True:
                start = time.monotonic()
                self.step(min(start - previous, 0.05))
                previous = start
                time.sleep(max(0.0, 1.0 / SERVER_HZ - (time.monotonic() - start)))
        except KeyboardInterrupt:
            logging.info("Server stopped. In-memory records cleared.")
        finally:
            self.network.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="1v1 shooting game server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--tcp-port", type=int, default=TCP_PORT)
    parser.add_argument("--udp-port", type=int, default=UDP_PORT)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        server = GameServer(args.host, args.tcp_port, args.udp_port)
    except OSError as error:
        parser.exit(1, f"서버 소켓을 열 수 없습니다: {error}\n")
    server.run()


if __name__ == "__main__":
    main()
