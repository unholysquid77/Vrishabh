"""
Vrishabh — Entry Point
Run with: uvicorn main:app --reload --port 8000
"""

import uvicorn
from api.server import app

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
