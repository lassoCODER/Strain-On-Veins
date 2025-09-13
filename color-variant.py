import requests
import io
import random
import chess
import chess.pgn
import chess.polyglot
import chess.variant

VARIANT = "horde"         
MAX_PLY = 200
MAX_BOOK_WEIGHT = 2520
MIN_RATING = 2400

BOOK_OUTPUT = "horde_white.bin"
TOURNAMENT_ID = "CydbQlns"
ALLOWED_BOTS = {"MaggiChess16", "NecroMindX", "Speedrunchessgames", "Endogenetic-Bot", "DarkOnBot", "Yuki_1324", "ToromBot"}


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
                if "@" in m.uci():
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


def fetch_tournament_games(tour_id: str, max_games: int = 5000):
    url = f"https://lichess.org/api/tournament/{tour_id}/games"
    headers = {"Accept": "application/x-chess-pgn"}
    params = {"max": max_games, "moves": True, "analysed": False, "variant": VARIANT}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return io.StringIO(resp.text)


def build_book(bin_path: str):
    book = Book()
    stream = fetch_tournament_games(TOURNAMENT_ID)
    processed = kept = 0
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        variant_tag = (game.headers.get("Variant", "") or "").lower()
        if VARIANT not in variant_tag:
            continue
        white = game.headers.get("White", "")
        black = game.headers.get("Black", "")

        if white not in ALLOWED_BOTS:
            continue

        try:
            white_elo = int(game.headers.get("WhiteElo", 0))
            black_elo = int(game.headers.get("BlackElo", 0))
        except ValueError:
            continue
        if white_elo < MIN_RATING or black_elo < MIN_RATING:
            continue

        kept += 1
        board = chess.variant.HordeBoard()
        result = game.headers.get("Result", "")
        if result == "1-0":
            winner = chess.WHITE
        elif result == "0-1":
            winner = chess.BLACK
        else:
            winner = None

        for ply, move in enumerate(game.mainline_moves()):
            if ply >= MAX_PLY:
                break
            try:
                k = key_hex(board)
                pos = book.get_position(k)
                bm = pos.get_move(move.uci())
                bm.move = move
                decay = max(1, (MAX_PLY - ply) // 5)
                if winner is not None:
                    if board.turn == winner:
                        bm.weight += 5 * decay
                    else:
                        bm.weight += 2 * decay
                else:
                    bm.weight += 3 * decay
                board.push(move)
            except Exception:
                break

        processed += 1
        if processed % 50 == 0:
            print(f"Processed {processed} games")

    print(f"Parsed {processed} PGNs, kept {kept} games")
    book.normalize()
    for pos in book.positions.values():
        for bm in pos.moves.values():
            bm.weight = min(MAX_BOOK_WEIGHT, bm.weight + random.randint(0, 2))
    book.save_polyglot(bin_path)


if __name__ == "__main__":
    build_book(BOOK_OUTPUT)
