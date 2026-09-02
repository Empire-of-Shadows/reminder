# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""Performance-timing helpers built on the engine logger.

A context manager / decorator pair plus a small timing context, all of which log operation
start/end and elapsed seconds. Elapsed time is measured with ``time.perf_counter()`` (monotonic),
not wall-clock, so NTP/DST adjustments can't skew or negate a duration.

Completion logging is level-split (2026-08-30, owner readability standard): a routine
completion is DEBUG detail, because at INFO the "Operation 'X' completed" lines were the
single largest source of noise in a production tail (a scheduler tick alone printed three per
guild every cycle, and every message added a completed-in-0.0002s line). An operation slower
than ``slow_threshold`` seconds still logs at INFO - a genuinely slow operation is signal, and
losing it to DEBUG would hide the one timing line worth seeing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import contextmanager
from functools import wraps

# Completions at or above this many seconds log at INFO; everything below is
# DEBUG. Callers with a different idea of "slow" pass their own threshold.
SLOW_OPERATION_SECONDS = 1.0


class PerformanceLogger:
    """Context manager for measuring execution time of a named operation."""

    def __init__(
        self,
        logger: logging.Logger,
        operation_name: str,
        slow_threshold: float = SLOW_OPERATION_SECONDS,
    ):
        self.logger = logger
        self.operation_name = operation_name
        self.slow_threshold = slow_threshold
        self._start: float | None = None

    def __enter__(self):
        self._start = time.perf_counter()
        self.logger.debug(f"Starting operation: {self.operation_name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.perf_counter() - (self._start or time.perf_counter())
        if duration >= self.slow_threshold:
            self.logger.info(
                f"⏱️ Slow operation '{self.operation_name}' completed in {duration:.4f}s"
            )
        else:
            self.logger.debug(
                f"Operation '{self.operation_name}' completed in {duration:.4f}s"
            )


def log_performance(operation_name: str = None, slow_threshold: float = SLOW_OPERATION_SECONDS):
    """Decorator to log function execution time for both sync and async functions."""

    def decorator(func):
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                logger = logging.getLogger(func.__module__)
                op_name = operation_name or func.__name__
                with PerformanceLogger(logger, op_name, slow_threshold=slow_threshold):
                    return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(func.__module__)
            op_name = operation_name or func.__name__
            with PerformanceLogger(logger, op_name, slow_threshold=slow_threshold):
                return func(*args, **kwargs)

        return wrapper

    return decorator


@contextmanager
def log_context(logger: logging.Logger, operation_name: str, level: int = logging.INFO):
    """Context manager for logging operation start and end with elapsed time."""
    logger.log(level, f"Starting: {operation_name}")
    start = time.perf_counter()
    try:
        yield
        duration = time.perf_counter() - start
        logger.log(level, f"Completed: {operation_name} (took {duration:.4f}s)")
    except Exception as e:
        duration = time.perf_counter() - start
        logger.error(f"Failed: {operation_name} after {duration:.4f}s - {e}")
        raise
