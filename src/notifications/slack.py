from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.utils.errors import SlackDeliveryError

if TYPE_CHECKING:
    from src.config import SlackConfig

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


class SlackNotifier:
    """Sends DMs to a user via Slack Bot Token API.

    Uses conversations.open to get a DM channel with the user,
    then chat.postMessage to send Block Kit messages as DMs.
    """

    def __init__(self, config: SlackConfig):
        self._bot_token = config.bot_token
        self._user_id = config.user_id
        self._dm_channel_id: Optional[str] = None

    def send(self, payload: dict) -> bool:
        """Send a Block Kit message as a DM to the configured user."""
        channel_id = self._get_dm_channel()
        return self._post_message(channel_id, payload)

    def _get_dm_channel(self) -> str:
        """Open or retrieve the DM channel with the target user."""
        if self._dm_channel_id:
            return self._dm_channel_id

        response = self._slack_api_call(
            "conversations.open",
            {"users": self._user_id},
        )

        if not response.get("ok"):
            error = response.get("error", "unknown")
            raise SlackDeliveryError(
                f"Failed to open DM channel with user {self._user_id}: {error}"
            )

        self._dm_channel_id = response["channel"]["id"]
        logger.info(f"Opened DM channel: {self._dm_channel_id}")
        return self._dm_channel_id

    def _post_message(self, channel_id: str, payload: dict) -> bool:
        """Post a Block Kit message to a channel, splitting if over 50 blocks."""
        blocks = payload.get("blocks", [])

        if len(blocks) <= 50:
            return self._send_single_message(channel_id, blocks)

        # Split into chunks of 48 blocks (leaving room for continuation header)
        chunks = [blocks[i : i + 48] for i in range(0, len(blocks), 48)]
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk.insert(
                    0,
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"_...continued ({i + 1}/{len(chunks)})_",
                            }
                        ],
                    },
                )
            self._send_single_message(channel_id, chunk)

        return True

    def _send_single_message(self, channel_id: str, blocks: list[dict]) -> bool:
        """Send a single message with blocks."""
        body = {
            "channel": channel_id,
            "blocks": blocks,
            "unfurl_links": False,
            "unfurl_media": False,
        }

        response = self._slack_api_call("chat.postMessage", body)

        if not response.get("ok"):
            error = response.get("error", "unknown")
            raise SlackDeliveryError(f"chat.postMessage failed: {error}")

        logger.info("Slack DM sent successfully")
        return True

    def _slack_api_call(self, method: str, body: dict) -> dict:
        """Make an authenticated call to the Slack Web API."""
        url = f"{SLACK_API_BASE}/{method}"
        data = json.dumps(body).encode("utf-8")

        req = Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {self._bot_token}",
            },
        )

        try:
            response = urlopen(req, timeout=15)
            result = json.loads(response.read().decode("utf-8"))
            return result
        except URLError as e:
            raise SlackDeliveryError(f"Slack API call to {method} failed: {e}") from e
        except json.JSONDecodeError as e:
            raise SlackDeliveryError(
                f"Invalid JSON response from Slack {method}: {e}"
            ) from e
