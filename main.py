import os

os.environ["STARLETTE_MAX_FILE_SIZE"] = "1048576"  # 1MB spool threshold (default)
os.environ["STARLETTE_MEMORY_LIMIT"] = "52428800" # 50MB

import uvicorn
from src.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, workers=1)
