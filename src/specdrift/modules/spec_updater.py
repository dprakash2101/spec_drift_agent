"""Spec Updater - Apply changes to OpenAPI specifications.

Generates minimal, git-diff friendly spec updates.
"""

import copy
from typing import Any

import yaml
from jsonpath_ng import parse as parse_jsonpath  # type: ignore[import-untyped]


def apply_updates(
    original_spec: dict[str, Any],
    updated_fragment: dict[str, Any],
    json_path: str | None = None,
) -> dict[str, Any]:
    """Apply updates to an OpenAPI specification.
    
    Args:
        original_spec: The original OpenAPI spec.
        updated_fragment: The updated fragment to apply.
        json_path: Optional JSON path to apply the fragment at.
        
    Returns:
        Updated specification.
    """
    # Deep copy to avoid mutating the original
    updated_spec = copy.deepcopy(original_spec)
    
    if json_path:
        # Apply fragment at specific path
        _apply_at_path(updated_spec, json_path, updated_fragment)
    else:
        # Merge the fragment into the spec
        _deep_merge(updated_spec, updated_fragment)
    
    return updated_spec


def _apply_at_path(spec: dict[str, Any], path: str, value: Any) -> None:
    """Apply a value at a specific JSON path."""
    # Convert OpenAPI-style path to jsonpath-ng format
    # e.g., "paths./users.get.responses.200" -> "paths['/users'].get.responses['200']"
    normalized_path = _normalize_jsonpath(path)
    
    try:
        jsonpath_expr = parse_jsonpath(normalized_path)
        jsonpath_expr.update_or_create(spec, value)
    except Exception:
        # Fallback: manual path navigation
        _manual_set_path(spec, path, value)


def _normalize_jsonpath(path: str) -> str:
    """Normalize a path for jsonpath-ng."""
    # Simple normalization - handle common patterns
    parts = path.strip("$.").split(".")
    result_parts = []
    
    for part in parts:
        if part.startswith("/"):
            # Path segment like /users
            result_parts.append(f"['{part}']")
        elif part.isdigit():
            # Numeric key (status code)
            result_parts.append(f"['{part}']")
        else:
            result_parts.append(part)
    
    return "$.." + ".".join(result_parts) if result_parts else "$"


def _manual_set_path(spec: dict[str, Any], path: str, value: Any) -> None:
    """Manually set a value at a path (fallback)."""
    parts = path.strip("$.").split(".")
    current = spec
    
    for i, part in enumerate(parts[:-1]):
        if part not in current:
            current[part] = {}
        current = current[part]
    
    if parts:
        current[parts[-1]] = value


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> None:
    """Recursively merge updates into base dict."""
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)


def spec_to_yaml(spec: dict[str, Any]) -> str:
    """Convert a spec to YAML string.
    
    Args:
        spec: OpenAPI specification dict.
        
    Returns:
        YAML-formatted string.
    """
    return yaml.dump(spec, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_diff_output(
    original_spec: dict[str, Any],
    updated_spec: dict[str, Any],
) -> str:
    """Generate a human-readable diff between specs.
    
    Args:
        original_spec: Original specification.
        updated_spec: Updated specification.
        
    Returns:
        Diff-like output string.
    """
    original_yaml = spec_to_yaml(original_spec)
    updated_yaml = spec_to_yaml(updated_spec)
    
    # Simple line-by-line diff
    original_lines = original_yaml.splitlines()
    updated_lines = updated_yaml.splitlines()
    
    diff_lines = []
    
    # Very simple diff - just show added/removed
    original_set = set(original_lines)
    updated_set = set(updated_lines)
    
    for line in original_lines:
        if line not in updated_set:
            diff_lines.append(f"- {line}")
    
    for line in updated_lines:
        if line not in original_set:
            diff_lines.append(f"+ {line}")
    
    return "\n".join(diff_lines) if diff_lines else "No changes detected"


def save_spec(spec: dict[str, Any], file_path: str) -> None:
    """Save a spec to a file.
    
    Args:
        spec: OpenAPI specification.
        file_path: Path to save to.
    """
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(spec, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
