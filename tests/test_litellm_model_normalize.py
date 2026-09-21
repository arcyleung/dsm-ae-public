from dsm_ae.litellm_client import _normalize_litellm_model


def test_hosted_vllm_with_api_base_becomes_openai():
    assert (
        _normalize_litellm_model("hosted_vllm/qwen3.6-plus", api_base="http://x/v1")
        == "openai/qwen3.6-plus"
    )


def test_vllm_prefix_with_api_base():
    assert (
        _normalize_litellm_model("vllm/qwen3.6-plus", api_base="http://x/v1")
        == "openai/qwen3.6-plus"
    )


def test_bare_name_with_api_base():
    assert _normalize_litellm_model("qwen3.6-plus", api_base="http://x/v1") == "openai/qwen3.6-plus"


def test_openai_prefix_kept():
    assert (
        _normalize_litellm_model("openai/qwen3.6-plus", api_base="http://x/v1")
        == "openai/qwen3.6-plus"
    )


def test_hosted_vllm_without_api_base_kept():
    assert (
        _normalize_litellm_model("hosted_vllm/qwen3.6-plus", api_base=None)
        == "hosted_vllm/qwen3.6-plus"
    )


def test_make_client_explicit_api_base_beats_yaml(tmp_path):
    """Form/CLI api_base must not be overwritten by models.yaml fallback."""
    yml = tmp_path / "models.yaml"
    yml.write_text(
        """
model_list:
  - model_name: other
    litellm_params:
      model: other
      api_base: http://yaml-should-not-win/v1
      api_key: yaml-key
"""
    )
    from dsm_ae.litellm_client import make_client

    c = make_client(
        "hosted_vllm/qwen3.6-plus",
        models_yaml=yml,
        api_base="http://form-wins/v1",
        api_key="form-key",
    )
    assert c.api_base == "http://form-wins/v1"
    assert c.api_key == "form-key"
    assert c.model == "hosted_vllm/qwen3.6-plus"


def test_assistant_message_preserves_reasoning_content():
    from dsm_ae.litellm_client import (
        CompletionResult,
        assistant_message_from_result,
        _extract_reasoning_content,
    )

    assert _extract_reasoning_content({"reasoning_content": "chain"}) == "chain"

    class M:
        content = "hi"
        reasoning_content = "think"

    assert _extract_reasoning_content(M()) == "think"

    r = CompletionResult(
        content="x",
        tool_calls=[{"id": "t1", "name": "done", "arguments": {"message": "ok"}}],
        reasoning_content="because",
    )
    msg = assistant_message_from_result(r)
    assert msg["reasoning_content"] == "because"
    assert msg["tool_calls"][0]["function"]["name"] == "done"
