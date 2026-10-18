"""
Vercel Serverless Entrypoint for FastAPI
"""

import sys
import os

# Add parent directory (project root) to sys.path so modules (main, core, controllers, etc.) can be imported
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from main import app

__all__ = ["app"]
