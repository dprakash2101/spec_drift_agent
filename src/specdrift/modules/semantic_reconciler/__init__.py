"""Semantic Reconciler Package - LLM-backed reasoning.

This module uses the Gemini API to reason about anomalies
and make semantic decisions about spec drift.
"""

from .llm_client import reconcile_with_llm

__all__ = ["reconcile_with_llm"]
