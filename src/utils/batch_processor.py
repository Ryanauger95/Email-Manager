from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def process_in_batches(
    items: list[T],
    batch_size: int,
    processor: Callable[[list[T]], list[R]],
    max_retries: int = 2,
    retry_delay: float = 2.0,
) -> list[R]:
    """Process a list of items in batches with retry logic.

    Uses exponential backoff on failure. Designed for Lambda time constraints.
    """
    results: list[R] = []
    total_batches = (len(items) + batch_size - 1) // batch_size

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        batch_num = i // batch_size + 1

        for attempt in range(max_retries + 1):
            try:
                logger.info(
                    f"Processing batch {batch_num}/{total_batches} "
                    f"(attempt {attempt + 1}, {len(batch)} items)"
                )
                batch_results = processor(batch)
                results.extend(batch_results)
                break
            except Exception as e:
                if attempt < max_retries:
                    delay = retry_delay * (attempt + 1)
                    logger.warning(
                        f"Batch {batch_num} failed (attempt {attempt + 1}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"Batch {batch_num} failed after {max_retries + 1} attempts: {e}"
                    )
                    raise

    return results
