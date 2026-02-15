"""Integration tests for auth endpoints in the test API."""

from pathlib import Path

from fastapi.testclient import TestClient

from specdrift.modules.diff_engine import compare_response_to_schema
from specdrift.modules.openapi_parser import find_matching_endpoint, get_endpoint_schema, load_spec_from_file
from specdrift.types import HttpMethod
from test_api.main import (
    TEST_API_KEY,
    TEST_BEARER_TOKEN,
    TEST_CLIENT_ACCESS_TOKEN,
    TEST_CLIENT_ID,
    TEST_CLIENT_SECRET,
    app,
)


client = TestClient(app)
parsed_spec = load_spec_from_file(str(Path("test_api/openapi_spec.yaml")))


def _assert_matches_schema(path: str, method: HttpMethod, response_json: object, status_code: int = 200) -> None:
    schema = get_endpoint_schema(parsed_spec, path, method, status_code)
    assert schema is not None

    endpoint = find_matching_endpoint(parsed_spec, path, method)
    expected_status_codes = list(endpoint.response_schemas.keys()) if endpoint else []

    anomalies = compare_response_to_schema(
        response_body=response_json,
        response_status=status_code,
        schema=schema,
        expected_status_codes=expected_status_codes,
    )
    assert anomalies == []


def _assert_drifts_from_schema(path: str, method: HttpMethod, response_json: object, status_code: int = 200) -> None:
    schema = get_endpoint_schema(parsed_spec, path, method, status_code)
    assert schema is not None

    endpoint = find_matching_endpoint(parsed_spec, path, method)
    expected_status_codes = list(endpoint.response_schemas.keys()) if endpoint else []

    anomalies = compare_response_to_schema(
        response_body=response_json,
        response_status=status_code,
        schema=schema,
        expected_status_codes=expected_status_codes,
    )
    assert len(anomalies) > 0


def test_bearer_protected_requires_valid_token() -> None:
    no_token_response = client.get("/auth/bearer-protected")
    assert no_token_response.status_code == 401

    invalid_token_response = client.get(
        "/auth/bearer-protected",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert invalid_token_response.status_code == 401

    valid_token_response = client.get(
        "/auth/bearer-protected",
        headers={"Authorization": f"Bearer {TEST_BEARER_TOKEN}"},
    )
    assert valid_token_response.status_code == 200
    assert valid_token_response.json() == {"status": "ok", "auth_type": "bearer"}
    _assert_matches_schema("/auth/bearer-protected", HttpMethod.GET, valid_token_response.json())

    drift_response = client.get(
        "/auth/bearer-protected",
        headers={"Authorization": f"Bearer {TEST_BEARER_TOKEN}"},
        params={"drift": "true"},
    )
    assert drift_response.status_code == 200
    _assert_drifts_from_schema("/auth/bearer-protected", HttpMethod.GET, drift_response.json())


def test_apikey_protected_accepts_header_and_query() -> None:
    missing_key_response = client.get("/auth/apikey-protected")
    assert missing_key_response.status_code == 401

    header_key_response = client.get(
        "/auth/apikey-protected",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert header_key_response.status_code == 200
    assert header_key_response.json() == {"status": "ok", "auth_type": "api-key"}

    query_key_response = client.get(
        "/auth/apikey-protected",
        params={"api_key": TEST_API_KEY},
    )
    assert query_key_response.status_code == 200
    assert query_key_response.json() == {"status": "ok", "auth_type": "api-key"}
    _assert_matches_schema("/auth/apikey-protected", HttpMethod.GET, query_key_response.json())

    drift_response = client.get(
        "/auth/apikey-protected",
        headers={"X-API-Key": TEST_API_KEY},
        params={"drift": "true"},
    )
    assert drift_response.status_code == 200
    _assert_drifts_from_schema("/auth/apikey-protected", HttpMethod.GET, drift_response.json())


def test_client_credentials_token_flow() -> None:
    token_response = client.post(
        "/auth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": TEST_CLIENT_ID,
            "client_secret": TEST_CLIENT_SECRET,
        },
    )
    assert token_response.status_code == 200
    token_data = token_response.json()
    assert token_data["access_token"] == TEST_CLIENT_ACCESS_TOKEN
    assert token_data["token_type"] == "bearer"
    _assert_matches_schema("/auth/token", HttpMethod.POST, token_data)

    drift_token_response = client.post(
        "/auth/token",
        params={"drift": "true"},
        data={
            "grant_type": "client_credentials",
            "client_id": TEST_CLIENT_ID,
            "client_secret": TEST_CLIENT_SECRET,
        },
    )
    assert drift_token_response.status_code == 200
    _assert_drifts_from_schema("/auth/token", HttpMethod.POST, drift_token_response.json())

    protected_response = client.get(
        "/auth/client-credentials-protected",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )
    assert protected_response.status_code == 200
    assert protected_response.json() == {
        "status": "ok",
        "auth_type": "client-credentials",
    }
    _assert_matches_schema(
        "/auth/client-credentials-protected",
        HttpMethod.GET,
        protected_response.json(),
    )

    drift_protected_response = client.get(
        "/auth/client-credentials-protected",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
        params={"drift": "true"},
    )
    assert drift_protected_response.status_code == 200
    _assert_drifts_from_schema(
        "/auth/client-credentials-protected",
        HttpMethod.GET,
        drift_protected_response.json(),
    )


def test_client_credentials_reject_invalid_credentials() -> None:
    bad_credentials_response = client.post(
        "/auth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": TEST_CLIENT_ID,
            "client_secret": "wrong-secret",
        },
    )
    assert bad_credentials_response.status_code == 401

    bad_grant_type_response = client.post(
        "/auth/token",
        data={
            "grant_type": "password",
            "client_id": TEST_CLIENT_ID,
            "client_secret": TEST_CLIENT_SECRET,
        },
    )
    assert bad_grant_type_response.status_code == 400
