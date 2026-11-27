# TCP/UDP 1v1 슈팅 게임

Python 서버와 Pygame 클라이언트로 실행하는 탑다운 1대1 슈팅 게임입니다. 서버가 이동, 발사 간격, 총알 충돌, 피해량, 아이템 획득, 승패를 판정합니다. 캐릭터는 원형 도형으로 표시합니다.

**게임 규칙**

- 두 참가자가 TCP로 입장하고 UDP 통신을 준비하면 경기가 시작됩니다.
- 각 캐릭터의 시작 체력은 100이고 기본 총알 피해량은 10입니다.
- 노란 아이템에 닿으면 8초 동안 발사하는 총알 피해량이 15로 증가합니다. 총알은 발사 시점의 피해량을 유지합니다.
- 아이템은 처음에 맵 중앙에 있으며, 획득된 뒤 10초 후 맵 안의 임의 위치에 다시 생성됩니다. 아이템 효과가 남아 있을 때 재획득하면 지속 시간이 8초로 갱신됩니다.
- 상대 체력을 0으로 만들면 한 경기에 승리합니다. 발사 간격은 0.25초입니다.
- 같은 서버 업데이트에서 두 캐릭터가 모두 사망하거나 120초가 지나면 무승부입니다. 시간 초과 시 남은 체력과 관계없이 무승부로 처리합니다.
- 경기 중 접속을 종료하거나 10초 동안 통신이 없으면 해당 참가자는 패배하고 상대방은 승리합니다. 경기 시작 전 이탈에는 승패를 기록하지 않습니다.
- 경기 종료 후 두 참가자가 모두 R 키를 누르면 체력과 아이템을 초기화하고 재경기합니다.

아이템 지속 시간, 재생성 시간, 제한 시간, 동시 사망과 접속 종료 규칙은 기본 구현에서 정한 값입니다. `shared/protocol.py`의 상수에서 게임 수치와 포트를 조정할 수 있습니다.

**설치와 실행**

Python 3.12와 Pygame 2.6.1에서 검증합니다. 프로젝트 루트에서 실행하세요. 기존 `.venv`를 사용한다면 아래의 환경 생성 명령은 생략할 수 있습니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

터미널을 세 개 열어 각각 서버, 첫 번째 클라이언트, 두 번째 클라이언트를 실행합니다. 각 클라이언트는 별도 창을 엽니다.

```powershell
# 터미널 1
.\.venv\Scripts\python.exe main.py server
```

```powershell
# 터미널 2
.\.venv\Scripts\python.exe main.py client --name Alice
```

```powershell
# 터미널 3
.\.venv\Scripts\python.exe main.py client --name Bob
```

`python -m server.main`, `python -m client.main --name Alice`로도 실행할 수 있습니다. 서버는 Ctrl+C로 종료합니다.

다른 PC에서는 서버 PC와 같은 LAN에 연결한 뒤 서버의 IPv4 주소를 지정합니다. 서버 PC의 방화벽에서 Python 또는 TCP 5000과 UDP 5001 통신을 허용해야 합니다.

```powershell
.\.venv\Scripts\python.exe main.py client --host 192.168.0.10 --name Bob
```

사용 중인 포트와 충돌하면 아래처럼 바꿉니다. UDP 포트는 TCP 입장 응답을 통해 클라이언트에 전달됩니다.

```powershell
.\.venv\Scripts\python.exe main.py server --tcp-port 6000 --udp-port 6001
.\.venv\Scripts\python.exe main.py client --tcp-port 6000 --name Alice
```

| 조작 | 기능 |
|---|---|
| WASD 또는 방향키 | 이동 |
| 마우스 | 조준 |
| 마우스 왼쪽 버튼 누르기 | 연속 발사 |
| R | 경기 종료 후 재경기 동의 |
| 마우스 휠 | 전적 대시보드 스크롤 |
| ESC 또는 창 닫기 | 클라이언트 종료 |

같은 PC에서 두 창을 실행할 때는 입력할 창을 클릭해 활성화하세요. 활성화되지 않은 창은 이동·발사를 멈춥니다.

**프로토콜 동작**

제공된 TCP 예제의 `bind → listen → accept` 및 `connect → send/recv` 구조와 UDP 예제의 `sendto/recvfrom` 구조를 바탕으로 지속적인 게임 통신을 구성했습니다.

| 통신 | 데이터 | 동작 |
|---|---|---|
| TCP 5000 | 이름으로 입장, 참가 ID와 세션 토큰, 로비, 경기 시작·종료, 전적, 재경기 요청 | 연결을 유지하며 메시지를 주고받습니다. 4바이트 길이 헤더와 UTF-8 JSON을 사용합니다. 수신 버퍼에서 분할되거나 합쳐진 메시지를 복원하고 부분 전송을 처리합니다. |
| UDP 5001 | 이동 방향·조준 방향·발사 버튼 상태 | 클라이언트가 초당 30회 전송합니다. 참가 ID, 세션 토큰, 경기 ID, 순번을 포함합니다. |
| UDP 5001 | 위치·체력·총알·아이템·남은 시간 | 서버가 초당 20회 현재 상태를 전송합니다. 클라이언트는 오래된 순번을 무시합니다. |

서버는 초당 60회 게임 상태를 갱신합니다. 클라이언트는 원하는 이동과 발사 상태를 전송하고, 서버가 실제 위치와 피해량을 계산합니다. 서버는 0.4초 동안 새 입력이 없으면 해당 플레이어의 이동과 발사를 중단합니다. 다음 입력과 상태 업데이트가 이전 UDP 메시지를 대체합니다. 경기 결과와 전적은 TCP로도 전달됩니다.

화면 아래에 TCP 수신 메시지 수, UDP 송수신 수, 오래된 UDP를 무시한 횟수가 표시됩니다. 패킷 내용은 `shared/protocol.py`와 양쪽 `network.py`에서 확인할 수 있습니다.

**전적 저장**

캐릭터는 실행할 때 지정한 `--name`으로 구분합니다. 승·무·패는 서버의 메모리 딕셔너리에 저장하고 모든 참가자의 대시보드에 표시합니다. 같은 서버가 실행 중이면 클라이언트를 종료하고 같은 이름으로 다시 접속해도 전적을 이어갑니다. 동시에 접속한 참가자는 서로 다른 이름을 사용해야 합니다.

서버를 종료하면 전체 전적이 사라집니다. 현재 요구사항에는 데이터베이스 연결이나 파일 저장이 필요하지 않습니다. 향후 서버 재시작 후에도 전적을 보관하려면 JSON 파일 또는 Python 기본 모듈인 `sqlite3`로 저장할 수 있습니다. SQLite를 사용하면 별도 데이터베이스 서버 없이 파일 하나로 보관할 수 있습니다.

**파일 역할**

```text
main.py                 서버/클라이언트 실행 선택
server/main.py          서버 게임 루프와 통신 이벤트 연결
server/network.py       TCP 접속, 수신 버퍼, UDP 세션과 순번 처리
server/game.py          체력, 이동, 발사, 충돌, 아이템, 판정, 메모리 전적
client/main.py          Pygame 입력, 게임 화면, 전적 대시보드
client/network.py       TCP 입장·이벤트, UDP 입력 전송·상태 수신
shared/protocol.py      공통 상수, JSON과 TCP 길이 헤더
requirements.txt        클라이언트 의존성
tests/test_game.py      피해량·아이템·무승부·재경기·전적 검증
tests/test_network.py   실제 로컬 TCP/UDP 통신과 메시지 복원 검증
```

**개발 검증과 Agentic AI 활용**

Codex를 사용해 제공된 네 가지 소켓 예제를 읽고, 통신과 게임 판정의 역할을 나눠 구현하고, 테스트를 실행하며 실패 원인을 수정했습니다. 테스트는 기본 모듈 `unittest`로 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

검증에는 일반 총알 10회 명중 후 승패 확정, 강화 피해량 15와 효과 만료, 아이템 재생성, 동시 사망과 시간 초과 무승부, 중복 재경기 요청, 이탈 패배와 이름 재접속, TCP 메시지 분할·결합, 실제 두 클라이언트의 TCP/UDP 경기, 잘못된 UDP 토큰과 오래된 순번 거부가 포함됩니다.

소켓 API와 TCP 메시지 경계 처리는 [Python Socket Programming HOWTO](https://docs.python.org/3/howto/sockets.html)를, 창의 매 프레임 입력 처리는 [Pygame 이벤트 문서](https://www.pygame.org/docs/ref/event.html)를 참고했습니다.
