"""Entry point — run with:  python -m src  or  uvicorn src.app:app"""
import uvicorn
from .config import settings

if __name__ == "__main__":
    uvicorn.run(
        "src.app:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
