from __future__ import annotations

import logging
from typing import Any, Optional

from src.config import load_config
from src.logging_config import setup_logging
from src.pipeline import PipelineRunner

logger = logging.getLogger(__name__)


def run(event: dict[str, Any], context: Optional[Any] = None) -> dict[str, Any]:
    """AWS Lambda entry point.

    Triggered by EventBridge schedule (every hour).
    Creates a PipelineRunner and executes the state machine.
    """
    request_id = None
    if context and hasattr(context, "aws_request_id"):
        request_id = context.aws_request_id

    # Load config first so we can use logging settings
    config = load_config()

    setup_logging(
        level=config.logging.level,
        log_format=config.logging.format,
        request_id=request_id,
    )

    logger.info(
        "Email Manager Lambda invoked",
        extra={"request_id": request_id},
    )

    runner = PipelineRunner(config=config, request_id=request_id)
    response = runner.run()

    logger.info(
        f"Pipeline finished: status={response.status}, "
        f"processed={response.emails_processed}, "
        f"slack_sent={response.slack_sent}",
    )

    return response.model_dump()
