"""Pygame input, arena rendering, and an in-memory-record dashboard."""

import argparse
import math
import os
import secrets
import time

from client.network import ClientNetwork
from shared.protocol import ARENA_HEIGHT, ARENA_WIDTH, INPUT_HZ, MAX_HEALTH, PLAYER_RADIUS, TCP_PORT


WINDOW_SIZE = (1180, 720)
ARENA_ORIGIN = (20, 90)
BACKGROUND = (14, 19, 30)
PANEL = (23, 31, 46)
TEXT = (230, 237, 246)
MUTED = (145, 163, 186)
COLORS = [(74, 195, 255), (255, 112, 130)]
BOOST_COLOR = (255, 199, 75)


def draw_text(surface, text, position, font, color=TEXT):
    surface.blit(font.render(str(text), True, color), position)


def draw_arena(pygame, surface, state, own_id, fonts):
    ox, oy = ARENA_ORIGIN
    arena = pygame.Rect(ox, oy, ARENA_WIDTH, ARENA_HEIGHT)
    pygame.draw.rect(surface, PANEL, arena, border_radius=10)
    for x in range(50, ARENA_WIDTH, 50):
        pygame.draw.line(surface, (30, 40, 57), (ox + x, oy), (ox + x, oy + ARENA_HEIGHT))
    for y in range(50, ARENA_HEIGHT, 50):
        pygame.draw.line(surface, (30, 40, 57), (ox, oy + y), (ox + ARENA_WIDTH, oy + y))
    if not state:
        return
    if state["item"]:
        x, y = state["item"]
        center = (int(ox + x), int(oy + y))
        pygame.draw.circle(surface, BOOST_COLOR, center, 13)
        draw_text(surface, "+", (center[0] - 6, center[1] - 13), fonts["body"], BACKGROUND)
        draw_text(surface, "공격력 +50%", (center[0] - 43, center[1] + 18), fonts["small"], BOOST_COLOR)
    player_colors = {p["id"]: COLORS[index] for index, p in enumerate(state["players"])}
    for x, y, owner, damage in state["bullets"]:
        color = BOOST_COLOR if damage > 10 else player_colors.get(owner, TEXT)
        pygame.draw.circle(surface, color, (int(ox + x), int(oy + y)), 5)
    for player in state["players"]:
        x, y = int(ox + player["x"]), int(oy + player["y"])
        color = player_colors[player["id"]]
        if player["boost"] > 0:
            pygame.draw.circle(surface, BOOST_COLOR, (x, y), PLAYER_RADIUS + 6, 2)
        pygame.draw.circle(surface, color, (x, y), PLAYER_RADIUS)
        if player["id"] == own_id:
            pygame.draw.circle(surface, TEXT, (x, y), PLAYER_RADIUS + 2, 2)
        dx, dy = player["aim"]
        pygame.draw.line(surface, TEXT, (x, y), (int(x + dx * 29), int(y + dy * 29)), 5)
        label = f'{player["name"]}  {player["health"]} HP'
        label_surface = fonts["small"].render(label, True, TEXT)
        label_x = max(ox + 2, min(ox + ARENA_WIDTH - label_surface.get_width() - 2,
                                 x - label_surface.get_width() // 2))
        label_y = max(oy + 3, y - 49)
        surface.blit(label_surface, (label_x, label_y))
        pygame.draw.rect(surface, (55, 63, 78), (x - 25, max(oy + 24, y - 28), 50, 5))
        pygame.draw.rect(surface, color, (x - 25, max(oy + 24, y - 28),
                                         int(50 * player["health"] / MAX_HEALTH), 5))
        if player["boost"] > 0:
            draw_text(surface, f'15 DMG · {player["boost"]:.1f}s',
                      (max(ox, min(x - 45, ox + ARENA_WIDTH - 110)), min(y + 29, oy + ARENA_HEIGHT - 22)),
                      fonts["small"], BOOST_COLOR)


def draw_dashboard(pygame, surface, network, fonts, scroll):
    pygame.draw.rect(surface, PANEL, (940, 90, 220, 560), border_radius=10)
    draw_text(surface, "전적 대시보드", (956, 106), fonts["body"])
    draw_text(surface, "캐릭터", (956, 150), fonts["small"], MUTED)
    for label, x in [("승", 1055), ("무", 1090), ("패", 1125)]:
        draw_text(surface, label, (x, 150), fonts["small"], MUTED)
    for index, record in enumerate(network.records[scroll : scroll + 12]):
        y = 182 + index * 31
        name = record["name"]
        while fonts["small"].size(name)[0] > 90:
            name = name[:-2] + "…"
        draw_text(surface, name, (956, y), fonts["small"])
        for key, x in [("wins", 1055), ("draws", 1090), ("losses", 1125)]:
            draw_text(surface, record[key], (x, y), fonts["small"])
    draw_text(surface, "서버 실행 중에만 보관", (956, 587), fonts["small"], MUTED)
    draw_text(surface, "휠로 전적 스크롤", (956, 613), fonts["small"], MUTED)


def draw_overlay(pygame, surface, state, own_id, fonts):
    if not state or state["phase"] == "playing":
        return
    rect = pygame.Rect(180, 285, 580, 150)
    pygame.draw.rect(surface, (12, 18, 29), rect, border_radius=12)
    pygame.draw.rect(surface, (66, 83, 107), rect, 1, border_radius=12)
    if state["phase"] == "waiting":
        title = "상대방을 기다리는 중"
        ready = sum(player["ready"] for player in state["players"])
        detail = f"접속 {len(state['players'])}/2 · UDP 준비 {ready}/2"
        hint = "두 참가자의 TCP·UDP 연결이 준비되면 시작합니다."
    else:
        result = state["result"]
        if result["winner_id"] is None:
            title = "무승부"
        elif result["winner_id"] == own_id:
            title = "승리!"
        else:
            title = "패배"
        reasons = {"knockout": "체력 소진", "simultaneous": "동시 사망",
                   "timeout": "제한 시간 종료", "disconnect": "상대 접속 종료"}
        detail = reasons.get(result["reason"], result["reason"])
        hint = f"R 키로 재경기 요청 · 동의 {len(state['rematch_votes'])}/2"
    for text, font, y in [(title, fonts["title"], 305), (detail, fonts["body"], 351),
                          (hint, fonts["small"], 394)]:
        image = font.render(text, True, TEXT)
        surface.blit(image, (rect.centerx - image.get_width() // 2, y))


def read_input(pygame, state, own_id):
    keys = pygame.key.get_pressed()
    focused = pygame.key.get_focused()
    dx = int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(keys[pygame.K_a] or keys[pygame.K_LEFT])
    dy = int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(keys[pygame.K_w] or keys[pygame.K_UP])
    if not focused:
        dx, dy = 0, 0
    mouse_x, mouse_y = pygame.mouse.get_pos()
    aim = (1.0, 0.0)
    if state:
        own = next((p for p in state["players"] if p["id"] == own_id), None)
        if own:
            aim = (mouse_x - ARENA_ORIGIN[0] - own["x"], mouse_y - ARENA_ORIGIN[1] - own["y"])
    inside = (ARENA_ORIGIN[0] <= mouse_x < ARENA_ORIGIN[0] + ARENA_WIDTH
              and ARENA_ORIGIN[1] <= mouse_y < ARENA_ORIGIN[1] + ARENA_HEIGHT)
    shooting = bool(focused and inside and pygame.mouse.get_pressed()[0])
    return (dx, dy), aim, shooting


def run_client(pygame, network, name, host):
    pygame.display.init()
    pygame.font.init()
    surface = pygame.display.set_mode(WINDOW_SIZE)
    pygame.display.set_caption(f"1v1 Arena — {name}")
    fonts = {key: pygame.font.SysFont("malgungothic,nanumgothic,notosanscjkkr,arial", size)
             for key, size in [("title", 28), ("body", 20), ("small", 15)]}
    clock = pygame.time.Clock()
    last_input = 0.0
    scroll = 0
    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_r and network.state and network.state["phase"] == "finished":
                        network.request_rematch()
                elif event.type == pygame.MOUSEWHEEL:
                    scroll = max(0, min(max(0, len(network.records) - 12), scroll - event.y))
            network.poll()
            now = time.monotonic()
            if now - last_input >= 1.0 / INPUT_HZ:
                network.send_input(*read_input(pygame, network.state, network.player_id))
                last_input = now
            surface.fill(BACKGROUND)
            draw_text(surface, "1v1 ARENA", (20, 14), fonts["title"])
            draw_text(surface, f"{name}  |  {host}", (240, 22), fonts["body"], MUTED)
            if network.error:
                status = network.error + "  ·  ESC로 종료"
                color = COLORS[1]
            elif not network.state:
                status, color = "서버에 참가 요청 중…", MUTED
            else:
                state = network.state
                remaining = math.ceil(state["remaining"])
                status = f"ROUND {state['match_id']}  ·  {remaining // 60:02d}:{remaining % 60:02d}"
                if now - network.last_state_received > 1.0:
                    status += "  ·  상태 수신 지연"
                color = TEXT
            draw_text(surface, status, (20, 57), fonts["body"], color)
            draw_arena(pygame, surface, network.state, network.player_id, fonts)
            draw_dashboard(pygame, surface, network, fonts, scroll)
            draw_overlay(pygame, surface, network.state, network.player_id, fonts)
            draw_text(surface, "WASD / 방향키 이동   ·   마우스 조준   ·   왼쪽 버튼 발사   ·   R 재경기   ·   ESC 종료",
                      (20, 660), fonts["small"], MUTED)
            draw_text(surface, f"TCP 수신 {network.tcp_received}   |   UDP 송신 {network.udp_sent} / 수신 {network.udp_received}"
                      f"   |   오래된 UDP 무시 {network.udp_ignored}", (20, 688), fonts["small"], MUTED)
            pygame.display.flip()
            clock.tick(60)
    finally:
        network.close()
        pygame.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description="1v1 shooting game client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--tcp-port", type=int, default=TCP_PORT)
    parser.add_argument("--name", default=f"Player-{secrets.token_hex(2)}")
    args = parser.parse_args(argv)
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    try:
        import pygame
    except ModuleNotFoundError:
        parser.exit(1, "pygame을 설치하세요: python -m pip install -r requirements.txt\n")
    try:
        network = ClientNetwork(args.host, args.name, args.tcp_port)
    except OSError as error:
        parser.exit(1, f"서버에 연결할 수 없습니다: {error}\n")
    run_client(pygame, network, args.name, args.host)


if __name__ == "__main__":
    main()
