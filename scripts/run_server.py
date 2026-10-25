import sys
from pathlib import Path

import uvicorn

# Direct script execution puts ``scripts`` rather than the repository root on
# sys.path.  Bootstrap the root before importing the application package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
