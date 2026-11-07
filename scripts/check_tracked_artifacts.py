"""Fail CI for tracked demo artifacts or obvious credentials, without printing values."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".gguf", ".safetensors", ".pt", ".pth", ".bin"}
FORBIDDEN_PARTS = {".demo", ".venv", "node_modules", "dist", "uploads", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".md", ".yml", ".yaml", ".json", ".html", ".css", ".toml", ".ps1", ".txt", ".example"}
KEY_PATTERNS = (
    ("possible API key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("nonempty DeepSeek assignment", re.compile(r"^\s*DEEPSEEK_API_KEY\s*=\s*[^\s#]+", re.I)),
)


def check(paths: list[Path]) -> list[str]:
    problems = []
    for relative in paths:
        if relative.is_absolute() or ".." in relative.parts:
            problems.append(f"{relative}: unsafe tracked path")
            continue
        lowered = [part.lower() for part in relative.parts]
        name = lowered[-1]
        if any(part in FORBIDDEN_PARTS for part in lowered[:-1]) or relative.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(f"{relative}: forbidden generated or model artifact")
            continue
        if (name == ".env" or name.startswith(".env.")) and name != ".env.example":
            problems.append(f"{relative}: private environment file")
            continue
        if relative.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = (ROOT / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            problems.append(f"{relative}: cannot inspect tracked text file")
            continue
        for number, line in enumerate(content.splitlines(), 1):
            for label, pattern in KEY_PATTERNS:
                if pattern.search(line):
                    problems.append(f"{relative}:{number}: {label}")
    return problems


def main() -> int:
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=ROOT, check=True, capture_output=True)
    paths = [Path(path.decode("utf-8")) for path in result.stdout.split(b"\0") if path]
    problems = check(paths)
    for problem in problems:
        print(f"FAIL: {problem}")
    if problems:
        return 1
    print(f"PASS: inspected {len(paths)} tracked or candidate files; no forbidden artifacts or obvious keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
