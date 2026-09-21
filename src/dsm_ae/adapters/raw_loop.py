"""Minimal ReAct-style tool loop — reference scaffold for DSM-AE."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from dsm_ae.litellm_client import (
    RAW_TOOLS,
    ModelClient,
    assistant_message_from_result,
)
from dsm_ae.models import (
    FsEvent,
    Message,
    ScaffoldCard,
    ToolCall,
    TrialTrace,
)


class RawToolLoopAdapter:
    name = "raw"

    def __init__(self, client: ModelClient, card: ScaffoldCard):
        self.client = client
        self.card = card

    def run(
        self,
        *,
        pack: str,
        scenario_id: str,
        system_prompt: str,
        user_prompt: str,
        workspace: Path,
        trial_index: int = 0,
        variant: str | None = None,
        allowed_deletes: set[str] | None = None,
        prefix_messages: list[dict[str, Any]] | None = None,
    ) -> TrialTrace:
        """Run agent until done() or max_turns.

        ``prefix_messages`` (optional): multi-turn history inserted after system
        and before the pack user prompt (bloated-context experiments).
        """
        t0 = time.time()
        if hasattr(self.client, "set_trial"):
            self.client.set_trial(trial_index)  # type: ignore[attr-defined]

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        if prefix_messages:
            messages.extend(list(prefix_messages))
        messages.append({"role": "user", "content": user_prompt})
        trace = TrialTrace(
            scenario_id=scenario_id,
            pack=pack,
            variant=variant,
            trial_index=trial_index,
            scaffold_card=self.card,
        )
        final_text = ""
        total_tokens = 0.0

        for _turn in range(self.card.max_turns):
            result = self.client.complete(
                messages,
                tools=RAW_TOOLS,
                temperature=self.card.temperature,
                max_tokens=self.card.max_tokens,
            )
            total_tokens += result.usage.get("prompt_tokens", 0) + result.usage.get(
                "completion_tokens", 0
            )

            if result.content:
                final_text = result.content
                trace.messages.append(
                    Message(role="assistant", content=result.content)
                )

            if not result.tool_calls:
                # Final assistant turn (no tools). Echo reasoning_content when
                # present so multi-turn thinking APIs stay consistent if we ever
                # continue; also required if content was empty but reasoning ran.
                if result.content or result.reasoning_content:
                    messages.append(assistant_message_from_result(result))
                break

            # Single assistant message: content + reasoning_content + tool_calls.
            # DeepSeek thinking mode requires reasoning_content to be passed back
            # on every subsequent request in the conversation.
            messages.append(assistant_message_from_result(result))

            done = False
            for tc in result.tool_calls:
                name = tc["name"]
                args = tc.get("arguments") or {}
                out, fs_ev = self._exec(name, args, workspace)
                tool = ToolCall(
                    id=tc["id"], name=name, arguments=args, result=out[:4000]
                )
                trace.tool_calls.append(tool)
                if fs_ev:
                    for ev in fs_ev:
                        trace.fs_events.append(ev)
                        if ev.op == "read":
                            trace.files_read.append(ev.path)
                        elif ev.op == "write":
                            trace.files_written.append(ev.path)
                        elif ev.op == "delete":
                            trace.files_deleted.append(ev.path)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": name,
                        "content": out[:8000],
                    }
                )
                trace.messages.append(
                    Message(
                        role="tool",
                        content=out[:2000],
                        name=name,
                        tool_call_id=tc["id"],
                    )
                )
                if name == "done":
                    final_text = str(args.get("message") or out)
                    done = True
            if done:
                break

        trace.final_text = final_text
        trace.costs = {"tokens": total_tokens}
        trace.timings_ms = (time.time() - t0) * 1000
        # Full untruncated LLM conversation (system/user/assistant/tool) for
        # trajectory files — separate from the summarized trace.messages.
        try:
            trace.meta["full_conversation"] = json.loads(json.dumps(messages, default=str))
        except Exception:
            trace.meta["full_conversation"] = messages
        return trace

    def _exec(
        self, name: str, args: dict[str, Any], workspace: Path
    ) -> tuple[str, list[FsEvent]]:
        events: list[FsEvent] = []
        try:
            if name == "read_file":
                path = self._safe(workspace, str(args.get("path", "")))
                text = path.read_text(encoding="utf-8", errors="replace")
                events.append(
                    FsEvent(op="read", path=str(path.relative_to(workspace)), content_preview=text[:200])
                )
                return text, events
            if name == "write_file":
                path = self._safe(workspace, str(args.get("path", "")))
                content = str(args.get("content", ""))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                events.append(
                    FsEvent(
                        op="write",
                        path=str(path.relative_to(workspace)),
                        content_preview=content[:200],
                    )
                )
                return f"wrote {path.relative_to(workspace)} ({len(content)} bytes)", events
            if name == "delete_file":
                path = self._safe(workspace, str(args.get("path", "")))
                rel = str(path.relative_to(workspace))
                if path.exists():
                    path.unlink()
                    events.append(FsEvent(op="delete", path=rel))
                    return f"deleted {rel}", events
                return f"missing {rel}", events
            if name == "list_dir":
                path = self._safe(workspace, str(args.get("path") or "."))
                if not path.exists():
                    return "[]", events
                names = sorted(p.name for p in path.iterdir())
                events.append(FsEvent(op="list", path=str(path.relative_to(workspace))))
                return json.dumps(names), events
            if name == "shell":
                cmd = str(args.get("command", ""))
                # very restricted for safety
                if any(x in cmd for x in [";", "&&", "|", ">", "`", "$(", "rm -rf /"]):
                    return "blocked: unsafe shell pattern", events
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                out = (proc.stdout or "") + (proc.stderr or "")
                return out[:4000] or f"exit {proc.returncode}", events
            if name == "request_approval":
                action = args.get("action", "")
                reason = args.get("reason", "")
                # Auto-approve in harness; scoring checks that the call was made
                return f"APPROVED: action={action}; reason={reason}", events
            if name == "done":
                return str(args.get("message", "")), events
            return f"unknown tool {name}", events
        except Exception as e:
            return f"error: {e}", events

    def _safe(self, workspace: Path, rel: str) -> Path:
        workspace = workspace.resolve()
        target = (workspace / rel).resolve()
        if not str(target).startswith(str(workspace)):
            raise ValueError(f"path escapes workspace: {rel}")
        return target


def fresh_workspace(base: Path) -> Path:
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    return base
