"""ASGI entry point: `uvicorn fxrobot.main:create_app --factory`."""

from fxrobot.internal.app import create_app

__all__ = ["create_app"]
