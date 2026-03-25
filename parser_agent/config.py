"""Configuration for the parser-agent module."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LOG_DIR = REPO_ROOT / "logs"
SUMMARY_DIR = REPO_ROOT / "reports" / "agent-summaries"

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-3-5-haiku-20241022-v1:0"
)

MAX_LOG_CHARS = 80_000
MAX_OUTPUT_TOKENS = 4096
