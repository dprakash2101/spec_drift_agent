"""HTTP Request Executor Module.

Builds request configuration and delegates all non-Gemini outbound API calls
to the centralized API call component.
"""

from typing import Any

from specdrift.types import ApiKeyLocation, AuthType, HttpMethod, RecordedResponse, RequestConfig

from .api_client import ApiCallComponent


async def execute_request(
    config: RequestConfig,
    timeout: float = 30.0,
) -> RecordedResponse:
    """Execute an HTTP request via the central API call component."""
    api_client = ApiCallComponent(timeout=timeout)
    return await api_client.execute_request(config)


def build_request_config(
    method: str | HttpMethod,
    url: str,
    *,
    path_params: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    body: Any = None,
    auth_type: AuthType | str | None = None,
    auth_token: str | None = None,
    basic_username: str | None = None,
    basic_password: str | None = None,
    api_key: str | None = None,
    api_key_name: str = "X-API-Key",
    api_key_location: ApiKeyLocation | str = ApiKeyLocation.HEADER,
    client_id: str | None = None,
    client_secret: str | None = None,
    token_url: str | None = None,
    token_scope: str | None = None,
    token_audience: str | None = None,
) -> RequestConfig:
    """Helper to build a RequestConfig."""
    if isinstance(method, str):
        method = HttpMethod(method.upper())

    resolved_auth_type: AuthType | None
    if auth_type is None:
        resolved_auth_type = AuthType.BEARER if auth_token else None
    else:
        resolved_auth_type = AuthType(auth_type)

    resolved_api_key_location = (
        ApiKeyLocation(api_key_location)
        if isinstance(api_key_location, str)
        else api_key_location
    )

    return RequestConfig(
        method=method,
        url=url,
        path_params=path_params or {},
        query_params=query_params or {},
        headers=headers or {},
        body=body,
        auth_type=resolved_auth_type,
        auth_token=auth_token,
        basic_username=basic_username,
        basic_password=basic_password,
        api_key=api_key,
        api_key_name=api_key_name,
        api_key_location=resolved_api_key_location,
        client_id=client_id,
        client_secret=client_secret,
        token_url=token_url,
        token_scope=token_scope,
        token_audience=token_audience,
    )