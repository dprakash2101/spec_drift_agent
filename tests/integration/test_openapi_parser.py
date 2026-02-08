"""Integration tests for the OpenAPI parser."""

import pytest
from specdrift.modules.openapi_parser import parse_spec, get_endpoint_schema, resolve_refs
from specdrift.types import HttpMethod


SAMPLE_SPEC = """
openapi: "3.0.3"
info:
  title: Test API
  version: "1.0.0"
paths:
  /users/{user_id}:
    get:
      operationId: getUser
      parameters:
        - name: user_id
          in: path
          required: true
          schema:
            type: integer
      responses:
        "200":
          description: User found
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/User"
        "404":
          description: User not found
  /items:
    get:
      operationId: listItems
      responses:
        "200":
          description: List of items
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: "#/components/schemas/Item"
components:
  schemas:
    User:
      type: object
      required:
        - id
        - name
      properties:
        id:
          type: integer
        name:
          type: string
        email:
          type: string
    Item:
      type: object
      required:
        - id
        - name
      properties:
        id:
          type: integer
        name:
          type: string
        count:
          type: integer
"""


class TestOpenAPIParser:
    """Tests for OpenAPI parsing."""

    def test_parse_spec_basic(self):
        """Parse a basic OpenAPI spec."""
        parsed = parse_spec(SAMPLE_SPEC)
        
        assert parsed.openapi_version == "3.0.3"
        assert parsed.title == "Test API"
        assert parsed.version == "1.0.0"
        assert len(parsed.endpoints) == 2

    def test_parse_spec_endpoints(self):
        """Endpoints are correctly extracted."""
        parsed = parse_spec(SAMPLE_SPEC)
        
        # Find the getUser endpoint
        user_endpoint = None
        for endpoint in parsed.endpoints:
            if endpoint.operation_id == "getUser":
                user_endpoint = endpoint
                break
        
        assert user_endpoint is not None
        assert user_endpoint.path == "/users/{user_id}"
        assert user_endpoint.method == HttpMethod.GET

    def test_ref_resolution(self):
        """$ref references are resolved."""
        parsed = parse_spec(SAMPLE_SPEC)
        
        schema = get_endpoint_schema(parsed, "/users/{user_id}", HttpMethod.GET, 200)
        
        assert schema is not None
        assert schema.get("type") == "object"
        assert "properties" in schema
        assert "id" in schema["properties"]

    def test_get_endpoint_schema_not_found(self):
        """Returns None for non-existent endpoint."""
        parsed = parse_spec(SAMPLE_SPEC)
        
        schema = get_endpoint_schema(parsed, "/nonexistent", HttpMethod.GET, 200)
        
        assert schema is None

    def test_array_response_schema(self):
        """Array response schemas are correctly parsed."""
        parsed = parse_spec(SAMPLE_SPEC)
        
        schema = get_endpoint_schema(parsed, "/items", HttpMethod.GET, 200)
        
        assert schema is not None
        assert schema.get("type") == "array"
        assert "items" in schema
        # $ref should be resolved
        assert schema["items"].get("type") == "object"
