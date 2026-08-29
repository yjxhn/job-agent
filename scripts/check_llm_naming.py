#!/usr/bin/env python3
"""Fail CI if agent_core/llm/ contains provider names NOT declared in config.yaml.

The single source of truth for the active LLM provider is `llm.provider` in
config.yaml (currently `deepseek`). Any other model/vendor name found in
agent_core/llm/ — in code, comments, log strings, or URLs — is residue from
copy-pasted code from another model and must be rejected.

Allowed names are derived from the declared provider plus a small allowlist of
generic SDK vocabulary that is provider-agnostic (e.g. "openai" refers to the
SDK package, not the OpenAI provider).

Exit 0 = clean, Exit 1 = banned name found (prints offenders).

Usage:
    python scripts/check_llm_naming.py
    python scripts/check_llm_naming.py --config config.yaml --pkg agent_core/llm
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Names that must NEVER appear in agent_core/llm/ regardless of config.
# These are foreign model/vendor identifiers that have historically leaked in.
BANNED_ALWAYS = [
    r"glm[-_.]?5[-_.]?2",  # GLM-5.2 / glm_5_2 / glm-5.2 / glm5.2 — Zhipu model name
    r"\bclaude\b",  # Anthropic model family
    r"\banthropic\b",  # Anthropic vendor
    r"\bgpt[-_]?\d\b",  # GPT-3 / GPT-4 / gpt4
    r"\bgpt\b",  # bare GPT
    r"api\.glm-5\.2\.com",  # foreign endpoint URL
    r"api\.openai\.com",  # OpenAI endpoint (we use deepseek)
]

# Words that LOOK like vendor names but are legitimate SDK / generic vocabulary.
# These are matched case-insensitively against whole words and skipped.
ALLOWLIST_CONTEXTS = {
    # "openai" the SDK package is fine (AsyncOpenAI, openai SDK). The OpenAI
    # *endpoint* api.openai.com is still banned above.
    "openai",
}


def load_declared_provider(config_path: Path) -> str:
    """Read llm.provider from config.yaml (minimal parse, no pyyaml needed)."""
    if not config_path.exists():
        print(f"warn: config not found at {config_path}, assuming 'deepseek'", file=sys.stderr)
        return "deepseek"
    in_llm = False
    for raw in config_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # top-level key
        if not line.startswith(" ") and stripped.endswith(":"):
            in_llm = stripped[:-1] == "llm"
            continue
        if in_llm and stripped.startswith("provider:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return "deepseek"


def scan(pkg_dir: Path) -> list[tuple[Path, int, str, str]]:
    """Return list of (file, lineno, matched_text, line) for banned names."""
    offenders: list[tuple[Path, int, str, str]] = []
    patterns = [re.compile(p, re.IGNORECASE) for p in BANNED_ALWAYS]
    for py in pkg_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), start=1):
            for pat in patterns:
                for m in pat.finditer(line):
                    word = m.group(0).lower()
                    # Allow bare "openai" when it refers to the SDK, not a vendor
                    # claim. We still ban api.openai.com (caught by its pattern).
                    if word in ALLOWLIST_CONTEXTS:
                        continue
                    offenders.append((py, lineno, m.group(0), line.strip()))
    return offenders


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--pkg", default="agent_core/llm")
    args = ap.parse_args()

    config_path = Path(args.config)
    pkg_dir = Path(args.pkg)

    if not pkg_dir.is_dir():
        print(f"error: package dir not found: {pkg_dir}", file=sys.stderr)
        return 2

    provider = load_declared_provider(config_path)
    print(f"Declared provider in {config_path}: {provider!r}")
    print(f"Scanning {pkg_dir} for banned model/vendor names...")

    offenders = scan(pkg_dir)
    if not offenders:
        print("OK: no banned provider names found.")
        return 0

    print(f"\nFAIL: {len(offenders)} banned name(s) found:\n")
    for f, lineno, matched, line in offenders:
        print(f"  {f}:{lineno}: '{matched}'")
        print(f"    {line}")
    print(
        "\nRemediation: agent_core/llm/ must reference only the provider "
        f"declared in config.yaml ({provider!r}). "
        "Foreign model names (glm-5.2/claude/gpt/anthropic) are residue from "
        "copy-pasted code and must be removed or renamed."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
