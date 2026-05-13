"""Shared request utilities for route handlers."""

from flask import request


def get_param(name: str, default: str = "") -> str:
    """Get a parameter from any request source: form, query string, or JSON body."""
    val = request.values.get(name)
    if val:
        return val
    json_body = request.get_json(silent=True)
    if json_body:
        return json_body.get(name, default)
    return default
