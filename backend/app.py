"""FastAPI backend for the blank environment.

This provides the stateful counter service that the environment tools interact with.
"""

import logging
import sys

from fastapi import FastAPI

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s | %(name)s | %(message)s",
)

app = FastAPI(title="Blank Environment Backend")

# In-memory state
_count = 0


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/act")
def act():
    """Increment the counter."""
    global _count
    _count += 1
    return {"count": _count}


@app.post("/reset")
def reset():
    """Reset the counter to 0."""
    global _count
    _count = 0
    return {"ok": True}


@app.get("/state")
def state():
    """Get the current counter state."""
    return {"count": _count}

