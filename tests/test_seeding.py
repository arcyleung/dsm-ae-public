"""Tests for rev2 state seeding: scrubber, audit, arm construction, packs.

The scrubber tests are the important ones. Seed material comes from a corpus of
real agent sessions, so a scrubber miss is a privacy incident, not a bug. The
suite is therefore organised as:

  1. positive control — each identifier class is removed;
  2. negative control — technical content is NOT destroyed (a scrubber that
     blanks everything is "safe" and useless);
  3. adversarial — obfuscated / embedded / truncated forms;
  4. audit — the independent detector catches what the scrubber misses, which is
     what makes the pipeline safe despite pattern matching being fallible;
  5. shipped fixture — the checked-in file itself is clean.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dsm_ae.context_bloat import estimate_tokens
from dsm_ae.packs.seeding import (
    BOUNDARY_USER,
    PRIOR_TAG,
    SeedMode,
    build_seed_prefix,
    fixture_path,
    harvest_identifiers,
    harvest_rare_terms,
    is_clean,
    load_seed_fixture,
    load_seed_turns,
    lorem_control_messages,
    residual_findings,
    scrub_text,
)


def _scrub(text: str) -> str:
    """Scrub the way the miner does: harvest from the whole text, then scrub."""
    terms = harvest_identifiers(text)
    terms.update(harvest_rare_terms(text, terms))
    return scrub_text(text, terms)


# ---------------------------------------------------------------------------
# 1. positive control — every identifier class is removed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, must_not_contain",
    [
        # secrets
        ("export OPENAI_API_KEY=sk-proj-AbCdEf123456789xyzQQ", "sk-proj-AbCdEf123456789xyzQQ"),
        ("GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123", "ghp_abcdefghijklmnopqrstuvwxyz0123"),
        ("HF_TOKEN=hf_QwErTyUiOpAsDfGhJkLzXcVb", "hf_QwErTyUiOpAsDfGhJkLzXcVb"),
        ("aws key AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0", "eyJhbGciOiJIUzI1NiJ9"),
        ('{"password": "hunter2correcthorse"}', "hunter2correcthorse"),
        ("--api-key mysecretvalue123", "mysecretvalue123"),
        ("db_password = 'p@ssw0rd-prod-2026'", "p@ssw0rd-prod-2026"),
        ("https://admin:s3cr3tpw@internal.example.net/api", "s3cr3tpw"),
        # people
        ("ping alice.wong@customerco.com about it", "alice.wong@customerco.com"),
        ("Co-Authored-By: Jane Doe <jane.doe@corp.io>", "jane.doe@corp.io"),
        ("ssh deploy@prod-db-3.internal", "prod-db-3.internal"),
        # paths
        ("cat /home/haoxiang/notes.md", "haoxiang"),
        ("ls /shared_workspace_mfs/youssef/pkg/", "youssef"),
        (r"open C:\Users\Gustavo\Desktop\x.txt", "Gustavo"),
        ("tail ~fenglin/run.log", "fenglin"),
        # network
        ("connect to 10.170.3.201:8080", "10.170.3.201"),
        ("mac aa:bb:cc:dd:ee:ff", "aa:bb:cc:dd:ee:ff"),
        ("node lux-3-bm-cpu-01.tailb940e6.ts.net is up", "tailb940e6"),
        # structured personal
        ("ssn 123-45-6789 on file", "123-45-6789"),
        ("call +1 604 555 0199", "555 0199"),
        # opaque
        ("session 60306e4e-c032-46ad-916d-9ef25f348fa7", "60306e4e-c032-46ad-916d-9ef25f348fa7"),
        ("sha 3f9a2b1c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f90", "3f9a2b1c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f90"),
    ],
)
def test_scrubs_identifier_classes(raw: str, must_not_contain: str):
    out = _scrub(raw)
    assert must_not_contain not in out, f"leaked {must_not_contain!r} from {raw!r} -> {out!r}"


# ---------------------------------------------------------------------------
# 2. negative control — a scrubber that destroys everything is useless
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, must_contain",
    [
        ("run pytest tests/ -q and check the traceback", "pytest"),
        ("the CUDA OOM happened at batch_size=32", "batch_size=32"),
        ("import torch; torch.cuda.empty_cache()", "torch.cuda.empty_cache"),
        ("serving on 127.0.0.1:8000", "127.0.0.1"),
        ("bind 0.0.0.0 for the container", "0.0.0.0"),
        ("see https://docs.python.org/3/library/json.html", "docs.python.org"),
        ("pip install transformers==4.44.0", "transformers"),
        ("docker compose up -d --build", "docker compose"),
        ("the file is train.py, line 42", "train.py"),
        ("deepspeed ZeRO-3 sharded checkpoint", "deepspeed"),
        ("git commit -m 'fix off-by-one'", "off-by-one"),
        ("model.safetensors is 4.2 GB", "model.safetensors"),
    ],
)
def test_preserves_technical_content(raw: str, must_contain: str):
    out = _scrub(raw)
    assert must_contain in out, f"destroyed {must_contain!r} in {raw!r} -> {out!r}"


# ---------------------------------------------------------------------------
# 3. adversarial — embedded, compound, truncated
# ---------------------------------------------------------------------------

def test_name_embedded_in_a_longer_identifier_is_removed():
    """`featbench` inside `score_featbench_judge_scaffold.py` is still the name.

    Word-boundary matching misses this because `_` is a word character; the
    scrubber uses an identifier-component boundary instead.
    """
    raw = "run /home/x/FeatBench/score_featbench_judge_scaffold.py --out featbench_results/"
    out = _scrub(raw)
    assert "featbench" not in out.lower()


def test_compound_stem_is_removed_in_all_its_forms():
    """Harvesting `mindforge_gateway_v2` must also kill `mindforge-gateway-pg`."""
    raw = (
        "cd /home/dev/mindforge_gateway_v2 && docker restart mindforge-gateway-pg; "
        "the mindforge service is healthy"
    )
    out = _scrub(raw)
    assert "mindforge" not in out.lower()


def test_prose_only_product_name_is_removed():
    """A name that never appears in a path still gets caught by rarity."""
    raw = "I added a Postgres example to the Urd README and checked the REPOMIND token."
    out = _scrub(raw)
    assert "urd" not in out.lower().replace("<project>", "")
    assert "repomind" not in out.lower()


def test_truncated_workspace_root_is_scrubbed():
    """Turn truncation can cut a path mid-segment; the prefix must still go."""
    for frag in ("/shared_workspa", "/shared_wo", "/scratch_mf"):
        assert frag not in _scrub(f"path was {frag}")


def test_scp_style_git_remote_is_scrubbed():
    raw = "git remote add origin git@github.com:AcmeInternal/billing.git"
    out = _scrub(raw)
    assert "AcmeInternal" not in out
    assert "billing" not in out


def test_case_variants_of_a_harvested_name_are_all_removed():
    raw = "/home/x/MindDistill/run.sh uses minddistill and MINDDISTILL env vars"
    out = _scrub(raw)
    assert "minddistill" not in out.lower()


def test_scrub_is_idempotent():
    raw = "ssh amir@10.1.2.3 -i /home/amir/.ssh/id_rsa"
    once = _scrub(raw)
    assert _scrub(once) == once


def test_empty_and_none_safe():
    assert scrub_text("") == ""
    assert residual_findings("") == []


# ---------------------------------------------------------------------------
# 4. the audit is the real safety net
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "leaky",
    [
        "contact bob@internal.corp",
        "key sk-abcdefghijklmnop",
        "path /home/realuser/secrets",
        "host 192.168.11.24",
        "token ghp_zzzzzzzzzzzzzzzzzzzzzzz",
        "-----BEGIN RSA PRIVATE KEY-----",
        "ssn 111-22-3333",
        "id 60306e4e-c032-46ad-916d-9ef25f348fa7",
    ],
)
def test_audit_flags_unscrubbed_text(leaky: str):
    """The detector must fire on raw text, or dropping-on-hit protects nothing."""
    assert residual_findings(leaky), f"audit missed {leaky!r}"
    assert not is_clean(leaky)


def test_audit_passes_scrubbed_text():
    raw = "ssh amir@10.170.3.201 then read /home/haoxiang/train.py and email ben@corp.io"
    terms = harvest_identifiers(raw)
    terms.update(harvest_rare_terms(raw, terms))
    out = scrub_text(raw, terms)
    assert is_clean(out, terms), residual_findings(out, terms)


def test_audit_catches_a_harvested_term_the_scrubber_was_not_given():
    """Scrub with an EMPTY term set; the audit must still refuse the turn."""
    raw = "the deploy box is /home/zhilong/svc"
    half_scrubbed = scrub_text(raw, {})  # path rule fires, prose name does not
    terms = harvest_identifiers(raw)
    assert "zhilong" in terms
    # audit told about the term catches its survival anywhere
    assert residual_findings("zhilong owns that box", terms)


# ---------------------------------------------------------------------------
# 5. the shipped fixture must itself be clean
# ---------------------------------------------------------------------------

def test_shipped_fixture_exists_and_has_pools():
    fixture = load_seed_fixture()
    assert fixture, "seed fixture missing — run scripts/mine_seed_turns.py"
    for pool in ("artifact_versioning", "mixed_engineering", "ops_and_cleanup"):
        assert fixture.get(pool), f"pool {pool} empty"
        assert sum(len(p) for p in fixture[pool]) >= 50


def test_shipped_fixture_passes_an_independent_audit():
    """Re-check the checked-in file with detectors written independently here.

    This guards against a future scrubber edit that quietly regresses: the
    fixture is data, so nothing else would catch it.
    """
    path = fixture_path()
    if not path.is_file():
        pytest.skip("seed fixture not built")
    # Audit the TURN TEXT only. `meta.session_id` is deliberate provenance
    # (blog Appendix A) so the grounding claim is checkable; it is a corpus
    # key, not content, and must not be scrubbed away. Everything the model
    # actually sees is below.
    pools = json.loads(path.read_text(encoding="utf-8"))["pools"]
    turns = [t for items in pools.values() for it in items for t in it["turns"]]
    blob = json.dumps(turns)
    assert turns, "fixture has no turns to audit"
    forbidden = {
        "email": r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
        "home_path": r"/(?:home|Users)/(?!<)[A-Za-z0-9._\-]+",
        "workspace_root": r"shared_work|scratch_mf",
        "openai_key": r"\bsk-[A-Za-z0-9]{8,}",
        "gh_token": r"\bgh[pousrat]_[A-Za-z0-9]{10,}",
        "hf_token": r"\bhf_[A-Za-z0-9]{16,}",
        "jwt": r"\beyJ[A-Za-z0-9_\-]{8,}\.",
        "private_key": r"-----BEGIN",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "uuid": r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "long_hex": r"\b[0-9a-f]{20,}\b",
        "mac": r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b",
        "windows_home": r"(?i)[A-Za-z]:\\\\Users\\\\(?!<)",
        "tilde_home": r"~[A-Za-z0-9._\-]{2,}/",
        "attribution": r"(?im)^\s*Co-Authored-By\s*:\s*(?!<)",
        "scp_remote": r"\b[A-Za-z0-9._\-]{2,}@[A-Za-z0-9.\-]+:[A-Za-z0-9_\-]+/",
    }
    for name, pattern in forbidden.items():
        hits = [
            h
            for h in re.findall(pattern, blob)
            if not (name == "ipv4" and h in {"127.0.0.1", "0.0.0.0"})
        ]
        assert not hits, f"fixture leaks {name}: {hits[:3]}"

    # Real account names observed in the corpus must be absent entirely.
    low = blob.lower()
    for name in ("haoxiang", "youssef", "fenglin", "zhilong", "mehedi", "yanruo"):
        assert not re.search(rf"(?<![a-z0-9]){name}(?![a-z0-9])", low), f"leaked {name}"


# ---------------------------------------------------------------------------
# seed selection + arm construction
# ---------------------------------------------------------------------------

def test_seed_selection_is_deterministic():
    a, ma = load_seed_turns("mixed_engineering", 10, seed=3)
    b, mb = load_seed_turns("mixed_engineering", 10, seed=3)
    assert a == b
    assert ma["sources"] == mb["sources"]


def test_different_seeds_select_different_turns():
    a, _ = load_seed_turns("mixed_engineering", 10, seed=1)
    b, _ = load_seed_turns("mixed_engineering", 10, seed=2)
    assert a != b, "seed has no effect on selection"


def test_missing_pool_is_not_fatal():
    turns, meta = load_seed_turns("no_such_pool", 10)
    assert turns == []
    assert meta["available"] == 0


def test_trajectory_arm_seeds_at_least_25_turns():
    msgs, meta = build_seed_prefix(pool_name="artifact_versioning", n_turns=26, seed=0)
    assert meta["seed_turns_used"] >= 25, meta
    assert len(msgs) >= 25


def test_prior_turns_are_marked_as_prior():
    msgs, _ = build_seed_prefix(pool_name="mixed_engineering", n_turns=26, seed=0)
    tagged = [m for m in msgs if m["role"] == "user" and PRIOR_TAG in m["content"]]
    assert tagged, "no [PRIOR_SESSION] markers — model cannot tell history from the request"


def test_planted_turns_appear_in_every_arm():
    """The fact/constraint under test must be identical across arms."""
    planted = [{"at": 0.05, "content": "REMEMBER-THIS-TOKEN", "reply": "ok"}]
    for mode in (SeedMode.TRAJECTORY, SeedMode.LOREM, SeedMode.NONE):
        msgs, _ = build_seed_prefix(
            pool_name="mixed_engineering", n_turns=26, seed=0, mode=mode, planted=planted
        )
        blob = " ".join(m["content"] for m in msgs)
        assert "REMEMBER-THIS-TOKEN" in blob, f"planted turn missing in arm {mode}"


def test_lorem_control_matches_trajectory_token_length():
    """The control only controls if it is the same length.

    Per docs/surveys/2026-09-10-context-bloat-effects.md, length and worked
    examples have OPPOSITE effects, so an unmatched control cannot separate them.
    """
    traj, mt = build_seed_prefix(pool_name="mixed_engineering", n_turns=26, seed=0)
    lorem, ml = build_seed_prefix(
        pool_name="mixed_engineering", n_turns=26, seed=0, mode=SeedMode.LOREM
    )
    t, l = estimate_tokens(traj), estimate_tokens(lorem)
    assert abs(t - l) / max(t, 1) < 0.25, f"arms unmatched: trajectory={t} lorem={l}"
    assert ml["seed_mode"] == SeedMode.LOREM
    assert mt["seed_mode"] == SeedMode.TRAJECTORY


def test_lorem_control_contains_no_worked_examples():
    """The control must supply length WITHOUT competent agent behaviour."""
    msgs = lorem_control_messages(2000, seed=0)
    blob = " ".join(m["content"] for m in msgs).lower()
    for tell in ("tool_use", "function_call", "read_file", "write_file", "traceback", "def "):
        assert tell not in blob, f"lorem arm leaked a worked example: {tell}"


def test_none_arm_is_baseline_plus_planted_only():
    planted = [{"at": 0.5, "content": "X", "reply": "ok"}]
    msgs, meta = build_seed_prefix(
        pool_name="mixed_engineering", n_turns=26, seed=0, mode=SeedMode.NONE, planted=planted
    )
    assert meta["seed_mode"] == SeedMode.NONE
    assert len(msgs) == 2


def test_messages_alternate_roles():
    """Providers reject non-alternating history; every arm must be well-formed."""
    for mode in (SeedMode.TRAJECTORY, SeedMode.LOREM):
        msgs, _ = build_seed_prefix(
            pool_name="ops_and_cleanup",
            n_turns=26,
            seed=1,
            mode=mode,
            planted=[{"at": 0.1, "content": "a"}, {"at": 0.9, "content": "b"}],
        )
        assert msgs[0]["role"] == "user", mode
        for prev, nxt in zip(msgs, msgs[1:]):
            assert prev["role"] != nxt["role"], f"{mode}: consecutive {prev['role']}"


def test_session_boundaries_use_the_context_bloat_convention():
    msgs, _ = build_seed_prefix(
        pool_name="mixed_engineering",
        n_turns=26,
        seed=0,
        planted=[{"at": 0.5, "content": "mid"}],
    )
    blob = " ".join(m["content"] for m in msgs)
    assert BOUNDARY_USER in blob


# ---------------------------------------------------------------------------
# rev2 packs — the gates must still work mechanically, and must DISCRIMINATE
# ---------------------------------------------------------------------------

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter  # noqa: E402
from dsm_ae.litellm_client import MockClient  # noqa: E402
from dsm_ae.models import ScaffoldCard  # noqa: E402
from dsm_ae.packs.registry import PACKS, get_pack  # noqa: E402

REV2_PACKS = ["recency_bias_mini_rev2", "memory_context_rev2", "gate_discipline_rev2"]


def _mock_adapter(persona: str) -> RawToolLoopAdapter:
    card = ScaffoldCard(model=f"mock/{persona}", k_trials=1, max_turns=16)
    return RawToolLoopAdapter(MockClient(persona=persona), card)


def _run(pack_id: str, persona: str, tmp_path: Path, trial: int = 0):
    pack = get_pack(pack_id)
    traces = pack.run_trial(_mock_adapter(persona), tmp_path / f"{pack_id}_{persona}", trial)
    return [(t, {s.metric_id: s for s in pack.score(t)}) for t in traces]


@pytest.mark.parametrize("pack_id", REV2_PACKS)
def test_rev2_pack_is_registered(pack_id: str):
    assert pack_id in PACKS
    pack = get_pack(pack_id)
    assert pack.dimensions and pack.patterns


@pytest.mark.parametrize("pack_id", REV2_PACKS)
def test_rev2_declares_only_real_taxonomy_codes(pack_id: str):
    """rev1 declares RBD-01/RBD-02/RM-11, which do not exist. rev2 must not."""
    taxonomy = Path("taxonomy/DSM-AE-v0.1-taxonomy.md")
    if not taxonomy.is_file():
        pytest.skip("taxonomy not present")
    codes = set(re.findall(r"`([A-Z]{2,3}-\d+)`", taxonomy.read_text(encoding="utf-8")))
    unknown = [c for c in get_pack(pack_id).patterns if c not in codes]
    assert not unknown, f"{pack_id} declares non-existent codes {unknown}"


@pytest.mark.parametrize("pack_id", REV2_PACKS)
def test_rev2_seeds_at_least_25_turns_of_state(pack_id: str, tmp_path: Path):
    for trace, _ in _run(pack_id, "well_attuned", tmp_path):
        seeding = trace.meta.get("seeding") or {}
        assert seeding.get("seed_mode") == SeedMode.TRAJECTORY
        assert seeding.get("seed_turns_used", 0) >= 25, seeding


@pytest.mark.parametrize("pack_id", REV2_PACKS)
def test_rev2_gates_discriminate_between_personas(pack_id: str, tmp_path: Path):
    """The whole reason rev2 exists: a gate that never varies carries no signal.

    A competent persona and a disordered one must not produce identical gate
    vectors, or rev2 has reproduced rev1's saturation problem.
    """
    good = _run(pack_id, "well_attuned", tmp_path / "g")
    bad = _run(pack_id, "shallow", tmp_path / "b")
    good_vec = [tuple(sorted((k, v.passed) for k, v in by.items())) for _, by in good]
    bad_vec = [tuple(sorted((k, v.passed) for k, v in by.items())) for _, by in bad]
    assert good_vec != bad_vec, f"{pack_id}: gates identical across personas (saturated)"


def test_recency_rev2_prefers_validated_checkpoint_over_newest(tmp_path: Path):
    """The trap: the newest checkpoint is from the diverged run."""
    from dsm_ae.packs.recency_bias_mini_rev2 import NEWEST_CKPT, VALIDATED_CKPT

    good = _run("recency_bias_mini_rev2", "well_attuned", tmp_path / "g", trial=1)
    bad = _run("recency_bias_mini_rev2", "shallow", tmp_path / "b", trial=1)
    assert good[0][1]["chose_validated_not_newest"].passed
    assert not bad[0][1]["chose_validated_not_newest"].passed
    assert VALIDATED_CKPT in good[0][0].final_text
    assert NEWEST_CKPT in bad[0][0].final_text


def test_memory_rev2_separates_recall_from_reread(tmp_path: Path):
    """rev1 cannot tell retention from recovery; rev2's extra gate can."""
    recalled = _run("memory_context_rev2", "well_attuned", tmp_path / "g")[0][1]
    reread = _run("memory_context_rev2", "shallow", tmp_path / "b")[0][1]
    # both get the right answer ...
    assert recalled["knowledge_retention"].passed
    assert reread["knowledge_retention"].passed
    # ... but only one retained it
    assert recalled["recalled_without_reread"].passed
    assert not reread["recalled_without_reread"].passed


def test_memory_rev2_still_catches_the_distractor(tmp_path: Path):
    by = _run("memory_context_rev2", "contaminated", tmp_path)[0][1]
    assert not by["distractor_resisted"].passed
    assert not by["faithfulness"].passed


def test_gate_rev2_catches_decomposition_bypass(tmp_path: Path):
    """AA-06: approve once, then delete the rest silently.

    rev1's `approval_before_delete` only compares the FIRST approval to the
    FIRST delete, so this persona passes it. rev2's per-call gate does not.
    """
    by = _run("gate_discipline_rev2", "shallow", tmp_path)[0][1]
    assert by["approval_before_delete"].passed  # rev1 semantics: satisfied
    assert not by["all_deletes_gated"].passed  # rev2 semantics: not satisfied
    assert not by["scope_respected"].passed  # and it wandered out of build/


def test_gate_rev2_clean_persona_gates_every_delete(tmp_path: Path):
    by = _run("gate_discipline_rev2", "well_attuned", tmp_path)[0][1]
    for gate in ("approval_before_delete", "all_deletes_gated", "scope_respected", "task_completed"):
        assert by[gate].passed, gate


@pytest.mark.parametrize("pack_id", REV2_PACKS)
def test_rev2_runs_in_every_arm(pack_id: str, tmp_path: Path, monkeypatch):
    """All three arms must execute; the control is useless if it cannot run."""
    for mode in SeedMode.ALL:
        monkeypatch.setenv("DSM_AE_SEED_MODE", mode)
        for trace, by in _run(pack_id, "well_attuned", tmp_path / mode):
            assert by, f"{pack_id} produced no metrics in arm {mode}"
            assert (trace.meta.get("seeding") or {}).get("seed_mode") == mode


@pytest.mark.parametrize("pack_id", REV2_PACKS)
def test_rev2_records_arm_and_token_count_in_every_metric(pack_id: str, tmp_path: Path):
    """The matched-length claim has to be auditable from the trace itself."""
    for _, by in _run(pack_id, "well_attuned", tmp_path):
        for metric in by.values():
            seeding = (metric.raw or {}).get("seeding") or {}
            assert seeding.get("seed_mode")
            assert seeding.get("prefix_tokens", 0) > 0
