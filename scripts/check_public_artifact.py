from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ is None:  # Support both `python scripts/...` and `python -m scripts...`.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkaggle_leaderboard.settings import (
    credential_secret_values,
    parse_api_tokens,
    parse_legacy_credentials,
)


TEXT_SUFFIXES = {".html", ".css", ".js", ".json", ".txt", ".xml", ".svg"}
FORBIDDEN_SUFFIXES = {".csv", ".env", ".key", ".log", ".zip"}
FORBIDDEN_MARKERS = (
    b"KAGGLE_API_TOKEN",
    b"KAGGLE_API_TOKENS",
    b"KAGGLE_LEGACY_CREDENTIALS",
    b"KAGGLE_USERNAME",
    b"KAGGLE_KEY",
    b"TeamMemberUserNames",
    b"Authorization: Bearer",
    b"/.kaggle/",
    b"\\.kaggle\\",
)


def scan(
    paths: list[Path],
    api_tokens: str | list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    findings: list[str] = []
    if isinstance(api_tokens, str):
        token_values = (api_tokens,)
    else:
        token_values = tuple(api_tokens or ())
    token_bytes = tuple(
        token.encode("utf-8") for token in token_values if len(token) >= 8
    )

    files: list[Path] = []
    for path in paths:
        if path.is_symlink():
            findings.append(f"symbolic link is not allowed: {path}")
        elif path.is_dir():
            for item in path.rglob("*"):
                if item.is_symlink():
                    findings.append(f"symbolic link is not allowed: {item}")
                elif item.is_file():
                    files.append(item)
        elif path.is_file():
            files.append(path)
        else:
            findings.append(f"missing path: {path}")

    for file_path in files:
        suffix = file_path.suffix.casefold()
        if suffix in FORBIDDEN_SUFFIXES or file_path.name.casefold().startswith(".env"):
            findings.append(f"forbidden artifact type: {file_path}")
            continue
        if suffix not in TEXT_SUFFIXES:
            findings.append(f"unsupported artifact type: {file_path}")
            continue
        content = file_path.read_bytes()
        if any(token in content for token in token_bytes):
            findings.append(f"credential value found: {file_path}")
        lowered_content = content.lower()
        for marker in FORBIDDEN_MARKERS:
            if marker.lower() in lowered_content:
                findings.append(f"forbidden field marker found: {file_path}")
                break
    return findings


def credential_values_from_environment() -> tuple[str, ...]:
    """Collect every secret value that must never appear in a public artifact."""
    values = [
        *parse_api_tokens(
            os.environ.get("KAGGLE_API_TOKEN"),
            os.environ.get("KAGGLE_API_TOKENS"),
        ),
        *(
            secret
            for credential in parse_legacy_credentials(
                os.environ.get("KAGGLE_LEGACY_CREDENTIALS")
            )
            for secret in credential_secret_values(credential)
        ),
    ]
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a Pages artifact for credential or raw-field leaks")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        credential_values = credential_values_from_environment()
    except ValueError as exc:
        print(f"ERROR {exc}")
        return 1
    findings = scan(args.paths, credential_values)
    if findings:
        for finding in findings:
            print(f"ERROR {finding}")
        return 1
    print(f"Public artifact safety check passed for {len(args.paths)} path(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
