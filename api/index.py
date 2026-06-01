"""Vercel Python entrypoint.

Vercel's @vercel/python runtime detects the module-level ASGI ``app`` and serves
it. ``vercel.json`` rewrites every path to this function.
"""

from codemaru.app import app

__all__ = ["app"]
