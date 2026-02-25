from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import boto3
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from src.utils.errors import TokenRefreshError

if TYPE_CHECKING:
    from src.config import GmailConfig

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
SSM_REFRESH_TOKEN_PATH = "/email-manager/gmail/refresh-token"


class TokenManager:
    """Manages Gmail OAuth2 tokens with SSM Parameter Store as backing store."""

    def __init__(self, config: GmailConfig):
        self._client_id = config.client_id
        self._client_secret = config.client_secret
        self._refresh_token = config.refresh_token
        self._scopes = config.scopes
        self._ssm_client = boto3.client("ssm")

    def get_credentials(self) -> Credentials:
        """Build Credentials from the refresh token and refresh the access token.

        If Google rotates the refresh token, the new one is persisted to SSM.
        """
        try:
            creds = Credentials(
                token=None,
                refresh_token=self._refresh_token,
                client_id=self._client_id,
                client_secret=self._client_secret,
                token_uri=GOOGLE_TOKEN_URI,
                scopes=self._scopes,
            )
            creds.refresh(Request())
        except Exception as e:
            raise TokenRefreshError(f"Failed to refresh Gmail OAuth token: {e}") from e

        if creds.refresh_token and creds.refresh_token != self._refresh_token:
            logger.info("Refresh token was rotated by Google, updating SSM")
            self._update_ssm_refresh_token(creds.refresh_token)
            self._refresh_token = creds.refresh_token

        return creds

    def _update_ssm_refresh_token(self, new_token: str) -> None:
        try:
            self._ssm_client.put_parameter(
                Name=SSM_REFRESH_TOKEN_PATH,
                Value=new_token,
                Type="SecureString",
                Overwrite=True,
            )
            logger.info("Updated refresh token in SSM Parameter Store")
        except Exception as e:
            logger.error(f"Failed to update refresh token in SSM: {e}")
