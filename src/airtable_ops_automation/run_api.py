from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("ORDER_API_HOST", "0.0.0.0")
    port = int(os.getenv("ORDER_API_PORT", "8000"))
    uvicorn.run("airtable_ops_automation.order_api:app", host=host, port=port, reload=True)
