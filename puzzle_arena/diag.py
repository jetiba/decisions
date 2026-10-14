"""Event-loop lag monitor: shows whether the shared asyncio loop was ever blocked during a game."""
import asyncio
import time

_samples: list[tuple[float, float]] = []  # (wall time, lag in ms)
_task: asyncio.Task | None = None
INTERVAL = 0.05


async def _run() -> None:
    while True:
        t = time.perf_counter()
        await asyncio.sleep(INTERVAL)
        _samples.append((time.time(), max(0.0, (time.perf_counter() - t - INTERVAL) * 1000)))
        if len(_samples) > 200_000:
            del _samples[:100_000]


def start() -> None:
    global _task
    if _task is None:
        _task = asyncio.get_running_loop().create_task(_run())


def window(t_start: float, t_end: float) -> dict:
    lags = sorted(lag for ts, lag in _samples if t_start <= ts <= t_end)
    if not lags:
        return {"loop_lag_ms_mean": None, "loop_lag_ms_p99": None, "loop_lag_ms_max": None}
    return {"loop_lag_ms_mean": round(sum(lags) / len(lags), 2),
            "loop_lag_ms_p99": round(lags[int(0.99 * (len(lags) - 1))], 1),
            "loop_lag_ms_max": round(lags[-1], 1)}
