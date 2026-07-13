"""
Universal startup script for Replit, Render, Railway, and local dev.
Reads PORT from environment; defaults to 8000 locally.
"""

import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=False)
