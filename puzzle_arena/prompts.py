"""Prompt text shared verbatim by both agents (the Decision-1 adapter receives it as `state`)."""
from options import DEFAULTS

STRATEGY = """Strategy guidance (Warnsdorff's rule + backtracking). It is advice, not an order: you decide each move yourself.
- Starting in a corner ((0,0), (0,9), (9,0) or (9,9)) works well.
- Prefer moves into squares that will have FEWER onward moves: hard-to-reach squares must be visited early, before they become isolated. Among equal squares, edges and corners are the harder ones to reach.
- Avoid moves that leave an empty square with no way in (0 onward moves), unless it is the last number.
- If you reach a dead end, call `undo` and try a different move from the previous position."""


def system_prompt(opts: dict | None = None) -> str:
    o = {**DEFAULTS, **(opts or {})}
    text = ("You are an agent playing a solitary board puzzle. You can only act through the `move` and `undo` tools.\n"
            "Be efficient: do not write long explanations, just keep calling tools until the puzzle is solved.")
    if o["auto_forced"]:
        text += ("\nSteps with only one possible option (a single untried move, or a dead end that must be undone) "
                 "are played for you automatically and reported in the tool result, so every decision you make is a real choice.")
    if o["strategy"]:
        text += "\n\n" + STRATEGY
    return text


def task_prompt(opts: dict | None = None) -> str:
    o = {**DEFAULTS, **(opts or {})}
    if o["legal_filter"]:
        cand = "the candidate moves (all legal)"
    else:
        cand = ("the candidate squares (every empty square; NOT all of them are reachable, check the jump rules "
                "yourself, illegal moves are rejected and counted)")
    if o["onward_counts"]:
        cand += " with their onward-move counts"
    if o["illegal_memory"] and not o["legal_filter"]:
        cand += " (squares already rejected from the current position are not listed again)"
    cand += ", in no particular order"
    stuck = " and whether you are stuck" if o["legal_filter"] else ""
    return f"""Solve the 100-squares puzzle on a 10x10 board (rows and columns are numbered 0-9).

Rules:
- The board starts empty. First call `move` with any square to place the number 1.
- Every following number (2, 3, ...) must go on an EMPTY square reached from the square holding the previous number by either:
  * a jump of exactly 3 squares horizontally or vertically, or
  * a jump of exactly 2 squares diagonally (2 rows AND 2 columns).
- You can never use an occupied square and must stay on the board.
- Goal: fill the whole board with the numbers 1 to 100.

Tools:
- move(row, col): place the next number. The result shows the board, {cand}{stuck}.
- undo(): remove the last number to backtrack from a dead end.

Plan ahead: moves into squares that will become unreachable later are traps. Keep going until the board is full."""
