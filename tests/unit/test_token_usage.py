from langchain_core.messages import AIMessage

from src.agents.token_usage import extract_usage


def test_extract_usage_returns_dict_when_usage_metadata_present() -> None:
    response = AIMessage(
        content="hello",
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )

    usage = extract_usage(response)

    assert usage == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


def test_extract_usage_returns_none_when_absent() -> None:
    # Matches every existing mocked LLM response in this test suite, which
    # constructs AIMessage(content=...) with no usage_metadata kwarg.
    response = AIMessage(content="hello")

    assert extract_usage(response) is None
