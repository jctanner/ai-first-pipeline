#!/usr/bin/env python3
"""Bug bash analysis pipeline — AI-driven RHOAIENG bug evaluation."""

import sys
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from lib.cli import parse_args
from lib.phases import main

# Load environment variables from .env file (optional in K8s)
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    # In K8s, env vars come from secrets - .env not required
    import os
    if not os.getenv("ANTHROPIC_VERTEX_PROJECT_ID"):
        print(
            "Error: .env file not found and ANTHROPIC_VERTEX_PROJECT_ID not set\n"
            "\n"
            f"Expected location: {env_path}\n"
            "\n"
            "Create a .env file with at minimum:\n"
            "\n"
            "  CLAUDE_CODE_USE_VERTEX=1\n"
            "  CLOUD_ML_REGION=us-east5\n"
            "  ANTHROPIC_VERTEX_PROJECT_ID=<your-project>\n"
            "\n"
            "The Claude Agent SDK requires valid Vertex AI credentials.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
