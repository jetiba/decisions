"""Rules engine for the 100-squares puzzle (10x10, jumps of 3 orthogonal / 2 diagonal)."""
from __future__ import annotations

import random

from options import normalize

N = 10
DIRS = [(3, 0), (-3, 0), (0, 3), (0, -3), (2, 2), (2, -2), (-2, 2), (-2, -2)]


def onward_count(grid, r, c) -> int:
    return sum(1 for dr, dc in DIRS if 0 <= r + dr < N and 0 <= c + dc < N and not grid[r + dr][c + dc])


def onward_after(grid, a, b) -> int:
    """Empty squares reachable from (a, b) once (a, b) itself is occupied."""
    grid[a][b] = -1
    n = onward_count(grid, a, b)
    grid[a][b] = 0
    return n


class Game:
    def __init__(self, seed: int = 0, opts: dict | None = None) -> None:
        self.seed = seed
        self.opts = normalize(opts)
        self.grid = [[0] * N for _ in range(N)]
        self.path: list[tuple[int, int]] = []
        self.max_filled = 0
        self.illegal = 0
        self.undos = 0
        self.rejected: dict[tuple, set] = {}  # position (path) -> squares rejected as illegal from there
        self.failed: dict[tuple, set] = {}  # position (path) -> moves that already led to a dead end

    @property
    def filled(self) -> int:
        return len(self.path)

    @property
    def solved(self) -> bool:
        return self.filled == N * N

    def legal_moves(self) -> list[tuple[int, int]]:
        if self.solved:
            return []
        if not self.path:
            return [(r, c) for r in range(N) for c in range(N)]
        r, c = self.path[-1]
        out = []
        for dr, dc in DIRS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < N and 0 <= nc < N and not self.grid[nr][nc]:
                out.append((nr, nc))
        return out

    def move(self, r: int, c: int) -> str | None:
        """Place the next number. Returns an error string, or None on success."""
        err = self._check(r, c)
        if err:
            self.illegal += 1
            self.rejected.setdefault(tuple(self.path), set()).add((r, c))
            return err
        self.path.append((r, c))
        self.grid[r][c] = len(self.path)
        self.max_filled = max(self.max_filled, len(self.path))
        return None

    def _check(self, r: int, c: int) -> str | None:
        if not (0 <= r < N and 0 <= c < N):
            return f"({r},{c}) is outside the board (valid rows/cols are 0-{N - 1})."
        if self.grid[r][c]:
            return f"({r},{c}) is already occupied by {self.grid[r][c]}."
        if (r, c) not in self.legal_moves():
            pr, pc = self.path[-1]
            return (f"({r},{c}) is not reachable from ({pr},{pc}): "
                    "allowed jumps are 3 straight (horizontal/vertical) or 2 diagonal.")
        return None

    def undo(self) -> tuple[int, int, int] | None:
        if not self.path:
            return None
        r, c = self.path.pop()
        self.failed.setdefault(tuple(self.path), set()).add((r, c))
        n = self.grid[r][c]
        self.grid[r][c] = 0
        self.undos += 1
        return r, c, n

    def forced_step(self):
        """Plays the next step if it is the only option (one untried move, or a dead end to undo).

        Shared by both agents' tools so that every model call is a genuine choice between >=2 options.
        Returns ("move"|"undo", r, c, n) or None when the model has to decide (or the game is over).
        """
        if not self.opts["auto_forced"] or self.solved or not self.path:
            return None
        failed = self._failed_here()
        options = [m for m in self.legal_moves() if m not in failed]
        if len(options) == 1:
            self.move(*options[0])
            return ("move", *options[0], self.filled)
        if not options and len(self.path) > 1:
            r, c, n = self.undo()
            return ("undo", r, c, n)
        return None

    def _failed_here(self) -> set:
        return self.failed.get(tuple(self.path), set()) if self.opts["failed_memory"] else set()

    def _rejected_here(self) -> set:
        return self.rejected.get(tuple(self.path), set()) if self.opts["illegal_memory"] else set()

    def board_rows(self) -> list[str]:
        return [" ".join(f"{v:3d}" if v else "  ." for v in row) for row in self.grid]

    def tool_result(self, ok: bool = True, message: str = "") -> dict:
        moves = self.legal_moves()
        res = {
            "ok": ok,
            "message": message,
            "filled": self.filled,
            "solved": self.solved,
            "current_position": list(self.path[-1]) if self.path else None,
            "next_number": self.filled + 1,
            "board": self.board_rows(),
        }
        if not self.solved:
            failed, rejected = self._failed_here(), self._rejected_here()
            pool = moves if self.opts["legal_filter"] else [
                (r, c) for r in range(N) for c in range(N) if not self.grid[r][c]]
            options = [m for m in pool if m not in failed and m not in rejected]
            # Facts only, in an order shuffled per position (same for every agent playing this game seed).
            random.Random(f"{self.seed}:{self.path[-1] if self.path else None}:{len(self.path)}").shuffle(options)
            res["candidate_moves"] = [
                {"move": list(m), **({"onward_moves": onward_after(self.grid, *m)} if self.opts["onward_counts"] else {})}
                for m in options]
            if failed:
                res["already_failed_from_here"] = [list(m) for m in sorted(failed)]
            if rejected:
                res["already_rejected_from_here"] = [list(m) for m in sorted(rejected)]
        if self.opts["legal_filter"] and self.path and not moves and not self.solved:
            res["stuck"] = True
            res["hint"] = "Dead end: no legal moves. Call undo to backtrack."
        return res
