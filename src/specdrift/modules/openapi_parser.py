"""OpenAPI 3.x Specification Parser.

Parses OpenAPI specs and extracts schemas for comparison.
Handles $ref resolution and schema normalization.
"""

from typing import Any

import yaml

from specdrift.types import HttpMethod, ParsedEndpoint, ParsedSpec


def parse_spec(spec: str | dict[str, Any]) -> ParsedSpec:
    """Parse an OpenAPI specification.
    
    Args:
        spec: OpenAPI spec as YAML/JSON string or already-parsed dict.
        
    Returns:
        ParsedSpec with extracted endpoints and schemas.
        
    Raises:
        ValueError: If the spec is invalid or unsupported.
    """
    # Parse if string
    if isinstance(spec, str):
        raw_spec = yaml.safe_load(spec)
    else:
        raw_spec = spec
    
    # Validate OpenAPI version
    openapi_version = raw_spec.get("openapi", "")
    if not openapi_version.startswith("3."):
        raise ValueError(f"Unsupported OpenAPI version: {openapi_version}. Only 3.x is supported.")
    
    # Extract info
    info = raw_spec.get("info", {})
    title = info.get("title", "Untitled API")
    version = info.get("version", "0.0.0")
    
    # Extract components for ref resolution
    components = raw_spec.get("components", {})
    
    # Parse endpoints
    endpoints: list[ParsedEndpoint] = []
    paths = raw_spec.get("paths", {})
    
    for path, path_item in paths.items():
        for method in ["get", "post", "put", "patch", "delete", "head", "options"]:
            if method not in path_item:
                continue
            
            operation = path_item[method]
            endpoint = _parse_operation(path, method, operation, raw_spec)
            endpoints.append(endpoint)
    
    return ParsedSpec(
        openapi_version=openapi_version,
        title=title,
        version=version,
        endpoints=endpoints,
        components=components,
        raw_spec=raw_spec,
    )


def _parse_operation(
    path: str,
    method: str,
    operation: dict[str, Any],
    full_spec: dict[str, Any],
) -> ParsedEndpoint:
    """Parse a single operation (endpoint)."""
    # Get operation ID
    operation_id = operation.get("operationId")
    
    # Parse parameters
    parameters = operation.get("parameters", [])
    
    # Parse request body schema
    request_schema = None
    request_body = operation.get("requestBody", {})
    if request_body:
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        if json_content:
            schema = json_content.get("schema", {})
            request_schema = resolve_refs(schema, full_spec)
    
    # Parse response schemas
    response_schemas: dict[int, dict[str, Any]] = {}
    responses = operation.get("responses", {})
    
    for status_code, response_def in responses.items():
        try:
            code = int(status_code)
        except ValueError:
            # Handle 'default' or other non-numeric keys
            continue
        
        content = response_def.get("content", {})
        json_content = content.get("application/json", {})
        if json_content:
            schema = json_content.get("schema", {})
            response_schemas[code] = resolve_refs(schema, full_spec)
    
    return ParsedEndpoint(
        path=path,
        method=HttpMethod(method.upper()),
        operation_id=operation_id,
        request_schema=request_schema,
        response_schemas=response_schemas,
        parameters=parameters,
    )


def resolve_refs(schema: dict[str, Any], full_spec: dict[str, Any]) -> dict[str, Any]:
    """Recursively resolve $ref references in a schema.
    
    Args:
        schema: Schema that may contain $ref references.
        full_spec: Full OpenAPI spec for resolving references.
        
    Returns:
        Schema with all references resolved.
    """
    if not isinstance(schema, dict):
        return schema
    
    # Handle $ref
    if "$ref" in schema:
        ref_path = schema["$ref"]
        resolved = _resolve_ref_path(ref_path, full_spec)
        # Merge any additional properties from the original schema
        result = resolve_refs(resolved, full_spec)
        for key, value in schema.items():
            if key != "$ref":
                result[key] = value
        return result
    
    # Recursively resolve in nested structures
    resolved_schema: dict[str, Any] = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            resolved_schema[key] = resolve_refs(value, full_spec)
        elif isinstance(value, list):
            resolved_schema[key] = [
                resolve_refs(item, full_spec) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            resolved_schema[key] = value
    
    return resolved_schema


def _resolve_ref_path(ref_path: str, full_spec: dict[str, Any]) -> dict[str, Any]:
    """Resolve a $ref path to the actual schema.
    
    Args:
        ref_path: Reference path like "#/components/schemas/User".
        full_spec: Full OpenAPI spec.
        
    Returns:
        The resolved schema.
        
    Raises:
        ValueError: If the reference cannot be resolved.
    """
    if not ref_path.startswith("#/"):
        raise ValueError(f"External references not supported: {ref_path}")
    
    # Split the path and navigate
    parts = ref_path[2:].split("/")
    current: Any = full_spec
    
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ValueError(f"Cannot resolve reference: {ref_path}")
    
    if not isinstance(current, dict):
        raise ValueError(f"Reference does not resolve to a schema: {ref_path}")
    
    return current


def get_endpoint_schema(
    parsed_spec: ParsedSpec,
    path: str,
    method: HttpMethod,
    status_code: int = 200,
) -> dict[str, Any] | None:
    """Get the response schema for a specific endpoint.
    
    Args:
        parsed_spec: Parsed OpenAPI specification.
        path: API path (e.g., "/users/123" - actual path with values).
        method: HTTP method.
        status_code: Expected status code.
        
    Returns:
        Response schema if found, None otherwise.
    """
    for endpoint in parsed_spec.endpoints:
        if endpoint.method == method and _path_matches(path, endpoint.path):
            return endpoint.response_schemas.get(status_code)
    return None


def find_matching_endpoint(
    parsed_spec: ParsedSpec,
    path: str,
    method: HttpMethod,
) -> ParsedEndpoint | None:
    """Find the endpoint definition that matches a path.
    
    Args:
        parsed_spec: Parsed OpenAPI specification.
        path: API path with actual values (e.g., "/users/123").
        method: HTTP method.
        
    Returns:
        Matching ParsedEndpoint or None.
    """
    for endpoint in parsed_spec.endpoints:
        if endpoint.method == method and _path_matches(path, endpoint.path):
            return endpoint
    return None


def _path_matches(actual_path: str, spec_path: str) -> bool:
    """Check if an actual path matches a spec path pattern.
    
    Examples:
        _path_matches("/users/123", "/users/{user_id}") -> True
        _path_matches("/users/123/status", "/users/{user_id}/status") -> True
        _path_matches("/users", "/users") -> True
        _path_matches("/items", "/users") -> False
    
    Args:
        actual_path: The actual path from the request (e.g., "/users/123").
        spec_path: The OpenAPI spec path pattern (e.g., "/users/{user_id}").
        
    Returns:
        True if the paths match.
    """
    actual_parts = actual_path.strip("/").split("/")
    spec_parts = spec_path.strip("/").split("/")
    
    # Must have same number of segments
    if len(actual_parts) != len(spec_parts):
        return False
    
    # Check each segment
    for actual_seg, spec_seg in zip(actual_parts, spec_parts):
        # If spec segment is a parameter (e.g., {user_id}), it matches anything
        if spec_seg.startswith("{") and spec_seg.endswith("}"):
            continue
        # Otherwise must match exactly
        if actual_seg != spec_seg:
            return False
    
    return True


def load_spec_from_file(file_path: str) -> ParsedSpec:
    """Load and parse an OpenAPI spec from a file.
    
    Args:
        file_path: Path to YAML or JSON spec file.
        
    Returns:
        Parsed OpenAPI specification.
    """
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
    return parse_spec(content)
