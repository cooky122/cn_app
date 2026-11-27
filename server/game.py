"""Authoritative game rules. This module does not open sockets or draw graphics."""

import math
import random
from dataclasses import dataclass

from shared.protocol import (
    ARENA_HEIGHT, ARENA_WIDTH, BASE_DAMAGE, BOOST_DAMAGE, BOOST_DURATION,
    BULLET_RADIUS, BULLET_SPEED, INPUT_TIMEOUT, ITEM_RESPAWN, MAX_HEALTH,
    PLAYER_RADIUS, PLAYER_SPEED, ROUND_DURATION, SHOT_INTERVAL,
)


@dataclass
class Player:
    player_id: str
    name: str
    x: float = 0.0
    y: float = 0.0
    health: int = MAX_HEALTH
    ready: bool = False
    move: tuple = (0.0, 0.0)
    aim: tuple = (1.0, 0.0)
    shooting: bool = False
    last_input: float = -100.0
    next_shot: float = 0.0
    boost_until: float = 0.0


@dataclass
class Bullet:
    owner: str
    x: float
    y: float
    vx: float
    vy: float
    damage: int
    lifetime: float = 2.0


class Game:
    def __init__(self, round_duration=ROUND_DURATION):
        self.players = {}
        # Names identify characters for this server process. No disk writes occur.
        self.records = {}
        self.phase = "waiting"
        self.match_id = 0
        self.sequence = 0
        self.now = 0.0
        self.round_duration = round_duration
        self.round_end = 0.0
        self.bullets = []
        self.item = None
        self.item_spawn_at = 0.0
        self.result = None
        self.rematch_votes = set()
        self.events = []

    def add_player(self, player_id, name):
        if not isinstance(name, str):
            raise ValueError("이름은 문자열이어야 합니다.")
        name = name.strip()
        if not name or len(name) > 16 or any(not char.isprintable() for char in name):
            raise ValueError("이름은 표시 가능한 문자 1~16자로 입력하세요.")
        if len(self.players) >= 2:
            raise ValueError("이미 두 명이 접속했습니다.")
        if any(player.name == name for player in self.players.values()):
            raise ValueError("이미 접속 중인 이름입니다. 다른 이름을 사용하세요.")
        player = Player(player_id, name)
        self.players[player_id] = player
        self.records.setdefault(name, {"wins": 0, "draws": 0, "losses": 0})
        self.place_players()
        self.emit("lobby")

    def place_players(self):
        for index, player in enumerate(self.players.values()):
            player.x = 150.0 if index == 0 else ARENA_WIDTH - 150.0
            player.y = ARENA_HEIGHT / 2
            player.aim = (1.0, 0.0) if index == 0 else (-1.0, 0.0)

    def mark_ready(self, player_id):
        player = self.players[player_id]
        if player.ready:
            return
        player.ready = True
        self.emit("lobby")
        if len(self.players) == 2 and all(p.ready for p in self.players.values()):
            self.start_match()

    def start_match(self):
        self.phase = "playing"
        self.match_id += 1
        self.round_end = self.now + self.round_duration
        self.bullets.clear()
        self.item = (ARENA_WIDTH / 2, ARENA_HEIGHT / 2)
        self.result = None
        self.rematch_votes.clear()
        self.place_players()
        for player in self.players.values():
            player.health = MAX_HEALTH
            player.boost_until = 0.0
            player.next_shot = self.now
            player.move = (0.0, 0.0)
            player.shooting = False
            player.last_input = -100.0
        self.emit("match_start")

    def set_input(self, player_id, message):
        """Only validated movement and aim enter the simulation."""
        if message.get("match_id") != self.match_id:
            return
        move = message.get("move")
        aim = message.get("aim")
        if not self.valid_vector(move) or not self.valid_vector(aim):
            return
        if not isinstance(message.get("shooting"), bool):
            return
        player = self.players[player_id]
        player.move = self.unit_vector(move)
        direction = self.unit_vector(aim)
        if direction != (0.0, 0.0):
            player.aim = direction
        player.shooting = message["shooting"]
        player.last_input = self.now

    @staticmethod
    def valid_vector(value):
        return (
            isinstance(value, list) and len(value) == 2
            and all(type(part) in (int, float) and abs(part) <= 10000
                    and math.isfinite(part) for part in value)
        )

    @staticmethod
    def unit_vector(value):
        length = math.hypot(*value)
        if length == 0:
            return (0.0, 0.0)
        return (value[0] / length, value[1] / length)

    def request_rematch(self, player_id):
        if self.phase != "finished" or player_id not in self.players:
            return
        self.rematch_votes.add(player_id)
        if len(self.rematch_votes) == 2:
            self.start_match()
        else:
            self.emit("rematch")

    def remove_player(self, player_id):
        if player_id not in self.players:
            return
        if self.phase == "playing":
            winner = next(pid for pid in self.players if pid != player_id)
            self.finish_match(winner, "disconnect")
        del self.players[player_id]
        self.phase = "waiting"
        self.bullets.clear()
        self.item = None
        self.rematch_votes.clear()
        self.result = None
        self.place_players()
        for player in self.players.values():
            player.move = (0.0, 0.0)
            player.shooting = False
        self.emit("lobby")

    def update(self, dt):
        self.now += dt
        self.sequence += 1
        if self.phase != "playing":
            return
        for player in self.players.values():
            if self.now - player.last_input > INPUT_TIMEOUT:
                player.move = (0.0, 0.0)
                player.shooting = False
            player.x = max(PLAYER_RADIUS, min(
                ARENA_WIDTH - PLAYER_RADIUS, player.x + player.move[0] * PLAYER_SPEED * dt
            ))
            player.y = max(PLAYER_RADIUS, min(
                ARENA_HEIGHT - PLAYER_RADIUS, player.y + player.move[1] * PLAYER_SPEED * dt
            ))
        self.update_item()
        for player in self.players.values():
            if player.shooting and self.now >= player.next_shot:
                self.fire(player)
        self.update_bullets(dt)
        defeated = [p for p in self.players.values() if p.health <= 0]
        if len(defeated) == 2:
            self.finish_match(None, "simultaneous")
        elif defeated:
            winner = next(pid for pid in self.players if pid != defeated[0].player_id)
            self.finish_match(winner, "knockout")
        elif self.now >= self.round_end:
            self.finish_match(None, "timeout")

    def update_item(self):
        if self.item is None and self.now >= self.item_spawn_at:
            self.item = (random.uniform(230, ARENA_WIDTH - 230),
                         random.uniform(80, ARENA_HEIGHT - 80))
        if self.item is None:
            return
        for player in self.players.values():
            if math.hypot(player.x - self.item[0], player.y - self.item[1]) <= PLAYER_RADIUS + 12:
                player.boost_until = self.now + BOOST_DURATION
                self.item = None
                self.item_spawn_at = self.now + ITEM_RESPAWN
                break

    def fire(self, player):
        dx, dy = player.aim
        damage = BOOST_DAMAGE if player.boost_until > self.now else BASE_DAMAGE
        offset = PLAYER_RADIUS + BULLET_RADIUS + 2
        self.bullets.append(Bullet(
            player.player_id, player.x + dx * offset, player.y + dy * offset,
            dx * BULLET_SPEED, dy * BULLET_SPEED, damage,
        ))
        player.next_shot = self.now + SHOT_INTERVAL

    @staticmethod
    def hits_player(x1, y1, x2, y2, player):
        # A swept segment detects hits even if a bullet crosses the whole target.
        dx, dy = x2 - x1, y2 - y1
        length_squared = dx * dx + dy * dy
        fraction = 0.0
        if length_squared:
            fraction = max(0.0, min(1.0, (
                (player.x - x1) * dx + (player.y - y1) * dy
            ) / length_squared))
        distance = math.hypot(x1 + fraction * dx - player.x, y1 + fraction * dy - player.y)
        return distance <= PLAYER_RADIUS + BULLET_RADIUS

    def update_bullets(self, dt):
        remaining = []
        for bullet in self.bullets:
            x, y = bullet.x + bullet.vx * dt, bullet.y + bullet.vy * dt
            hit = False
            for player in self.players.values():
                if player.player_id == bullet.owner:
                    continue
                if self.hits_player(bullet.x, bullet.y, x, y, player):
                    player.health = max(0, player.health - bullet.damage)
                    hit = True
                    break
            bullet.x, bullet.y = x, y
            bullet.lifetime -= dt
            if not hit and bullet.lifetime > 0 and 0 <= x <= ARENA_WIDTH and 0 <= y <= ARENA_HEIGHT:
                remaining.append(bullet)
        self.bullets = remaining

    def finish_match(self, winner_id, reason):
        if self.phase != "playing":
            return
        self.phase = "finished"
        for player in self.players.values():
            if winner_id is None:
                self.records[player.name]["draws"] += 1
            elif player.player_id == winner_id:
                self.records[player.name]["wins"] += 1
            else:
                self.records[player.name]["losses"] += 1
        winner_name = self.players[winner_id].name if winner_id else None
        self.result = {"winner_id": winner_id, "winner_name": winner_name, "reason": reason}
        self.bullets.clear()
        self.emit("match_end")

    def dashboard(self):
        return [{"name": name, **record} for name, record in self.records.items()]

    def snapshot(self):
        return {
            "type": "state", "seq": self.sequence, "match_id": self.match_id,
            "phase": self.phase,
            "remaining": round(max(0.0, self.round_end - self.now), 1) if self.phase == "playing" else 0,
            "players": [{
                "id": p.player_id, "name": p.name, "x": round(p.x, 1), "y": round(p.y, 1),
                "health": p.health, "ready": p.ready,
                "aim": [round(v, 3) for v in p.aim],
                "boost": round(max(0.0, p.boost_until - self.now), 1),
            } for p in self.players.values()],
            "bullets": [[round(b.x, 1), round(b.y, 1), b.owner, b.damage] for b in self.bullets],
            "item": list(self.item) if self.item else None,
            "result": self.result, "rematch_votes": sorted(self.rematch_votes),
        }

    def emit(self, event_type):
        self.events.append({"type": event_type, "state": self.snapshot(), "records": self.dashboard()})

    def drain_events(self):
        events, self.events = self.events, []
        return events
