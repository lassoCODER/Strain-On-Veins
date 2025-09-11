import requests
import io
import random
import chess
import chess.pgn
import chess.polyglot

VARIANT = "standard"
MAX_PLY = 100
MAX_BOOK_WEIGHT = 2520

BOOK_OUTPUT = "std_black.bin"

ALLOWED_BOTS = {
    "ToromBot", "Speedrunchessgames", "NecroMindX", "MaggiChess16", "NNUE_Drift",
    "PINEAPPLEMASK", "Strain-On-Veins", "Yuki_1324", "Endogenetic-Bot",
    "Exogenetic-Bot", "BOT_Stockfish13", "Classic_Bot-V2",
}
RATING_CUTOFF = 3100


def fetch_user_pgn(username: str) -> str:
    url = f"https://lichess.org/api/games/user/{username}"
    params = {
        "perfType": "classical,blitz,bullet,rapid",
        "clocks": "false",
        "evals": "false",
        "opening": "false",
        "rated": "true",
        "pgnInJson": "false",
        "analysed": "false",
        "variant": VARIANT,
    }
    headers = {"Accept": "application/x-chess-pgn"}
    print(f"Downloading PGN for {username}...")
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.text


class BookMove:
    def __init__(self):
        self.weight = 0
        self.move: chess.Move | None = None


class BookPosition:
    def __init__(self):
        self.moves: dict[str, BookMove] = {}

    def get_move(self, uci: str) -> BookMove:
        return self.moves.setdefault(uci, BookMove())


class Book:
    def __init__(self):
        self.positions: dict[str, BookPosition] = {}

    def get_position(self, key_hex: str) -> BookPosition:
        return self.positions.setdefault(key_hex, BookPosition())

    def normalize(self):
        for pos in self.positions.values():
            s = sum(bm.weight for bm in pos.moves.values())
            if s <= 0:
                continue
            for bm in pos.moves.values():
                bm.weight = max(1, int(bm.weight / s * MAX_BOOK_WEIGHT))

    def save_polyglot(self, path: str):
        entries = []
        for key_hex, pos in self.positions.items():
            zbytes = bytes.fromhex(key_hex)
            for bm in pos.moves.values():
                if bm.weight <= 0 or bm.move is None:
                    continue
                m = bm.move
                if "@" in m.uci():  # skip drops
                    continue
                mi = m.to_square + (m.from_square << 6)
                if m.promotion:
                    mi += ((m.promotion - 1) << 12)
                mbytes = mi.to_bytes(2, "big")
                wbytes = min(MAX_BOOK_WEIGHT, bm.weight).to_bytes(2, "big")
                lbytes = (0).to_bytes(4, "big")
                entries.append(zbytes + mbytes + wbytes + lbytes)
        entries.sort(key=lambda e: (e[:8], e[10:12]))
        with open(path, "wb") as f:
            for e in entries:
                f.write(e)
        print(f"Saved {len(entries)} moves to book: {path}")


def key_hex(board: chess.Board) -> str:
    return f"{chess.polyglot.zobrist_hash(board):016x}"


def build_book_from_pgn(pgn_data: str, bin_path: str):
    print("Building book from BLACK wins + draws...")
    book = Book()
    stream = io.StringIO(pgn_data)

    processed = 0
    kept = 0
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break

        result = game.headers.get("Result", "")
        black = game.headers.get("Black", "")
        brating = int(game.headers.get("BlackElo", "0"))

        if result not in ("0-1", "1/2-1/2"):  # ✅ only black wins & draws
            continue
        if black not in ALLOWED_BOTS:
            continue
        if brating < RATING_CUTOFF:
            continue

        kept += 1
        board = chess.Board()

        for ply, move in enumerate(game.mainline_moves()):
            if ply >= MAX_PLY:
                break
            try:
                k = key_hex(board)
                pos = book.get_position(k)
                bm = pos.get_move(move.uci())
                bm.move = move

                decay = max(1, (MAX_PLY - ply) // 5)

                if board.turn == chess.BLACK:
                    bm.weight += 6 * decay  # ✅ Black’s moves boosted
                else:
                    bm.weight += 1

                board.push(move)
            except Exception:
                break

        processed += 1
        if processed % 100 == 0:
            print(f"Processed {processed} games")

    print(f"Parsed {processed} PGNs, kept {kept} black wins/draws")
    book.normalize()
    for pos in book.positions.values():
        for bm in pos.moves.values():
            bm.weight = min(MAX_BOOK_WEIGHT, bm.weight + random.randint(0, 3))

    book.save_polyglot(bin_path)


def main():
    combined_pgn = ""
    for username in ALLOWED_BOTS:
        combined_pgn += fetch_user_pgn(username) + "\n\n"

    build_book_from_pgn(combined_pgn, BOOK_OUTPUT)
    print("Done.")


if __name__ == "__main__":
    main()
