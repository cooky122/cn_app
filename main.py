"""Launch either side with python main.py server/client [options]."""

import argparse


def main():
    parser = argparse.ArgumentParser(description="TCP/UDP 1v1 shooting game")
    parser.add_argument("mode", choices=("server", "client"))
    args, remaining = parser.parse_known_args()
    if args.mode == "server":
        from server.main import main as run
    else:
        from client.main import main as run
    run(remaining)


if __name__ == "__main__":
    main()
