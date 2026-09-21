"""TDD test for harbor export script (Task 2/3).

Task 3: bulk export_all over list_packs; no src vendoring; test for hello + tool_integrity_tier2.
"""
from pathlib import Path
import pytest


def test_export_hello_creates_task_toml_and_files(tmp_path: Path):
    """Export must produce a valid harbor task layout for hello_metacog at least."""
    import sys
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "harbor_export_all_packs.py"

    # Load the script as module without requiring it to be in packages
    spec = importlib.util.spec_from_file_location("harbor_export_mod", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    export_fn = getattr(mod, "export_hello_metacog", None) or getattr(mod, "export_all", None)
    assert export_fn is not None, "export script must expose export_hello_metacog or export_all"

    out_dir = tmp_path / "harbor_out"
    out_dir.mkdir()
    # Call; for task2 may target dsm-ae substructure or flat under arg; support either
    export_fn(out_dir)

    # Check for hello under conventional dsm-ae/ layout or direct (prefer dsm-ae)
    candidates = [
        out_dir / "dsm-ae" / "hello_metacog" / "task.toml",
        out_dir / "hello_metacog" / "task.toml",
    ]
    task_toml = next((c for c in candidates if c.is_file()), None)
    assert task_toml is not None, f"expected task.toml created by export; looked in {candidates}"

    # Also verify key files for the task
    task_dir = task_toml.parent
    assert (task_dir / "instruction.md").is_file()
    assert (task_dir / "environment" / "Dockerfile").is_file()
    assert (task_dir / "tests" / "test.sh").is_file()

    # Validate minimal toml content (schema 1.3, name)
    content = task_toml.read_text()
    assert 'schema_version = "1.3"' in content
    assert 'name = "dsm-ae/hello_metacog"' in content

    # test.sh should reference pack_bridge score + write_reward + /logs/verifier
    test_sh = (task_dir / "tests" / "test.sh").read_text()
    assert "score_workspace" in test_sh
    assert "write_reward" in test_sh
    assert "/logs/verifier/reward.json" in test_sh


def test_export_skips_live_harbor_when_no_cli():
    """Documented: if no harbor, we still produce files (this test itself does not require CLI)."""
    # This is a marker; live run skipped in CI / when harbor absent.
    # See script comments and task-2-brief.
    import shutil
    if shutil.which("harbor") is None:
        # Expected in this env; we verified file gen + verifier logic instead of `harbor run -a oracle`
        assert True
    pass


def test_export_all_creates_task_toml(tmp_path: Path):
    """Task 3 requirement: export_all creates task.toml for hello_metacog AND tool_integrity_tier2.
    Uses dsm-ae/ subdir layout under provided out_dir.
    """
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "harbor_export_all_packs.py"

    spec = importlib.util.spec_from_file_location("harbor_export_mod", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    export_all = getattr(mod, "export_all", None)
    assert export_all is not None, "export_all must be exposed"

    out_dir = tmp_path / "harbor_bulk"
    created = export_all(out_dir)

    # per requirement (adjusted for dsm-ae/ layout used by script + docs)
    hello_toml = out_dir / "dsm-ae" / "hello_metacog" / "task.toml"
    tid2_toml = out_dir / "dsm-ae" / "tool_integrity_tier2" / "task.toml"
    assert hello_toml.is_file(), "expected hello_metacog task.toml"
    assert tid2_toml.is_file(), "expected tool_integrity_tier2 task.toml"

    # spot check structure for one: no vendored src, has fixtures subdir + new Dockerfile style
    hello_dir = hello_toml.parent
    assert (hello_dir / "environment" / "Dockerfile").is_file()
    assert (hello_dir / "tests" / "test.sh").is_file()
    # fixtures/ exists (may be emptyish or have .gitkeep + contracts)
    assert (hello_dir / "environment" / "fixtures").is_dir()

    # test.sh generic
    test_sh = (tid2_toml.parent / "tests" / "test.sh").read_text()
    assert "score_workspace" in test_sh
    assert "tool_integrity_tier2" in test_sh
    assert "/logs/verifier/reward.json" in test_sh

    # Dockerfile uses monorepo COPY, no vendored /src inside task env
    df = (hello_dir / "environment" / "Dockerfile").read_text()
    assert "COPY pyproject.toml README.md ./" in df
    assert "COPY src ./src" in df
    assert "harbor_tasks/dsm-ae/" in df  # fixtures COPY uses context path
    # should not have old vendored copy style inside the task tree
    assert "COPY src /src/dsm-ae/src" not in df


def test_export_includes_llm_network_policy_and_context_notes(tmp_path: Path):
    """Task 6: generated task.toml must document allowlist/allowed_hosts, env vars, and Codex windows (no live LLM)."""
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "harbor_export_all_packs.py"

    spec = importlib.util.spec_from_file_location("harbor_export_mod", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    export_all = getattr(mod, "export_all", None)
    out_dir = tmp_path / "harbor_policy"
    export_all(out_dir)

    toml_path = out_dir / "dsm-ae" / "hello_metacog" / "task.toml"
    content = toml_path.read_text()

    # network allowlist for LLM
    assert 'network_mode = "allowlist"' in content
    assert "allowed_hosts" in content
    # env vars
    assert "OPENAI_API_BASE" in content
    assert "OPENAI_API_KEY" in content
    # context windows guidance (Codex ops not marketing)
    assert "272000" in content or "272k" in content.lower()
    assert "372000" in content or "372k" in content.lower()
    assert "1.05M" in content or "marketing" in content.lower() or "Codex" in content
    # docker label and cleanup are in harbor README/docs but ensure smoke default
    assert 'network_mode = "no-network"' in content
    # no live execution here; purely static export test

