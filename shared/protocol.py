"""Shared wire format and game settings. TCP frames use a four-byte length."""

import json
import struct


TCP_PORT = 5000
UDP_PORT = 5001
ARENA_WIDTH = 900
ARENA_HEIGHT = 560
PLAYER_RADIUS = 18
MAX_HEALTH = 100
BASE_DAMAGE = 10
BOOST_DAMAGE = 15
BOOST_DURATION = 8.0
ITEM_RESPAWN = 10.0
ROUND_DURATION = 120.0
PLAYER_SPEED = 250.0
BULLET_SPEED = 650.0
BULLET_RADIUS = 5
SHOT_INTERVAL = 0.25
SERVER_HZ = 60
SNAPSHOT_HZ = 20
INPUT_HZ = 30
INPUT_TIMEOUT = 0.4
CONNECTION_TIMEOUT = 10.0
MAX_TCP_FRAME = 64 * 1024
MAX_UDP_PACKET = 8192
MAX_PENDING_BYTES = 256 * 1024


class ProtocolError(ValueError):
    """The peer sent an invalid message."""


def encode_message(message):
    return json.dumps(
        message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def reject_constant(value):
    raise ProtocolError(f"Invalid JSON number: {value}")


def decode_message(data):
    try:
        message = json.loads(data.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ProtocolError("Invalid JSON message") from error
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("A message needs a string type")
    return message


def encode_tcp(message):
    data = encode_message(message)
    if not 0 < len(data) <= MAX_TCP_FRAME:
        raise ProtocolError("TCP message is too large")
    return struct.pack("!I", len(data)) + data


def extract_tcp_messages(buffer):
    """Keep incomplete frames in buffer, including incomplete length headers."""
    messages = []
    while len(buffer) >= 4:
        size = struct.unpack_from("!I", buffer)[0]
        if not 0 < size <= MAX_TCP_FRAME:
            raise ProtocolError("Invalid TCP frame length")
        if len(buffer) < size + 4:
            break
        messages.append(decode_message(bytes(buffer[4 : size + 4])))
        del buffer[: size + 4]
    return messages
