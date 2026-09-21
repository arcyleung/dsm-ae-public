"""State seeding for rev2 indicator packs.

Motivation
----------
81% of pack gates return an identical value for every model at k=20, and 75 of
those are at ceiling.  A gate that never varies carries no information (item
discrimination, see docs/surveys/2026-09-08-smoke-test-criteria-survey.md §3.2).
The diagnosis is that each rev1 fixture presents its challenge *in isolation and
clearly marked* — the easiest possible version of the behaviour.

The generalisation (docs/blog_post.md §2.2): an agent is a ReAct loop, so a
behaviour is a pattern of state transitions.  A deterministic single-turn gate is
the n=1 case.  Seed states 0..n-1 and test the decision at state n, and the
fixture becomes long-horizon in the STATE it presents without being long-horizon
in wall-clock.

Evidence that this works: docs/surveys/2026-09-10-context-bloat-effects.md found
padding with unrelated prior sessions moved gpt-5.6 gate agreement from 85%
identical -> 67%, mean spread 2.12x, sign test p=0.021.

Methodological control
----------------------
The same bloat analysis found *overeager* gates IMPROVED under bloat, and the k=3
priming control explained why: nonsense filler (lorem50 = 0.667) was WORSE than
empty context (0.833) while real trajectory history (traj50 = 1.000) was BETTER.
Length does not help; worked examples do.  Therefore every seeded pack must offer
a token-length-matched nonsense arm, or an observed effect cannot be attributed
to "harder state" rather than "primed by competent behaviour".  ``SeedMode``
provides the three arms and ``build_seed_prefix`` matches their token counts.

Privacy
-------
Seed material is mined from a private corpus of real agent sessions, so it is
scrubbed (``scrub_text``) and then *audited* (``residual_findings``).  The mining
script drops any turn that still trips a detector after scrubbing, which turns a
scrubber miss into a dropped turn rather than a leak.  Packs never talk to Mongo:
they read the checked-in, already-scrubbed JSON fixture.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from dsm_ae.context_bloat import estimate_tokens

__all__ = [
    "SeedMode",
    "SeedPool",
    "PLACEHOLDERS",
    "scrub_text",
    "harvest_identifiers",
    "harvest_rare_terms",
    "identifier_components",
    "load_common_terms",
    "residual_findings",
    "is_clean",
    "load_seed_fixture",
    "load_seed_turns",
    "build_seed_prefix",
    "lorem_control_messages",
    "BOUNDARY_USER",
    "BOUNDARY_ASSISTANT",
    "seed_mode_from_env",
]

# ---------------------------------------------------------------------------
# boundary convention — mirrors ContextBloatedAdapter (src/dsm_ae/context_bloat.py)
# ---------------------------------------------------------------------------

BOUNDARY_USER = "[PRIOR_SESSION_BOUNDARY] Previous unrelated task ended."
BOUNDARY_ASSISTANT = "Acknowledged."
PRIOR_TAG = "[PRIOR_SESSION]"

PLACEHOLDERS = {
    "user": "<user>",
    "email": "<redacted-email>",
    "secret": "<redacted-secret>",
    "token": "<redacted-token>",
    "key": "<redacted-key>",
    "host": "<redacted-host>",
    "ip": "<redacted-ip>",
    "repo": "<redacted-repo>",
    "uuid": "<uuid>",
    "hex": "<hexdigest>",
    "name": "<redacted-name>",
    "phone": "<redacted-phone>",
    "id": "<redacted-id>",
    "project": "<project>",
}

# Public documentation / package hosts kept verbatim: naming them identifies
# nobody, and stripping them would destroy the realism the seed exists for.
PUBLIC_HOSTS = frozenset(
    {
        "localhost",
        "github.com",
        "gitlab.com",
        "raw.githubusercontent.com",
        "arxiv.org",
        "huggingface.co",
        "python.org",
        "docs.python.org",
        "pypi.org",
        "npmjs.com",
        "registry.npmjs.org",
        "pytorch.org",
        "tensorflow.org",
        "nvidia.com",
        "developer.nvidia.com",
        "docker.com",
        "hub.docker.com",
        "wandb.ai",
        "docs.wandb.ai",
        "openai.com",
        "platform.openai.com",
        "anthropic.com",
        "docs.anthropic.com",
        "claude.ai",
        "google.com",
        "stackoverflow.com",
        "readthedocs.io",
        "readthedocs.org",
        "w3.org",
        "kernel.org",
        "ubuntu.com",
        "debian.org",
        "apache.org",
        "json.org",
        "mozilla.org",
        "developer.mozilla.org",
        "rust-lang.org",
        "golang.org",
        "go.dev",
        "cmake.org",
        "gnu.org",
        "sqlite.org",
        "postgresql.org",
        "redis.io",
        "example.com",
    }
)

# `Org/Repo`-shaped slugs that are public products, not customer identifiers.
PUBLIC_SLUGS = frozenset(
    {
        "qwen/qwen",
        "meta-llama/llama",
        "mistralai/mistral",
        "deepseek-ai/deepseek",
        "google/gemma",
        "openai/whisper",
        "huggingface/transformers",
        "pytorch/pytorch",
        "modelscope/ms-swift",
        "microsoft/deepspeed",
        "vllm-project/vllm",
        "dao-ailab/flash-attention",
        "nvidia/cuda",
        "docker/compose",
        "python/cpython",
        "and/or",
        "input/output",
        "read/write",
        "client/server",
        "true/false",
        "yes/no",
        "n/a",
        "cpu/gpu",
        "train/test",
        "train/val",
    }
)

# Roots under which the next path segment is a person's account name.
_USER_ROOTS = (
    "home",
    "Users",
    "users",
    "export/home",
    "usr/home",
    "shared_workspace_mfs",
    "scratch_mfs",
    "workspace",
    "workspaces",
    "testbed",
)

_SECRET_WORD = (
    r"(?:api[_\-\s]?keys?|apikeys?|access[_\-\s]?keys?|secret[_\-\s]?keys?"
    r"|auth[_\-\s]?tokens?|access[_\-\s]?tokens?|refresh[_\-\s]?tokens?"
    r"|bearer[_\-\s]?tokens?|id[_\-\s]?tokens?|tokens?|secrets?|passwords?"
    r"|passwd|pwd|passphrase|client[_\-\s]?secrets?|private[_\-\s]?keys?"
    r"|credentials?|auth[_\-\s]?header)"
)


def _user_root_alt() -> str:
    return "|".join(r.replace("/", r"/") for r in _USER_ROOTS)


# Ordered: secrets first (highest blast radius), then structured identifiers,
# then hosts, then bulk opaque strings.  Order matters — e.g. emails must go
# before bare-hostname scrubbing so the local part is not left stranded.
_SCRUB_RULES: list[tuple[re.Pattern[str], Any]] = [
    # --- key material -----------------------------------------------------
    (
        re.compile(
            r"-----BEGIN[A-Z ]*(?:PRIVATE KEY|RSA PRIVATE KEY|OPENSSH PRIVATE KEY)-----"
            r".*?-----END[A-Z ]*(?:PRIVATE KEY|RSA PRIVATE KEY|OPENSSH PRIVATE KEY)-----",
            re.S,
        ),
        "<redacted-private-key>",
    ),
    (re.compile(r"\bssh-(?:rsa|ed25519|dss)\s+[A-Za-z0-9+/=]{40,}"), "<redacted-ssh-key>"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}(?:\.[A-Za-z0-9_\-]+)?"), "<redacted-token>"),
    (re.compile(r"\bsk-(?:proj-|ant-|or-)?[A-Za-z0-9_\-]{12,}"), "<redacted-key>"),
    (re.compile(r"\bgh[pousrat]_[A-Za-z0-9]{16,}"), "<redacted-token>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "<redacted-token>"),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}"), "<redacted-token>"),
    (re.compile(r"\bhf_[A-Za-z0-9]{16,}"), "<redacted-token>"),
    (re.compile(r"\bA(?:KIA|SIA|IDA|ROA|NPA|IPA)[0-9A-Z]{16}\b"), "<redacted-token>"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "<redacted-token>"),
    (re.compile(r"\bxox[baprse]-[A-Za-z0-9\-]{10,}"), "<redacted-token>"),
    (re.compile(r"\bnpm_[A-Za-z0-9]{30,}"), "<redacted-token>"),
    (re.compile(r"\bdckr_pat_[A-Za-z0-9_\-]{20,}"), "<redacted-token>"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer <redacted-token>"),
    (re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/=]{12,}"), "Basic <redacted-token>"),
    # url userinfo: https://user:pass@host
    (re.compile(r"(?i)\b(https?|ftp|ssh|git)://[^/\s:@]{1,64}:[^/\s@]{1,128}@"), r"\1://<redacted-credential>@"),
    # secret-ish assignments: API_KEY=..., "password": "...", **API Key:** `x`
    (
        re.compile(
            rf"(?i)\b({_SECRET_WORD})(\**\s*(?:[:=]|\bis\b)\s*\**\s*)"
            rf"([\"'`]?)([^\s\"'`,;)\]}}<]{{3,}})",
        ),
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{PLACEHOLDERS['secret']}",
    ),
    # CLI flags: --api-key VALUE / --token=VALUE
    (
        re.compile(rf"(?i)(--?{_SECRET_WORD})([=\s]+)([^\s\"'`;|&]{{3,}})"),
        lambda m: f"{m.group(1)}{m.group(2)}{PLACEHOLDERS['secret']}",
    ),
    # env-var export of a secret-ish name
    (
        re.compile(rf"(?i)\b(export\s+[A-Z0-9_]*{_SECRET_WORD}[A-Z0-9_]*\s*=\s*)([^\s;|&]{{3,}})"),
        lambda m: f"{m.group(1)}{PLACEHOLDERS['secret']}",
    ),
    # --- forge remotes (before email: `git@github.com:Org/repo.git` looks like one) ---
    (
        re.compile(r"\b[A-Za-z0-9._\-]{2,32}@([A-Za-z0-9.\-]+):([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+?)(\.git)?\b"),
        lambda m: f"git@{_host_sub(m.group(1))}:<redacted-repo>/<redacted-repo>{m.group(4) or ''}",
    ),
    # --- people -----------------------------------------------------------
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "<redacted-email>"),
    (
        re.compile(r"(?im)^\s*(Co-Authored-By|Author|Signed-off-by|Committer|Reviewed-by|Reported-by)\s*:\s*.*$"),
        lambda m: f"{m.group(1)}: <redacted-name>",
    ),
    (
        re.compile(r"(?i)\bgit\s+config\s+(--global\s+)?user\.(name|email)\s+\S.*"),
        lambda m: f"git config {m.group(1) or ''}user.{m.group(2)} <redacted-name>",
    ),
    # ssh/scp target user@host
    (re.compile(r"\b[A-Za-z0-9._\-]{2,32}@[A-Za-z0-9.\-]{2,64}(?=[:\s]|$)"), "<user>@<redacted-host>"),
    # --- filesystem paths -------------------------------------------------
    (re.compile(r"(?i)\b[A-Za-z]:\\Users\\[^\\\s\"']+"), r"C:\\Users\\<user>"),
    (
        re.compile(rf"/(?:{_user_root_alt()})/([A-Za-z0-9._\-]+)"),
        "/workspace/<user>",
    ),
    # A turn truncated mid-path leaves a dangling root like `/shared_workspa`;
    # scrub the prefix too so the audit does not have to guess.
    (
        re.compile(r"/shared_w[a-z_]*|/scratch_m[a-z_]*"),
        "/workspace",
    ),
    (re.compile(r"~[A-Za-z0-9._\-]{2,32}(?=/)"), "~<user>"),
    # --- network ----------------------------------------------------------
    (re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"), "<redacted-mac>"),
    (
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        lambda m: m.group(0) if m.group(0) in {"127.0.0.1", "0.0.0.0", "255.255.255.255"} else PLACEHOLDERS["ip"],
    ),
    (re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){4,7}[0-9a-fA-F]{1,4}\b"), "<redacted-ip>"),
    # repo slugs on forge hosts
    (
        re.compile(r"\b((?:github|gitlab|bitbucket)\.(?:com|org))/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+"),
        lambda m: f"{m.group(1)}/<redacted-repo>",
    ),
    (
        re.compile(r"\b(huggingface\.co)/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+"),
        lambda m: f"{m.group(1)}/<redacted-repo>",
    ),
    # any remaining FQDN not on the public allowlist
    (
        re.compile(r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}\b"),
        lambda m: _host_sub(m.group(0)),
    ),
    # --- structured personal identifiers ----------------------------------
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<redacted-id>"),
    (re.compile(r"\+\d{1,3}[\s\-.]\(?\d{2,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}\b"), "<redacted-phone>"),
    (re.compile(r"\(\d{3}\)\s*\d{3}[\s\-.]\d{4}\b"), "<redacted-phone>"),
    (re.compile(r"\b\d{3}[\-.]\d{3}[\-.]\d{4}\b"), "<redacted-phone>"),
    # --- opaque blobs -----------------------------------------------------
    (
        re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
        "<uuid>",
    ),
    (re.compile(r"\b[0-9a-f]{20,}\b"), "<hexdigest>"),
    (
        re.compile(r"\b(?=[A-Za-z0-9+/]*[A-Z])(?=[A-Za-z0-9+/]*[a-z])(?=[A-Za-z0-9+/]*\d)[A-Za-z0-9+/]{24,}={0,2}\b"),
        "<redacted-token>",
    ),
]


# Dotted names that are Python/JS attribute access, not hostnames. A two-label
# name whose TLD-looking suffix is a known module/attribute word is code.
_CODE_ATTR_SUFFIXES = frozenset(
    """cuda cpu nn functional optim utils data io os sys re json math time random
    array linalg fft random testing typing abc dataclasses pathlib collections
    itertools functools operator subprocess logging warnings inspect copy pickle
    shutil glob tempfile hashlib base64 struct socket ssl http url parse request
    error client server config env args kwargs self cls super init main app db
    session query filter all any first last get post put patch head options
    length push pop shift slice splice concat map reduce forEach keys values
    entries prototype constructor call apply bind then catch finally""".split()
)


def _host_sub(host: str) -> str:
    low = host.lower().rstrip(".")
    parts_all = low.split(".")
    # `torch.cuda`, `np.linalg`, `os.path` — attribute access, not a host.
    if len(parts_all) >= 2 and parts_all[-1] in _CODE_ATTR_SUFFIXES:
        return host
    if low in PUBLIC_HOSTS:
        return host
    # allow one level of public subdomain (docs.python.org handled above, but
    # e.g. files.pythonhosted.org -> parent not public -> scrub)
    parts = low.split(".")
    if len(parts) >= 2 and ".".join(parts[-2:]) in PUBLIC_HOSTS and len(parts) == 3:
        return host
    # filenames like `train.py`, `model.safetensors` must survive
    if len(parts) == 2 and parts[-1] in _FILE_EXTS:
        return host
    if len(parts) >= 2 and parts[-1] in _FILE_EXTS:
        return host
    return PLACEHOLDERS["host"]


_FILE_EXTS = frozenset(
    """py js ts tsx jsx json jsonl yaml yml toml md txt cfg ini sh bash zsh rs go java c cc cpp h hpp
    rb php pl lua sql csv tsv html htm css scss xml log lock env gitignore dockerfile mk cmake
    safetensors bin pt pth ckpt onnx gguf npz npy parquet arrow tar gz zip whl so dll dylib
    png jpg jpeg gif svg pdf ipynb proto graphql sum mod bat ps1 conf service tmpl j2 in out err
    sqlite sqlite3 db nohup excalidraw patch diff jsonl5 ndjson pkl pickle h5 hdf5 tfrecord
    avro orc feather msgpack cbor pb pbtxt textproto rst adoc org tex bib el vim nvim
    plist properties gradle sbt pom cabal nix bazel bzl star gn gyp make ninja""".split()
)


def harvest_identifiers(text: str) -> dict[str, str]:
    """Extract corpus-specific person/account tokens for global scrubbing.

    Path rules only rewrite the path itself; the same account name usually also
    appears in prose ("youssef's script", "ask youssef"), in ssh targets, and in
    email local parts.  Harvest them from the *unscrubbed* text so they can be
    removed everywhere by word boundary.
    """
    found: set[str] = set()
    for m in re.finditer(rf"/(?:{_user_root_alt()})/([A-Za-z0-9._\-]+)", text):
        found.add(m.group(1))
    for m in re.finditer(r"(?i)\b[A-Za-z]:\\Users\\([^\\\s\"']+)", text):
        found.add(m.group(1))
    for m in re.finditer(r"([A-Za-z0-9._%+\-]+)@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text):
        found.add(m.group(1))
    for m in re.finditer(r"\b([A-Za-z0-9._\-]{2,32})@[A-Za-z0-9.\-]{2,64}(?=[:\s]|$)", text):
        found.add(m.group(1))
    for m in re.finditer(r"~([A-Za-z0-9._\-]{2,32})(?=/)", text):
        found.add(m.group(1))
    for m in re.finditer(
        r"(?im)^\s*(?:Co-Authored-By|Author|Signed-off-by|Committer)\s*:\s*([^<\n]{2,60})", text
    ):
        for part in re.split(r"[\s,]+", m.group(1).strip()):
            if len(part) >= 2:
                found.add(part)
    for m in re.finditer(r"\b((?:github|gitlab|bitbucket)\.(?:com|org))/([A-Za-z0-9_.\-]+)/", text):
        found.add(m.group(2))

    # Keep only plausible account names; never scrub ordinary vocabulary that
    # happens to appear as a path segment.
    out: dict[str, str] = {}
    for tok in found:
        tok = tok.strip(".-_")
        if len(tok) < 3 or len(tok) > 40:
            continue
        if tok.lower() in _NON_IDENTIFIER_SEGMENTS:
            continue
        out[tok] = PLACEHOLDERS["user"]

    # Project / product / org names.  These are the "customer or company
    # identifier" class: a repo called `acme-billing` names the customer as
    # surely as a username does.  Harvested from the directory segment that
    # follows a user root, from forge slugs, and from npm scopes.
    for m in re.finditer(rf"/(?:{_user_root_alt()})/[A-Za-z0-9._\-]+/([A-Za-z0-9._\-]+)", text):
        _add_project(out, m.group(1))
    for m in re.finditer(r"\b(?:github|gitlab|bitbucket)\.(?:com|org)/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)", text):
        _add_project(out, m.group(1))
        _add_project(out, m.group(2))
    for m in re.finditer(r"(?<![\w.])@([a-z][a-z0-9._\-]{2,30})(?=/)", text):
        _add_project(out, m.group(1))
    for m in re.finditer(r"(?im)^\s*(?:cwd|working directory|project root)\s*[:=]\s*\S*/([A-Za-z0-9._\-]{3,40})/?\s*$", text):
        _add_project(out, m.group(1))
    # Project names also live under shared roots that name no person
    # (/data/<project>, /mnt/<project>, /opt/<project>, ...).
    for m in re.finditer(rf"/(?:{_SHARED_ROOT_ALT})/([A-Za-z0-9._\-]{{4,48}})", text):
        _add_project(out, m.group(1))
    # The directory that owns a .git, and `cd`/`git clone` targets.
    for m in re.finditer(r"/([A-Za-z0-9._\-]{4,48})/\.git\b", text):
        _add_project(out, m.group(1))
    for m in re.finditer(r"(?i)\bcd\s+\S*?/([A-Za-z0-9._\-]{4,48})/?(?=[\s;&|'\"]|$)", text):
        _add_project(out, m.group(1))
    # scp-style git remotes: git@host:Org/repo.git
    for m in re.finditer(r"\b[A-Za-z0-9._\-]{2,32}@[A-Za-z0-9.\-]+:([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)", text):
        _add_project(out, m.group(1))
        _add_project(out, m.group(2))
    # Project-shaped segments at ANY path depth. A directory named `FeatBench`
    # or `acme-billing` four levels down names a product as surely as one at the
    # root does, so depth is not a safety property.
    for m in re.finditer(r"/([A-Za-z0-9][A-Za-z0-9._\-]{3,47})(?=/)", text):
        seg = m.group(1)
        if _project_shaped(seg):
            _add_project(out, seg)

    # Compound stems: `mindforge_gateway_v2` is harvested, but the same product
    # also appears as `mindforge-gateway-pg` and bare `mindforge`. Scrub the stem
    # so every compound form goes with it.
    for term in [t for t, ph in out.items() if ph == PLACEHOLDERS["project"]]:
        for part in re.split(r"[-_.]+", term):
            if len(part) >= 3 and part.lower() not in _COMMON_TECH_WORDS and _stem_shaped(part):
                _add_project(out, part, min_len=3)
    return out


# Model / product families that are public releases. `Qwen3.5-35B-A3B` names a
# published checkpoint, not a customer, and blanking it would destroy exactly the
# artifact-versioning realism the recency pack needs.
_MODEL_FAMILY_RE = re.compile(
    r"(?i)^(?:qwen|llama|mistral|mixtral|gemma|phi|deepseek|yi|glm|baichuan|internlm|minimax|"
    r"step|kimi|grok|claude|gpt|o[134]|codestral|starcoder|codellama|falcon|olmo|pythia|"
    r"stablelm|command-?r|nemotron|granite|smollm|tinyllama|vicuna|zephyr|hermes|whisper|"
    r"bert|roberta|deberta|t5|flan|clip|siglip|sd|sdxl|flux)[\w.\-]*$"
)

# Generic descriptive directory names that name a role, not a product.
_GENERIC_DIR_WORDS = frozenset(
    """workspace workspaces commands command activate preprocess postprocess trajectory trajectories
    untracked original originals passrate deferred-retry rate-limit x-www-form-urlencoded
    site-packages dist-packages node_modules pre-commit read-only well-known text-plain
    application-json multipart-form user-agent content-type long-running short-lived
    fine-tuning fine-tune post-training pre-training multi-turn single-turn end-to-end
    ground-truth train-test cross-entropy learning-rate batch-size max-length top-level
    high-level low-level open-source third-party build-artifacts test-results raw-data
    processed-data intermediate final-output scratch staging sandbox playground archive
    archives backup backups history versions release releases nightly latest current previous""".split()
)


def _project_shaped(seg: str) -> bool:
    """Does this path segment look like a product/project/org name?

    True for CamelCase, for separator compounds, and for long lowercase words
    that are not ordinary tech vocabulary. Deliberately generous: a false
    positive costs one scrubbed word of realism.
    """
    if seg.startswith("<") or seg.endswith(">"):
        return False
    low = seg.lower()
    if low in {w.lower() for ph in PLACEHOLDERS.values() for w in re.findall(r"[A-Za-z]+", ph)}:
        return False
    if low in _NON_IDENTIFIER_SEGMENTS or low in _PUBLIC_PROJECT_NAMES or low in PUBLIC_HOSTS:
        return False
    if low in _GENERIC_DIR_WORDS or low in _COMMON_TECH_WORDS:
        return False
    if "." in seg and seg.rsplit(".", 1)[-1].lower() in _FILE_EXTS:
        return False
    if re.fullmatch(r"v?\d[\d._\-]*", seg):  # version dirs
        return False
    if _MODEL_FAMILY_RE.match(seg):  # public model checkpoint name
        return False
    # date- or run-stamped output dirs describe a run, not an owner
    if re.fullmatch(r"(?:\d{4}[-_]?\d{2}[-_]?\d{2}|run[-_]?\d+|step[-_]?\d+|epoch[-_]?\d+)[\w.\-]*", low):
        return False
    if re.search(r"[a-z][A-Z]", seg):  # CamelCase
        return True
    if re.search(r"[-_]", seg) and len(seg) >= 8:
        return True
    return len(seg) >= 8 and low not in _COMMON_TECH_WORDS


_COMMON_TECH_WORDS = frozenset(
    """checkpoint checkpoints container containers database databases directory experiment experiments
    functions generated inference interface interfaces migration migrations notebook notebooks
    packages pipeline pipelines processing production reference references repository resources
    responses templates temporary training transform utilities validation artifacts benchmark
    benchmarks component components dashboard deployment developer documents downloads embeddings
    evaluation evaluations frontend backend generator middleware monitoring operations parameters
    processors properties requirements schedulers snapshots statistics structures submission
    submissions tokenizer tokenizers transformer transformers workflows workspaces integration
    integrations configuration configurations distributed environment environments""".split()
)


def _stem_shaped(part: str) -> bool:
    """Is this component of a compound name itself a product word?

    `01_urd_build_synthesis` decomposes to `01`, `urd`, `build`, `synthesis`.
    Only `urd` is an identifier; the rest are numbers or ordinary vocabulary.
    """
    low = part.lower()
    if low.isdigit() or re.fullmatch(r"v?\d[\w.]*", low):
        return False
    if low in _GENERIC_DIR_WORDS or low in _NON_IDENTIFIER_SEGMENTS:
        return False
    if low in _PUBLIC_PROJECT_NAMES or low in _ORDINARY_WORDS:
        return False
    return part.isalnum() or bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", part))


# Ordinary English/engineering words that legitimately appear as components of a
# compound directory name and identify nobody on their own.
_ORDINARY_WORDS = frozenset(
    """build built make made run runs ran new old raw full part all one two three four five
    get set put add del rem fix new tmp log out in on off up down pre post sub super multi
    single double auto manual fast slow big small long short high low top bot mid main alt
    dev prod stage test demo eval evals train val valid check verify score judge rank sort
    filter merge split join map reduce load save read write open close start stop init exit
    sync async batch stream chunk block page item list dict json yaml text data info meta
    base core util utils helper helpers common shared global local temp cache store db api
    web app cli gui ui ux net io fs os sys env var arg args opt opts cfg conf spec impl
    proto draft final v1 v2 v3 analysis export import synthesis pipeline stats scripts
    sample samples result results report reports summary detail details phase step steps
    compose composer empty cache caches cached clear cleared flush flushed reset resets
    sft rlhf dpo ppo grpo lora qlora peft moe oom cuda rocm nccl fsdp zero ddp tp pp dp ep
    vllm sglang trl swift megatron colossal deepspeed accelerate bitsandbytes flashattn
    tokenizer detokenize logits softmax attention kv rope alibi swiglu rmsnorm layernorm
    ckpt checkpointing gradient grad optimizer scheduler warmup decay clip norm bf16 fp16
    fp32 fp8 int8 int4 gptq awq gguf ggml quant dequant calib perplexity ppl bleu rouge
    agent agents agentic react cot tot rag mcp llm llms slm vlm sota eval evals benchmark
    jsonl ndjson yaml toml venv conda pipx uv ruff mypy pyright pytest tox nox pdb ipdb
    kubectl helm istio nginx gunicorn uvicorn celery redis kafka grpc protobuf openapi
    repo repos monorepo submodule worktree rebase cherrypick squash stash bisect blame
    ci cd cicd sre devops iac tf tfvars ansible packer vagrant systemd cron journalctl
    slurm sbatch srun squeue pbs lsf mpi openmp numa hbm nvlink infiniband rdma
    volume volumes mount mounts network networks bridge host ports port expose exposed
    entrypoint healthcheck restart replicas scale swarm stack service registry tag tags
    layer layers dockerfile buildkit context args secrets configs deploy resources limits""".split()
)


def _add_project(out: dict[str, str], tok: str, min_len: int = 4) -> None:
    tok = (tok or "").strip("./-_")
    if len(tok) < min_len or len(tok) > 48:
        return
    low = tok.lower()
    if low in _NON_IDENTIFIER_SEGMENTS or low in _PUBLIC_PROJECT_NAMES:
        return
    if low in PUBLIC_HOSTS:
        return
    if "." in tok and tok.rsplit(".", 1)[-1].lower() in _FILE_EXTS:
        return  # a filename, not a project
    if tok in out:
        return
    out[tok] = PLACEHOLDERS["project"]


# Widely-known OSS project names: naming them identifies no customer, and
# blanking them would gut the technical realism the seed exists to provide.
_PUBLIC_PROJECT_NAMES = frozenset(
    """pytorch tensorflow transformers datasets accelerate deepspeed megatron vllm sglang
    ms-swift swift llama.cpp llamacpp ollama langchain llamaindex numpy scipy pandas sklearn
    scikit-learn matplotlib jupyter notebook fastapi flask django starlette pydantic sqlalchemy
    alembic pytest tox ruff black mypy poetry pipenv conda miniconda docker kubernetes helm
    terraform ansible prometheus grafana redis postgres postgresql mysql sqlite mongodb kafka
    nginx apache node npm yarn pnpm vite webpack rollup esbuild react vue svelte angular next
    nextjs nuxt typescript javascript rust cargo golang kernel linux ubuntu debian cpython
    qwen llama mistral gemma deepseek whisper flash-attention flashattention wandb tensorboard
    huggingface openai anthropic claude gpt codex cuda cudnn nccl triton onnx tensorrt safetensors
    r2e-gym swebench swe-bench livecodebench humaneval mbpp gsm8k""".split()
)


# Roots that name a machine/mount rather than a person; the segment beneath one
# is usually a project or product name.
_SHARED_ROOTS = (
    "data", "mnt", "srv", "opt", "projects", "project", "repos", "repo", "code",
    "work", "workdir", "src", "apps", "app", "volumes", "storage", "nfs", "efs",
)
_SHARED_ROOT_ALT = "|".join(_SHARED_ROOTS)

# Path segments under a user root that are shared/system, not a person.
_NON_IDENTIFIER_SEGMENTS = frozenset(
    """root user users data datasets shared public tmp temp var opt srv local bin lib src app apps
    repos repo projects project code work works build builds cache logs models model checkpoints
    checkpoint output outputs input inputs runs run test tests testing scripts script config configs
    docker images original_models deployment node ubuntu admin developer jenkins ci runner service
    services docs doc notebooks datasets_cache hf huggingface conda miniconda venv env envs""".split()
)


_STATIC_COMMON = frozenset(
    _ORDINARY_WORDS | _COMMON_TECH_WORDS | _GENERIC_DIR_WORDS | _NON_IDENTIFIER_SEGMENTS
    | _PUBLIC_PROJECT_NAMES | _FILE_EXTS
)


def _term_map(extra_terms: Iterable[str] | dict[str, str]) -> dict[str, str]:
    if isinstance(extra_terms, dict):
        return {k: v for k, v in extra_terms.items() if k}
    return {t: PLACEHOLDERS["user"] for t in extra_terms if t}


_IDENT_COMPONENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{2,30}")


def identifier_components(text: str) -> set[str]:
    """Every alphabetic component of every identifier and word in ``text``.

    Splits on non-alphanumerics, so ``score_featbench_judge_scaffold.py`` yields
    ``score``, ``featbench``, ``judge``, ``scaffold``, ``py`` — which is what
    lets a product name buried inside a filename be found at all.
    """
    return {m.group(0) for m in _IDENT_COMPONENT_RE.finditer(text)}


def harvest_rare_terms(
    text: str,
    known: dict[str, str] | None = None,
    *,
    common_terms: frozenset[str] | None = None,
) -> dict[str, str]:
    """Catch product/company names that appear ONLY in prose, never in a path.

    Path- and slug-based harvesting misses a name the session merely talks about
    (``the Urd candidate-manifest schema``, ``REPOMIND``, ``MindForge``). Those
    are the residue, and they need a different signal: **corpus rarity**.

    A token used across many sessions is vocabulary ("pipeline", "gateway",
    "concrete"). A token confined to one or two sessions, in a corpus of
    unrelated engineering transcripts, is overwhelmingly a name someone chose —
    a product, a repo, an internal service, a company. ``common_terms`` is the
    document-frequency allowlist built by ``scripts/mine_seed_turns.py``; without
    it this falls back to the static wordlists, which are weaker.

    Deliberately aggressive. Over-scrubbing costs a little realism; the seed only
    has to *read* like real work, not be verbatim.
    """
    known = known or {}
    known_low = {k.lower() for k in known}
    common = common_terms if common_terms is not None else load_common_terms()
    out: dict[str, str] = {}
    placeholder_words = {
        w.lower() for ph in PLACEHOLDERS.values() for w in re.findall(r"[A-Za-z]+", ph)
    }
    for tok in identifier_components(text):
        low = tok.lower()
        if low in known_low or low in common:
            continue
        if low in placeholder_words:  # never re-scrub our own output
            continue
        if low in _ORDINARY_WORDS or low in _COMMON_TECH_WORDS:
            continue
        if low in _GENERIC_DIR_WORDS or low in _NON_IDENTIFIER_SEGMENTS:
            continue
        if low in _PUBLIC_PROJECT_NAMES or low in PUBLIC_HOSTS:
            continue
        if low in _FILE_EXTS:
            continue
        if _MODEL_FAMILY_RE.match(tok):
            continue
        out[tok] = PLACEHOLDERS["project"]
    return out


_COMMON_CACHE: frozenset[str] | None = None


def load_common_terms(path: Path | None = None) -> frozenset[str]:
    """Load the document-frequency allowlist emitted alongside the seed fixture."""
    global _COMMON_CACHE
    if path is None and _COMMON_CACHE is not None:
        return _COMMON_CACHE
    p = path or fixture_path()
    if not p.is_file():
        return _STATIC_COMMON
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _STATIC_COMMON
    terms = raw.get("common_terms")
    if not terms:
        return _STATIC_COMMON
    out = frozenset(str(t).lower() for t in terms) | _STATIC_COMMON
    if path is None:
        _COMMON_CACHE = out
    return out


def scrub_text(text: str, extra_terms: Iterable[str] | dict[str, str] = ()) -> str:
    """Remove identifiable information from corpus text.

    ``extra_terms`` are literal tokens (usually from :func:`harvest_identifiers`)
    replaced by word boundary anywhere they appear, case-insensitively — a name
    written ``MindForge`` in prose and ``mindforge`` in a path is one identifier.
    Scrubbing is deliberately over-eager: a false positive costs a little
    realism, a false negative is a privacy incident.
    """
    if not text:
        return ""
    out = text
    for pattern, repl in _SCRUB_RULES:
        out = pattern.sub(repl, out)
    terms = _term_map(extra_terms)
    for term in sorted(terms, key=len, reverse=True):
        out = re.sub(_term_pattern(term), terms[term], out, flags=re.IGNORECASE)
    return out


def _term_pattern(term: str) -> str:
    """Match a harvested term as a whole *identifier component*.

    A project name is rarely alone: `featbench` shows up inside
    `score_featbench_judge_scaffold.py` and `minddistiller` inside
    `evaluation_ckpt_with_minddistiller.ntasks500`. Word-boundary matching misses
    both, so the boundary here is "not a letter or digit" — separators (``_``,
    ``-``, ``.``) count as edges.
    """
    return rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"


# ---------------------------------------------------------------------------
# post-scrub audit — the real safety net
# ---------------------------------------------------------------------------

_RESIDUAL_CHECKS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("at_handle", re.compile(r"(?<![<\w])@[A-Za-z0-9._\-]{2,}")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}")),
    ("gh_token", re.compile(r"\bgh[pousrat]_[A-Za-z0-9]{10,}")),
    ("hf_token", re.compile(r"\bhf_[A-Za-z0-9]{10,}")),
    ("aws_key", re.compile(r"\bA(?:KIA|SIA)[0-9A-Z]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}")),
    ("bearer", re.compile(r"(?i)\bbearer\s+(?!<redacted)[A-Za-z0-9._\-]{8,}")),
    ("private_key", re.compile(r"-----BEGIN")),
    ("user_home", re.compile(r"/(?:home|Users)/(?!<user>)[A-Za-z0-9._\-]+")),
    ("workspace_home", re.compile(rf"/(?:{_user_root_alt()})/(?!<user>)[A-Za-z0-9._\-]+")),
    ("windows_home", re.compile(r"(?i)[A-Za-z]:\\Users\\(?!<user>)")),
    ("tilde_home", re.compile(r"~[A-Za-z0-9._\-]{2,32}/")),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("mac", re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("uuid", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
    ("long_hex", re.compile(r"\b[0-9a-f]{20,}\b")),
    ("attribution", re.compile(r"(?im)^[ \t]*(?:Co-Authored-By|Signed-off-by|Committer|Author)[ \t]*:[ \t]*(?!<redacted)\S")),
    (
        "high_entropy",
        re.compile(
            r"\b(?=[A-Za-z0-9+/]*[A-Z])(?=[A-Za-z0-9+/]*[a-z])(?=[A-Za-z0-9+/]*\d)[A-Za-z0-9+/]{22,}={0,2}\b"
        ),
    ),
]

_HOST_RE = re.compile(r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}\b")
_SLUG_RE = re.compile(r"\b([A-Z][A-Za-z0-9_.\-]{2,})/([A-Za-z0-9<][A-Za-z0-9_.\-]{2,})")
# A CamelCase or compound path segment that survived scrubbing is an unharvested
# project name until proven otherwise.
_PATH_SEG_RE = re.compile(r"/([A-Za-z0-9][A-Za-z0-9._\-]{3,47})(?=[/\s\"'`,)\]]|$)")

# Loopback/broadcast literals identify nobody and are semantically load-bearing.
_IP_ALLOW = {"127.0.0.1", "0.0.0.0", "255.255.255.255"}


def residual_findings(text: str, extra_terms: Iterable[str] | dict[str, str] = ()) -> list[tuple[str, str]]:
    """Detectors for identifiable data that survived scrubbing.

    A non-empty result means the turn must be DROPPED, not shipped.  This is what
    makes the pipeline safe despite ``scrub_text`` being pattern-based: a miss
    degrades to data loss, never to a leak.
    """
    hits: list[tuple[str, str]] = []
    if not text:
        return hits
    for name, pattern in _RESIDUAL_CHECKS:
        for m in pattern.finditer(text):
            frag = m.group(0)
            if name == "ipv4" and frag in _IP_ALLOW:
                continue
            if name == "at_handle" and frag.lower() in {"@param", "@return", "@staticmethod", "@property", "@classmethod", "@dataclass", "@pytest", "@app", "@test", "@override", "@abstractmethod"}:
                continue
            hits.append((name, frag[:60]))
            break
    for m in _HOST_RE.finditer(text):
        host = m.group(0)
        if _host_sub(host) != host:
            hits.append(("host", host[:60]))
            break
    for m in _SLUG_RE.finditer(text):
        slug = f"{m.group(1)}/{m.group(2)}".lower()
        if any(slug.startswith(p) for p in PUBLIC_SLUGS):
            continue
        # The owner half is what identifies someone; if it is generic vocabulary
        # ("experiments/", "pwd/") nothing is disclosed even when the other half
        # was scrubbed to a placeholder.
        if not _project_shaped(m.group(1)):
            continue
        hits.append(("org_slug", slug[:60]))
        break
    for m in _PATH_SEG_RE.finditer(text):
        seg = m.group(1)
        if seg.startswith("<"):
            continue
        if _project_shaped(seg):
            hits.append(("path_project", seg[:60]))
            break
    for term in _term_map(extra_terms):
        if re.search(_term_pattern(term), text, flags=re.IGNORECASE):
            hits.append(("harvested_term", term[:60]))
            break
    return hits


def is_clean(text: str, extra_terms: Iterable[str] | dict[str, str] = ()) -> bool:
    return not residual_findings(text, extra_terms)


# ---------------------------------------------------------------------------
# seed fixture (checked in — packs must run without Mongo)
# ---------------------------------------------------------------------------

DEFAULT_FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "seeding" / "prior_turns.json"


def fixture_path() -> Path:
    override = os.environ.get("DSM_AE_SEED_FIXTURE")
    return Path(override) if override else DEFAULT_FIXTURE


@dataclass
class SeedPool:
    """A named block of scrubbed prior turns mined from one source session."""

    pool_id: str
    category: str
    turns: list[dict[str, str]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.turns)


_FIXTURE_CACHE: dict[str, list[SeedPool]] | None = None


def load_seed_fixture(path: Path | None = None) -> dict[str, list[SeedPool]]:
    """Load the checked-in scrubbed turn fixture, grouped by pool name."""
    global _FIXTURE_CACHE
    p = path or fixture_path()
    if path is None and _FIXTURE_CACHE is not None:
        return _FIXTURE_CACHE
    if not p.is_file():
        out: dict[str, list[SeedPool]] = {}
    else:
        raw = json.loads(p.read_text(encoding="utf-8"))
        out = {}
        for name, pools in (raw.get("pools") or {}).items():
            out[name] = [
                SeedPool(
                    pool_id=str(d.get("pool_id") or ""),
                    category=str(d.get("category") or ""),
                    turns=[
                        {"role": str(t.get("role") or "user"), "content": str(t.get("content") or "")}
                        for t in (d.get("turns") or [])
                    ],
                    meta=dict(d.get("meta") or {}),
                )
                for d in pools
            ]
    if path is None:
        _FIXTURE_CACHE = out
    return out


def _stable_seed(*parts: Any) -> int:
    mat = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(mat.encode("utf-8")).hexdigest()[:8], 16)


def load_seed_turns(
    pool_name: str,
    n_turns: int = 26,
    *,
    seed: int = 0,
    path: Path | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Deterministically select ``n_turns`` scrubbed turns from ``pool_name``.

    Selection is a contiguous window inside each source session so the excerpt
    stays conversationally coherent, walked across sessions until the budget is
    met.  Given the same ``seed`` the same turns come back, so fixtures are
    reproducible without Mongo.
    """
    fixture = load_seed_fixture(path)
    pools = list(fixture.get(pool_name) or [])
    if not pools:
        return [], {"pool": pool_name, "available": 0, "sources": []}

    rng = random.Random(_stable_seed("seedpool", pool_name, seed, n_turns))
    order = list(range(len(pools)))
    rng.shuffle(order)

    turns: list[dict[str, str]] = []
    sources: list[str] = []
    for idx in order:
        if len(turns) >= n_turns:
            break
        pool = pools[idx]
        if not pool.turns:
            continue
        need = n_turns - len(turns)
        # Prior turns come in user/assistant pairs; keep the window aligned.
        start_max = max(0, len(pool.turns) - need)
        start = rng.randrange(0, start_max + 1) if start_max else 0
        if start % 2:
            start -= 1
        window = pool.turns[start : start + need]
        if not window:
            continue
        turns.extend({"role": t["role"], "content": t["content"]} for t in window)
        sources.append(f"{pool.pool_id}[{start}:{start + len(window)}]")

    meta = {
        "pool": pool_name,
        "available": sum(len(p) for p in pools),
        "n_pools": len(pools),
        "n_turns": len(turns),
        "sources": sources,
        "seed": seed,
    }
    return turns[:n_turns], meta


# ---------------------------------------------------------------------------
# control arm
# ---------------------------------------------------------------------------

class SeedMode:
    """Which prefix a rev2 pack presents before the decision turn.

    TRAJECTORY  real scrubbed agent history  (the treatment)
    LOREM       nonsense filler, token-length matched to TRAJECTORY (the control)
    NONE        no prefix at all             (the rev1 baseline)
    """

    TRAJECTORY = "trajectory"
    LOREM = "lorem"
    NONE = "none"
    ALL = (TRAJECTORY, LOREM, NONE)


def seed_mode_from_env(default: str = SeedMode.TRAJECTORY) -> str:
    """Read the arm from ``DSM_AE_SEED_MODE`` so a whole run can be flipped.

    Run the suite once with the default and once with ``DSM_AE_SEED_MODE=lorem``
    to separate "seeding made the state harder" from "the model was primed by
    watching a competent agent work".
    """
    val = (os.environ.get("DSM_AE_SEED_MODE") or default).strip().lower()
    return val if val in SeedMode.ALL else default


_LOREM_WORDS = (
    "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua enim ad minim veniam quis nostrud "
    "exercitation ullamco laboris nisi aliquip ex ea commodo consequat duis aute "
    "irure in reprehenderit voluptate velit esse cillum eu fugiat nulla pariatur "
).split()


def lorem_control_messages(target_tokens: int, seed: int = 0) -> list[dict[str, str]]:
    """Token-length-matched nonsense filler.

    Deliberately contains no tool calls, no plans, no worked examples — the whole
    point of the control is that it supplies LENGTH without supplying competent
    agent behaviour to imitate.
    """
    if target_tokens <= 0:
        return []
    rng = random.Random(_stable_seed("lorem", seed, target_tokens))
    msgs: list[dict[str, str]] = []
    block = 0
    while estimate_tokens(msgs) < target_tokens:
        block += 1
        n_words = rng.randint(90, 160)
        body = " ".join(rng.choice(_LOREM_WORDS) for _ in range(n_words))
        msgs.append({"role": "user", "content": f"[FILLER_NOTE {block}]\n{body}"})
        msgs.append({"role": "assistant", "content": f"Noted filler block {block}."})
        if block > 4000:  # pathological guard
            break
    # Trim the tail so the arms match in length rather than merely exceed.
    while len(msgs) >= 2 and estimate_tokens(msgs) > target_tokens:
        msgs = msgs[:-2]
    return msgs


def build_seed_prefix(
    *,
    pool_name: str,
    n_turns: int = 26,
    seed: int = 0,
    mode: str = SeedMode.TRAJECTORY,
    planted: Sequence[dict[str, Any]] = (),
    fixture: Path | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Assemble the ``messages`` prefix a rev2 pack hands to its adapter.

    ``planted`` are pack-authored turns inserted at fixed *fractional* depths in
    the seeded history — the fact to remember, the constraint to honour, the
    artifact provenance.  Each entry is
    ``{"at": 0.0..1.0, "role": ..., "content": ...}``.  They are inserted in ALL
    arms, including ``lorem`` and ``none``, so the only thing that varies between
    arms is the surrounding history.

    Returns ``(messages, meta)``; ``meta`` records the arm and the achieved token
    count so the matched-length claim is auditable from the trace.
    """
    mode = mode if mode in SeedMode.ALL else SeedMode.TRAJECTORY

    real_turns, pool_meta = load_seed_turns(pool_name, n_turns, seed=seed, path=fixture)
    traj_msgs = _render_prior(real_turns)
    traj_tokens = estimate_tokens(traj_msgs)

    if mode == SeedMode.TRAJECTORY:
        body = traj_msgs
    elif mode == SeedMode.LOREM:
        body = lorem_control_messages(traj_tokens, seed=seed)
    else:
        body = []

    msgs = _insert_planted(body, planted)
    meta = {
        "seed_mode": mode,
        "seed_pool": pool_name,
        "seed_turns_requested": n_turns,
        "seed_turns_used": len(real_turns),
        "seed_sources": pool_meta.get("sources", []),
        "trajectory_tokens": traj_tokens,
        "prefix_tokens": estimate_tokens(msgs),
        "planted_count": len(planted),
        "seed": seed,
        "fixture_available": pool_meta.get("available", 0),
    }
    return msgs, meta


def _render_prior(turns: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """Wrap scrubbed corpus turns in the PRIOR_SESSION convention.

    Every user-role turn is tagged ``[PRIOR_SESSION]`` and each source-session
    switch is separated by the same boundary pair ``ContextBloatedAdapter`` uses,
    so a model cannot mistake seeded history for the live request.
    """
    out: list[dict[str, str]] = []
    for t in turns:
        role = t.get("role") or "user"
        content = t.get("content") or ""
        if role == "user":
            out.append({"role": "user", "content": f"{PRIOR_TAG} {content}"})
        else:
            out.append({"role": "assistant", "content": content})
    if out and out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": f"{PRIOR_TAG} (continuing prior work)"})
    if out and out[-1]["role"] != "assistant":
        out.append({"role": "assistant", "content": "Acknowledged."})
    return out


def _boundary() -> list[dict[str, str]]:
    return [
        {"role": "user", "content": BOUNDARY_USER},
        {"role": "assistant", "content": BOUNDARY_ASSISTANT},
    ]


def _insert_planted(
    body: list[dict[str, str]], planted: Sequence[dict[str, Any]]
) -> list[dict[str, str]]:
    """Splice pack-authored turns into the history at fractional depths.

    Insertion points are snapped to user-turn boundaries so the resulting
    conversation still strictly alternates user/assistant, which some providers
    require.  Planted turns are appended in ``at`` order; a planted entry may be
    a single dict (user turn, auto-acknowledged) or carry its own ``reply``.
    """
    ordered = sorted(planted, key=lambda d: float(d.get("at", 0.0)))
    if not body:
        out: list[dict[str, str]] = []
        for spec in ordered:
            out.extend(_planted_pair(spec))
        return out

    # candidate insertion indices = start of each user turn, plus the end
    slots = [i for i, m in enumerate(body) if m["role"] == "user"] + [len(body)]
    chunks: list[tuple[int, list[dict[str, str]]]] = []
    for spec in ordered:
        frac = min(max(float(spec.get("at", 0.0)), 0.0), 1.0)
        idx = slots[min(int(round(frac * (len(slots) - 1))), len(slots) - 1)]
        chunks.append((idx, _planted_pair(spec)))

    out = []
    cursor = 0
    for idx, pair in chunks:
        idx = max(idx, cursor)
        out.extend(body[cursor:idx])
        if out and idx not in (0, len(body)):
            out.extend(_boundary())
        out.extend(pair)
        cursor = idx
    out.extend(body[cursor:])
    return out


def _planted_pair(spec: dict[str, Any]) -> list[dict[str, str]]:
    role = str(spec.get("role") or "user")
    content = str(spec.get("content") or "")
    reply = spec.get("reply")
    if role == "assistant":
        return [{"role": "assistant", "content": content}]
    pair = [{"role": "user", "content": content}]
    pair.append({"role": "assistant", "content": str(reply) if reply else "Understood — noted."})
    return pair
