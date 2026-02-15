"""API call component.

This module centralizes all non-Gemini outbound HTTP calls, including
request execution and OAuth2 client-credentials token generation.
"""

import base64
import time
from typing import Any

import httpx

from specdrift.types import ApiKeyLocation, AuthType, RecordedResponse, RequestConfig


class ApiCallComponent:
    """Executes HTTP requests with configured authentication."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    async def execute_request(self, config: RequestConfig) -> RecordedResponse:
        """Execute an HTTP request and return a structured recorded response."""
        url = self._build_url(config)
        headers = dict(config.headers)
        query_params = dict(config.query_params)

        start_time = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await self._apply_auth(
                config=config,
                client=client,
                headers=headers,
                query_params=query_params,
            )
            response = await client.request(
                method=config.method.value,
                url=url,
                params=query_params or None,
                headers=headers or None,
                **self._body_kwargs(config.body),
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return RecordedResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=self._parse_response_body(response),
            response_time_ms=elapsed_ms,
            request_config=config,
        )

    def _build_url(self, config: RequestConfig) -> str:
        url = config.url
        for param_name, param_value in config.path_params.items():
            url = url.replace(f"{{{param_name}}}", param_value)
        return url

    async def _apply_auth(
        self,
        *,
        config: RequestConfig,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        query_params: dict[str, str],
    ) -> None:
        auth_type = config.auth_type
        if auth_type is None and config.auth_token:
            auth_type = AuthType.BEARER

        if auth_type is None:
            return

        if auth_type == AuthType.BEARER:
            if not config.auth_token:
                raise ValueError("Bearer auth requires auth_token")
            headers["Authorization"] = f"Bearer {config.auth_token}"
            return

        if auth_type == AuthType.BASIC:
            if not config.basic_username or config.basic_password is None:
                raise ValueError("Basic auth requires basic_username and basic_password")
            raw_value = f"{config.basic_username}:{config.basic_password}".encode("utf-8")
            encoded_value = base64.b64encode(raw_value).decode("ascii")
            headers["Authorization"] = f"Basic {encoded_value}"
            return

        if auth_type == AuthType.API_KEY:
            if not config.api_key:
                raise ValueError("API key auth requires api_key")
            if config.api_key_location == ApiKeyLocation.HEADER:
                headers[config.api_key_name] = config.api_key
            else:
                query_params[config.api_key_name] = config.api_key
            return

        if auth_type == AuthType.CLIENT_CREDENTIALS:
            token = await self._fetch_access_token(config, client)
            headers["Authorization"] = f"Bearer {token}"
            return

        raise ValueError(f"Unsupported auth type: {auth_type}")

    async def _fetch_access_token(self, config: RequestConfig, client: httpx.AsyncClient) -> str:
        if not config.client_id or not config.client_secret or not config.token_url:
            raise ValueError(
                "Client credentials auth requires client_id, client_secret, and token_url"
            )

        payload: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        }
        if config.token_scope:
            payload["scope"] = config.token_scope
        if config.token_audience:
            payload["audience"] = config.token_audience

        token_response = await client.post(
            config.token_url,
            data=payload,
            headers={"Accept": "application/json"},
        )
        token_response.raise_for_status()

        token_data: Any = token_response.json()
        if not isinstance(token_data, dict):
            raise ValueError("Token endpoint returned non-object JSON")

        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("Token endpoint response missing access_token")

        return access_token

    def _body_kwargs(self, body: Any) -> dict[str, Any]:
        if body is None:
            return {}
        if isinstance(body, str):
            return {"content": body}
        return {"json": body}

    def _parse_response_body(self, response: httpx.Response) -> Any:
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                return response.json()
            except Exception:
                return response.text
        return response.text