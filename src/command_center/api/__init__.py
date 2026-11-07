"""REST API under /v1. openapi.json is the contract for the separate mobile repo."""

from command_center.api.factory import create_app

__all__ = ["create_app"]
