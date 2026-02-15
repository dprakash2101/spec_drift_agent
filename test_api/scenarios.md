# Test API Drift Scenarios

This document describes how to test the SpecDrift agent locally.

## Quick Start

```bash
# Terminal 1: Start the test API
cd test_api
python -m uvicorn main:app --reload --port 8000

# Terminal 2: Run specdrift analysis
specdrift analyze --spec test_api/openapi_spec.yaml --endpoint http://localhost:8000 --path /users/1
```

---

## Drift Scenarios

### Scenario 1: Extra Field
**Endpoint:** `GET /users/{user_id}`

```bash
specdrift analyze -s test_api/openapi_spec.yaml -e http://localhost:8000 -p /users/1
```

**Drift:** Response includes `metadata` field not documented in spec.

---

### Scenario 2: Missing Required Field
**Endpoint:** `GET /users`

```bash
specdrift analyze -s test_api/openapi_spec.yaml -e http://localhost:8000 -p /users
```

**Drift:** `updated_at` is sometimes `null` (spec says required).

---

### Scenario 3: Enum Violation
**Endpoint:** `GET /users/{user_id}/status`

```bash
specdrift analyze -s test_api/openapi_spec.yaml -e http://localhost:8000 -p /users/1/status
```

**Drift:** Returns `"archived"` (not in enum `["active", "inactive"]`).

---

### Scenario 4: Type Mismatch
**Endpoint:** `GET /items/{item_id}`

```bash
specdrift analyze -s test_api/openapi_spec.yaml -e http://localhost:8000 -p /items/1
```

**Drift:** `count` returns as string `"42"` instead of integer.

---

### Scenario 5: Undocumented Status Code
**Endpoint:** `GET /items?category=invalid`

**Drift:** Returns 422 when category is invalid (not documented).

---

### Scenario 6: POST with Auth (Extra Field)
**Endpoint:** `POST /users`

**Drift:** Returns extra `internal_id` field not in spec.

---

### Scenario 7: PUT with Body (Extra Field)
**Endpoint:** `PUT /items/{item_id}`

**Drift:** Returns `last_modified_by` not in spec.

---

### Scenario 8: POST Search (Extra Field)
**Endpoint:** `POST /search`

**Drift:** Returns `took_ms` timing field not in spec.

---

### Scenario 9: Bearer Token Validation
**Endpoint:** `GET /auth/bearer-protected`

**Match:** Default response matches schema when valid bearer token is provided.
**Drift:** Add `?drift=true` to return a schema-deviated response.

---

### Scenario 10: API Key Validation
**Endpoint:** `GET /auth/apikey-protected`

**Match:** Default response matches schema with valid API key.
**Drift:** Add `?drift=true` to return a schema-deviated response.

---

### Scenario 11: Client Credentials Token Flow
**Endpoints:** `POST /auth/token`, `GET /auth/client-credentials-protected`

**Match:**
- `/auth/token` issues access token matching schema when `client_id=test-client-id` and `client_secret=test-client-secret`
- `/auth/client-credentials-protected` matches schema with valid bearer token
**Drift:**
- `/auth/token?drift=true` returns schema-deviated token payload
- `/auth/client-credentials-protected?drift=true` returns schema-deviated protected payload

---

## Testing with curl

```bash
# GET with headers
curl -H "X-Request-ID: test-123" http://localhost:8000/users/1

# GET with query params
curl "http://localhost:8000/items?category=electronics&min_price=10"

# POST with body and auth
curl -X POST http://localhost:8000/users \
  -H "Authorization: Bearer test-token" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test User", "email": "test@example.com"}'

# PUT with body
curl -X PUT http://localhost:8000/items/1 \
  -H "Authorization: Bearer test-token" \
  -H "Content-Type: application/json" \
  -d '{"name": "Updated Item", "count": 100}'

# POST search
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"q": "widget", "limit": 5}'

# Bearer-protected endpoint
curl -H "Authorization: Bearer test-bearer-token" http://localhost:8000/auth/bearer-protected

# Bearer-protected endpoint (drift mode)
curl -H "Authorization: Bearer test-bearer-token" "http://localhost:8000/auth/bearer-protected?drift=true"

# API key-protected endpoint (header)
curl -H "X-API-Key: test-api-key" http://localhost:8000/auth/apikey-protected

# API key-protected endpoint (query)
curl "http://localhost:8000/auth/apikey-protected?api_key=test-api-key"

# API key-protected endpoint (drift mode)
curl -H "X-API-Key: test-api-key" "http://localhost:8000/auth/apikey-protected?drift=true"

# Client credentials token generation
curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=test-client-id&client_secret=test-client-secret"

# Client credentials token generation (drift mode)
curl -X POST "http://localhost:8000/auth/token?drift=true" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=test-client-id&client_secret=test-client-secret"

# Client credentials-protected endpoint
curl -H "Authorization: Bearer test-client-access-token" http://localhost:8000/auth/client-credentials-protected

# Client credentials-protected endpoint (drift mode)
curl -H "Authorization: Bearer test-client-access-token" "http://localhost:8000/auth/client-credentials-protected?drift=true"
```

---

## Environment Setup

Set your Gemini API key for LLM reconciliation:

```bash
export GOOGLE_API_KEY="your-api-key"
```

---

## Control Endpoint

The `/health` endpoint has NO drift and should pass validation:

```bash
specdrift analyze -s test_api/openapi_spec.yaml -e http://localhost:8000 -p /health
```
