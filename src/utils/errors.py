class EmailManagerError(Exception):
    pass


class GmailAuthError(EmailManagerError):
    pass


class GmailFetchError(EmailManagerError):
    pass


class AnthropicAPIError(EmailManagerError):
    pass


class AnthropicRateLimitError(AnthropicAPIError):
    pass


class SlackDeliveryError(EmailManagerError):
    pass


class ConfigError(EmailManagerError):
    pass


class TokenRefreshError(GmailAuthError):
    pass
