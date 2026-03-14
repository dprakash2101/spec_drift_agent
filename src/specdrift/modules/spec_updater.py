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


# ============================================================================
# Spec Update — Backup + Apply Sections + Write
# ============================================================================


def update_spec_file(
    spec_path: str,
    spec_update_result: "SpecUpdateResult",
    *,
    create_backup: bool = True,
    skip_non_backward_compatible: bool = True,
) -> tuple[bool, str | None, str]:
    """Apply LLM-generated section updates to the spec file on disk.

    Creates a timestamped backup, applies each backward-compatible section
    update, writes the result, and returns a diff.

    Args:
        spec_path: Path to the OpenAPI YAML/JSON file.
        spec_update_result: Structured output from the Spec Writer LLM.
        create_backup: Whether to create a backup before overwriting.
        skip_non_backward_compatible: Skip sections that aren't backward
            compatible (default True for safety).

    Returns:
        Tuple of ``(was_updated, backup_path_or_None, diff_string)``.
    """
    import logging
    from datetime import datetime as dt

    from specdrift.types import SpecUpdateResult  # noqa: F811 (local re-import for type)

    logger = logging.getLogger("specdrift.spec_updater")

    # Load the original spec
    with open(spec_path, encoding="utf-8") as f:
        original_yaml_text = f.read()
    original_spec = yaml.safe_load(original_yaml_text)
    updated_spec = copy.deepcopy(original_spec)

    # Create backup
    backup_path: str | None = None
    if create_backup:
        timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{spec_path}.bak.{timestamp}"
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(original_yaml_text)
        logger.info(f"   Backup created: {backup_path}")

    # Apply each section update
    applied_count = 0
    skipped_sections: list[str] = []

    for section in spec_update_result.updated_sections:
        # Gate: backward compatibility
        if skip_non_backward_compatible and not section.backward_compatible:
            logger.warning(
                f"   Skipping non-backward-compatible section: {section.section_path}"
            )
            skipped_sections.append(section.section_path)
            continue

        # Parse the updated YAML for this section
        try:
            section_data = yaml.safe_load(section.updated_yaml)
        except yaml.YAMLError as e:
            logger.warning(
                f"   Skipping section {section.section_path}: invalid YAML — {e}"
            )
            skipped_sections.append(section.section_path)
            continue

        # Navigate to the section path and replace
        if _set_section(updated_spec, section.section_path, section_data):
            logger.info(f"   ✅ Applied: {section.section_path} — {section.change_summary}")
            applied_count += 1
        else:
            logger.warning(f"   Could not navigate to: {section.section_path}")
            skipped_sections.append(section.section_path)

    if applied_count == 0:
        logger.info("   No sections applied — spec file unchanged")
        return False, backup_path, "No changes applied"

    # Write updated spec
    save_spec(updated_spec, spec_path)
    logger.info(f"   Spec written: {spec_path} ({applied_count} sections updated)")

    # Generate diff
    diff = generate_diff_output(original_spec, updated_spec)

    return True, backup_path, diff


def _set_section(spec: dict[str, Any], dot_path: str, value: Any) -> bool:
    """Navigate a dot-notation path and set the value.

    Handles paths like ``components.schemas.User`` or
    ``paths./users/{user_id}.get.responses.200``.

    Returns True if the section was found and updated.
    """
    parts = _split_dot_path(dot_path)
    current = spec

    for part in parts[:-1]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False

    if isinstance(current, dict):
        current[parts[-1]] = value
        return True
    return False


def _split_dot_path(dot_path: str) -> list[str]:
    """Split a dot-notation path, handling paths that start with ``/``.

    Examples::

        "components.schemas.User"  → ["components", "schemas", "User"]
        "paths./users/{user_id}.get" → ["paths", "/users/{user_id}", "get"]
        "paths./users.get.responses.200" → ["paths", "/users", "get", "responses", "200"]
    """
    parts: list[str] = []
    current = ""

    for char in dot_path:
        if char == ".":
            # Don't split on dots that follow a "/" (path segment start)
            if current and not current.startswith("/"):
                parts.append(current)
                current = ""
            elif current.startswith("/"):
                # We're in a path segment like /users/{user_id}
                # Check if the next segment starts with / too
                parts.append(current)
                current = ""
            else:
                parts.append(current)
                current = ""
        elif char == "/" and not current:
            # Starting a new path segment
            current = "/"
        else:
            current += char

    if current:
        parts.append(current)

    return [p for p in parts if p]

