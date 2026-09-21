from typing import TypedDict

from langchain_core.messages import BaseMessage


class TokenUsage(TypedDict):
    input_tokens: int
    output_tokens: int
    total_tokens: int


def extract_usage(response: BaseMessage) -> TokenUsage | None:
    """Pull input/output/total token counts off a chat-model response.

    Returns None when the response carries no usage_metadata -- the normal
    case for every mocked LLM response in this test suite (a bare
    AIMessage(content=...)), so callers must treat None as "nothing to log",
    not an error.
    """
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return None
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }
