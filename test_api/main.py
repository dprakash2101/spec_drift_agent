"""FastAPI Test API with Intentional Spec Drift.

This API is designed for dogfooding the SpecDrift agent.
It intentionally returns responses that drift from the OpenAPI spec.
"""

from datetime import datetime
from typing import Any, Annotated
import random

from fastapi import FastAPI, HTTPException, Query, Header, Body, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

app = FastAPI(
    title="SpecDrift Test API",
    description="An API with intentional spec drift for testing",
    version="1.0.0",
)

# Security scheme
security = HTTPBearer(auto_error=False)


# =============================================================================
# Request/Response Models
# =============================================================================


class CreateUserRequest(BaseModel):
    name: str
    email: str
    role: str = "user"


class UpdateItemRequest(BaseModel):
    name: str | None = None
    count: int | None = None
    price: float | None = None


class SearchQuery(BaseModel):
    q: str
    limit: int = 10
    offset: int = 0


# =============================================================================
# Drift Scenario 1: Extra Field (metadata not in spec)
# =============================================================================


@app.get("/users/{user_id}")
async def get_user(
    user_id: int,
    include_metadata: bool = Query(False, description="Include extra metadata"),
    x_request_id: str | None = Header(None, description="Request tracking ID"),
) -> dict[str, Any]:
    """Get a user by ID.
    
    DRIFT: Response includes 'metadata' field not documented in spec.
    """
    response = {
        "id": user_id,
        "name": "John Doe",
        "email": "john@example.com",
        "status": "active",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    
    # DRIFT: Extra undocumented field (always included despite query param)
    response["metadata"] = {
        "last_login": datetime.now().isoformat(),
        "login_count": 42,
        "request_id": x_request_id,
    }
    
    return response


# =============================================================================
# Drift Scenario 2: Missing Required Field (updated_at sometimes null)
# =============================================================================


@app.get("/users")
async def list_users(
    include_inactive: bool = Query(False),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    x_api_version: str | None = Header(None, description="API version header"),
) -> list[dict[str, Any]]:
    """List all users.
    
    DRIFT: updated_at is sometimes null even though spec says required.
    """
    users = [
        {
            "id": 1,
            "name": "Alice",
            "email": "alice@example.com",
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        },
        {
            "id": 2,
            "name": "Bob",
            "email": "bob@example.com",
            "status": "inactive" if include_inactive else "active",
            "created_at": datetime.now().isoformat(),
            # DRIFT: updated_at is null (spec says required)
            "updated_at": None,
        },
    ]
    return users[offset : offset + limit]


# =============================================================================
# Drift Scenario 3: Enum Violation (status returns "archived")
# =============================================================================


@app.get("/users/{user_id}/status")
async def get_user_status(user_id: int) -> dict[str, Any]:
    """Get user status.
    
    DRIFT: Returns "archived" which is not in the spec's enum.
    """
    return {
        "id": user_id,
        # DRIFT: "archived" is not in the spec enum ["active", "inactive"]
        "status": "archived",
        "reason": "Account deactivated by admin",
    }


# =============================================================================
# Drift Scenario 4: Type Mismatch (count returns string instead of int)
# =============================================================================


@app.get("/items/{item_id}")
async def get_item(
    item_id: int,
    currency: str = Query("USD", description="Currency for price"),
) -> dict[str, Any]:
    """Get an item by ID.
    
    DRIFT: count returns as string "42" instead of integer 42.
    """
    return {
        "id": item_id,
        "name": "Widget",
        # DRIFT: String instead of integer
        "count": "42",
        "price": 19.99,
        "currency": currency,
    }


# =============================================================================
# Drift Scenario 5: Undocumented Status Code (422)
# =============================================================================


@app.get("/items")
async def list_items(
    category: str = Query(None),
    min_price: float = Query(None, ge=0),
    max_price: float = Query(None, ge=0),
) -> list[dict[str, Any]]:
    """List items, optionally filtered by category.
    
    DRIFT: Returns 422 when category is invalid (not documented).
    """
    valid_categories = ["electronics", "clothing", "food"]
    
    if category and category not in valid_categories:
        # DRIFT: 422 status code not documented in spec
        raise HTTPException(
            status_code=422,
            detail={
                "error": f"Invalid category: {category}",
                "valid_categories": valid_categories,
            },
        )
    
    return [
        {"id": 1, "name": "Laptop", "count": 10, "price": 999.99},
        {"id": 2, "name": "Phone", "count": 25, "price": 599.99},
    ]


# =============================================================================
# Scenario 6: POST with Body (Auth Required)
# =============================================================================


@app.post("/users")
async def create_user(
    user: CreateUserRequest = Body(...),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_request_id: str | None = Header(None),
) -> dict[str, Any]:
    """Create a new user.
    
    Requires Bearer auth token.
    DRIFT: Returns extra 'internal_id' field not in spec.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization required")
    
    return {
        "id": 123,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "status": "active",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        # DRIFT: Extra field not in spec
        "internal_id": "usr_abc123xyz",
    }


# =============================================================================
# Scenario 7: PUT with Body and Path Param
# =============================================================================


@app.put("/items/{item_id}")
async def update_item(
    item_id: int,
    item: UpdateItemRequest = Body(...),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    """Update an item.
    
    DRIFT: Returns 'last_modified_by' not in spec.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization required")
    
    return {
        "id": item_id,
        "name": item.name or "Updated Widget",
        "count": item.count or 10,
        "price": item.price or 29.99,
        # DRIFT: Extra field
        "last_modified_by": "admin@example.com",
        "updated_at": datetime.now().isoformat(),
    }


# =============================================================================
# Scenario 8: POST Search with Complex Body
# =============================================================================


@app.post("/search")
async def search(
    query: SearchQuery = Body(...),
    x_search_context: str | None = Header(None, description="Search context"),
) -> dict[str, Any]:
    """Search across resources.
    
    DRIFT: Returns 'took_ms' timing field not in spec.
    """
    return {
        "query": query.q,
        "results": [
            {"type": "user", "id": 1, "name": "John Doe"},
            {"type": "item", "id": 42, "name": "Widget"},
        ],
        "total": 2,
        "limit": query.limit,
        "offset": query.offset,
        # DRIFT: Extra timing field
        "took_ms": 42,
    }


# =============================================================================
# Control Endpoint (No Drift)
# =============================================================================


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint (no drift, matches spec exactly)."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
