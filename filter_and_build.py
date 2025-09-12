import requests
import io
import os
import random
import chess
import chess.pgn
import chess.polyglot
from datetime import datetime, timedelta

VARIANT = "threecheck"
MAX_PLY = 50
MAX_BOOK_WEIGHT = 2520

BOOK_OUTPUT = "threecheck_white.bin"
PGN_FILE = "combined.pgn"

ALLOWED_BOTS = [
    "ToromBot", "NecroMindX", "Roudypuff", "PINEAPPLEMASK"
]

def fetch_games(username, max_games=50):
    url = f"https://lichess.org/api/games/user/{username}"
    since = int((datetime.utcnow() - timedelta(days=30)).timestamp() * 1000)

    params = {
        "max": max_games,
        "rated": "true",
        "analysed": "false",
        "perfType": VARIANT,
        "since": since,
        "moves": "true",
        "pgnInJson": "true"
    }

    headers = {"Accept": "application/x-ndjson"}
    r = requests.get(url, params=params, headers=headers)

    games = []
    for line in r.iter_lines():
        if not line:
            continue
        data = line.decode("utf-8")
        games.append(data)
    return games


def save_pgns():
    with open(PGN_FILE, "w", encoding="utf-8") as f:
        for bot in ALLOWED_BOTS:
            games = fetch_games(bot)
            print(f"Fetched {len(games)} games for {bot}")
            for g in games:
                f.write(g + "\n")


def build_book():
    if not os.path.exists(PGN_FILE):
        print("No PGN file found.")
        return

    with open(PGN_FILE, "r", encoding="utf-8") as f:
        pgns = f.read().split("\n")

    parsed = 0
    kept = 0

    with chess.polyglot.Writer(open(BOOK_OUTPUT, "wb")) as writer:
        for pgn in pgns:
            if not pgn.strip():
                continue
            game = chess.pgn.read_game(io.StringIO(pgn))
            parsed += 1

            if game is None or game.headers.get("Variant") != VARIANT:
                continue

            if game.headers.get("Result") not in ["1-0", "0-1"]:
                continue

            if game.headers.get("White") not in ALLOWED_BOTS:
                continue

            board = game.board()
            ply = 0
            for move in game.mainline_moves():
                if ply > MAX_PLY:
                    break
                entry = chess.polyglot.Entry.from_board(
                    board, move, weight=MAX_BOOK_WEIGHT
                )
                writer.write(entry)
                board.push(move)
                ply += 1
            kept += 1

    print(f"Parsed {parsed} PGNs, kept {kept} games")
    print(f"Saved moves to book: {BOOK_OUTPUT}")


if __name__ == "__main__":
    save_pgns()
    build_book()
