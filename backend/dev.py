# Author: Ching Kao
# Student ID: 85768427
"""Start the backend using only this project's environment files."""
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv


def main() -> None:
    root = Path(__file__).resolve().parent
    # Shell > .env.local > .env. No frontend or repository-root env is loaded.
    load_dotenv(root / ".env.local", override=False)
    load_dotenv(root / ".env", override=False)
    port = int(os.environ.get("BACKEND_PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("BACKEND_PORT must be between 1 and 65535.")
    uvicorn.run(
        "ai_coder.main:create_app",
        factory=True,
        app_dir=str(root / "src"),
        host=os.environ.get("BACKEND_HOST", "127.0.0.1"),
        port=port,
    )


if __name__ == "__main__":
    main()
