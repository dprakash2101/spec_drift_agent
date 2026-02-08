"""HTTP Request Executor Module.

Executes HTTP requests against API endpoints and records responses.
No retry logic - explicit per requirements.
"""

import time
from typing import Any

import httpx

from specdrift.types import HttpMethod, RecordedResponse, RequestConfig


async def execute_request(
    config: RequestConfig,
    timeout: float = 30.0,
) -> RecordedResponse:
    """Execute an HTTP request and record the response.
    
    Args:
        config: Request configuration including URL, method, headers, etc.
        timeout: Request timeout in seconds.
        
    Returns:
        RecordedResponse with status, headers, body, and timing.
        
    Raises:
        httpx.HTTPError: If the request fails at the network level.
    """
    # Build the full URL with path params
    url = config.url
    for param_name, param_value in config.path_params.items():
        url = url.replace(f"{{{param_name}}}", param_value)
    
    # Build headers
    headers = dict(config.headers)
    if config.auth_token:
        headers["Authorization"] = f"Bearer {config.auth_token}"
    
    # Execute request with timing
    start_time = time.perf_counter()
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            method=config.method.value,
            url=url,
            params=config.query_params or None,
            headers=headers or None,
            json=config.body if config.body is not None else None,
        )
    
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    
    # Parse response body
    body: Any
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = response.json()
        except Exception:
            body = response.text
    else:
        body = response.text
    
    # Convert headers to dict
    response_headers = dict(response.headers)
    
    return RecordedResponse(
        status_code=response.status_code,
        headers=response_headers,
        body=body,
        response_time_ms=elapsed_ms,
        request_config=config,
    )


def build_request_config(
    method: str | HttpMethod,
    url: str,
    *,
    path_params: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    body: Any = None,
    auth_token: str | None = None,
) -> RequestConfig:
    """Helper to build a RequestConfig.
    
    Args:
        method: HTTP method as string or HttpMethod enum.
        url: Base URL (can contain {param} placeholders).
        path_params: Path parameter substitutions.
        query_params: Query string parameters.
        headers: Request headers.
        body: Request body (will be JSON-encoded).
        auth_token: Bearer token for Authorization header.
        
    Returns:
        Configured RequestConfig instance.
    """
    if isinstance(method, str):
        method = HttpMethod(method.upper())
    
    return RequestConfig(
        method=method,
        url=url,
        path_params=path_params or {},
        query_params=query_params or {},
        headers=headers or {},
        body=body,
        auth_token=auth_token,
    )
