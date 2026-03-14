"""Convenience script to run the mail agent."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.main import main

if __name__ == "__main__":
    main()
