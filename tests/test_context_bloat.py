"""Tests for bloated-context history indexing and OpenAI-schema normalization."""

from __future__ import annotations

import json
from pathlib import Path

from dsm_ae.context_bloat import (
    ContextBloatConfig,
    _extract_messages_from_payload,
    _normalize_messages,
    build_stuffed_history,
)


def _assert_openai_tool_calls(messages: list[dict]) -> None:
    for m in messages:
        assert m.get("role") in ("user", "assistant", "tool"), m
        for tc in m.get("tool_calls") or []:
            assert isinstance(tc, dict)
            assert tc.get("type") == "function"
            assert tc.get("id")
            fn = tc.get("function")
            assert isinstance(fn, dict), tc
            assert fn.get("name")
            assert isinstance(fn.get("arguments"), str)


def test_extract_unwraps_trial_record_list():
    payload = [
        {
            "trial_id": "t0",
            "pack": "gate_discipline",
            "full_conversation": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "list_dir", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "[]"},
                {"role": "assistant", "content": "done"},
            ],
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "list_dir",
                    "arguments": {},
                    "result": "[]",
                    "error": None,
                }
            ],
            "final_text": "done",
        }
    ]
    msgs, pack, _model = _extract_messages_from_payload(payload)
    assert pack == "gate_discipline"
    assert all(m.get("role") for m in msgs)
    assert msgs[0]["role"] == "system"
    assert any(m.get("tool_calls") for m in msgs)
    # Must NOT treat the trial record itself as a message
    assert not any("full_conversation" in m for m in msgs)


def test_normalize_rejects_internal_tool_calls_shape():
    """Internal ToolCall dumps (name/arguments/result) must not pass as OpenAI tool_calls."""
    bad = [
        {
            "role": None,  # trial-record-like slip
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "list_dir",
                    "arguments": {"path": "."},
                    "result": '["a"]',
                    "error": None,
                }
            ],
            "full_conversation": [
                {"role": "user", "content": "look around"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "list_dir",
                                "arguments": '{"path": "."}',
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "c1", "content": '["a"]'},
                {"role": "assistant", "content": "saw a"},
            ],
        }
    ]
    # When passed as raw list including trial record, normalize unwraps full_conversation
    out = _normalize_messages(bad, pack="p", trial=0, id_prefix="b0_")
    _assert_openai_tool_calls(out)
    assert any(m["role"] == "assistant" and m.get("tool_calls") for m in out)
    for m in out:
        if m.get("tool_calls"):
            for tc in m["tool_calls"]:
                assert "function" in tc
                assert "result" not in tc


def test_normalize_flattens_internal_assistant_tool_calls():
    msgs = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "read_file",
                    "arguments": {"path": "x"},
                    "result": "hello",
                    "error": None,
                }
            ],
        }
    ]
    out = _normalize_messages(msgs, pack="p", trial=0, id_prefix="x_")
    assert out
    assert all(not m.get("tool_calls") for m in out)
    assert any("read_file" in (m.get("content") or "") for m in out)


def test_normalize_openai_tool_calls_keep_function():
    msgs = [
        {"role": "user", "content": "do it"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "list_dir", "arguments": '{"path": "."}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_abc", "content": "[]", "name": "list_dir"},
        {"role": "assistant", "content": "empty"},
    ]
    out = _normalize_messages(msgs, pack="p", trial=0, id_prefix="pref_")
    _assert_openai_tool_calls(out)
    tc_msg = next(m for m in out if m.get("tool_calls"))
    assert tc_msg["tool_calls"][0]["id"].startswith("pref_")
    tool_msg = next(m for m in out if m.get("role") == "tool")
    assert tool_msg["tool_call_id"].startswith("pref_")


def test_normalize_drops_incomplete_tool_pairs():
    msgs = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "list_dir", "arguments": "{}"},
                }
            ],
        },
        # missing tool result — should not emit bare tool_calls
    ]
    out = _normalize_messages(msgs, pack="p", trial=0, id_prefix="z_")
    _assert_openai_tool_calls(out)
    assert not any(m.get("tool_calls") for m in out)


def test_build_stuffed_history_schema_valid(tmp_path: Path):
    # Minimal source corpus
    conv = tmp_path / "trajectories" / "otherpack__t0" / "conversation.json"
    conv.parent.mkdir(parents=True)
    conv.write_text(
        json.dumps(
            [
                {
                    "trial_id": "t0",
                    "pack": "otherpack",
                    "full_conversation": [
                        {"role": "system", "content": "sys"},
                        {"role": "user", "content": "hello " * 200},
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "list_dir",
                                        "arguments": '{"path": "."}',
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": "call_1",
                            "content": '["a.txt"]',
                        },
                        {"role": "assistant", "content": "found a.txt " * 100},
                    ],
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "list_dir",
                            "arguments": {"path": "."},
                            "result": '["a.txt"]',
                            "error": None,
                        }
                    ],
                    "final_text": "found",
                }
            ]
        ),
        encoding="utf-8",
    )
    cfg = ContextBloatConfig(
        level=0.5,
        window_tokens=4000,
        reserve_tokens=500,
        model="qwen3.6-plus",
        sources=[tmp_path],
        seed=42,
        allow_source_file_fallback=True,
    )
    hist, meta = build_stuffed_history(
        cfg,
        pack_under_test="sycophancy_mini",
        trial_index=0,
        system_prompt="You are a coding agent.",
    )
    assert meta["achieved_stuff_tokens"] > 0
    assert meta["n_sources"] >= 1 or meta.get("filler_tokens", 0) > 0
    _assert_openai_tool_calls(hist)
    # Must never include trial-record keys as messages
    for m in hist:
        assert "full_conversation" not in m
        assert "final_text" not in m
        assert "trial_id" not in m
