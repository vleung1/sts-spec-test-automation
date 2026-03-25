"""Call AWS Bedrock to summarize detected test failures from log content."""

import boto3

from .config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    BEDROCK_MODEL_ID,
    MAX_LOG_CHARS,
    MAX_OUTPUT_TOKENS,
)
from .detect import DetectionResult


SYSTEM_PROMPT = """\
You are a test-failure analyst for an API test automation framework (STS v2).
You will receive a test log and a list of detected failure lines with context.

Produce a Markdown summary with one section per distinct failure. For each failure include:
- **Test / Stage**: the test name, stage label, or model handle
- **Expected**: what the test expected (status code, value, shape, etc.)
- **Actual**: what happened instead
- **Location**: file path or script name if identifiable
- **Error**: the key error message (verbatim, trimmed to one line)

If multiple failures share the same root cause, group them.
Do NOT reproduce the entire log. Be concise.\
"""


def _build_user_message(result: DetectionResult) -> str:
    failure_blocks = "\n\n".join(
        f"### Line {m.line_number}\n```\n{m.as_block()}\n```"
        for m in result.matches
    )

    log_excerpt = result.log_content
    if len(log_excerpt) > MAX_LOG_CHARS:
        half = MAX_LOG_CHARS // 2
        log_excerpt = (
            log_excerpt[:half]
            + "\n\n... [log truncated] ...\n\n"
            + log_excerpt[-half:]
        )

    return (
        f"## Detected failure locations ({len(result.matches)} match(es))\n\n"
        f"{failure_blocks}\n\n"
        f"## Full log\n\n```\n{log_excerpt}\n```"
    )


def _get_bedrock_client():
    kwargs: dict = {"region_name": AWS_REGION}
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
    return boto3.client("bedrock-runtime", **kwargs)


def summarize_failures(result: DetectionResult) -> str:
    """Send the detection result to Bedrock and return the Markdown summary."""
    client = _get_bedrock_client()

    response = client.converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [{"text": _build_user_message(result)}],
            }
        ],
        inferenceConfig={
            "maxTokens": MAX_OUTPUT_TOKENS,
            "temperature": 0.0,
        },
    )

    output_message = response["output"]["message"]
    summary_parts: list[str] = []
    for block in output_message["content"]:
        if "text" in block:
            summary_parts.append(block["text"])

    return "\n".join(summary_parts)
