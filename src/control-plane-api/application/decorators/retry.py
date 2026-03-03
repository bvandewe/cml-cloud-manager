"""Retry decorator for handling transient failures and optimistic concurrency conflicts."""

import asyncio
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from neuroglia.data.exceptions import OptimisticConcurrencyException

log = logging.getLogger(__name__)

T = TypeVar("T")


def retry_on_concurrency_conflict(
    max_attempts: int = 3,
    initial_delay: float = 0.1,
    backoff_factor: float = 2.0,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Retry decorator for handling optimistic concurrency conflicts.

    When an OptimisticConcurrencyException occurs, the operation is retried
    with exponential backoff. This allows the aggregate to be reloaded with
    the latest version and the operation to be reattempted.

    Args:
        max_attempts: Maximum number of retry attempts (including initial attempt)
        initial_delay: Initial delay in seconds before first retry
        backoff_factor: Multiplier for delay between retries

    Returns:
        Decorated async function with retry logic

    Example:
        @retry_on_concurrency_conflict(max_attempts=3, initial_delay=0.1)
        async def update_worker(self, worker_id: str) -> OperationResult:
            worker = await self.repository.get_by_id_async(worker_id)
            worker.update_something()
            await self.repository.update_async(worker)
            return self.ok()
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            delay = initial_delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except OptimisticConcurrencyException as e:
                    last_exception = e

                    if attempt == max_attempts:
                        log.warning(
                            "Optimistic concurrency conflict - max retries (%d) exhausted for %s: %s",
                            max_attempts,
                            func.__name__,
                            str(e),
                        )
                        raise

                    log.info(
                        "Optimistic concurrency conflict (attempt %d/%d) for %s - retrying in %.2fs: %s",
                        attempt,
                        max_attempts,
                        func.__name__,
                        delay,
                        str(e),
                    )

                    await asyncio.sleep(delay)
                    delay *= backoff_factor

            # Should never reach here, but satisfy type checker
            raise last_exception  # type: ignore

        return wrapper

    return decorator
