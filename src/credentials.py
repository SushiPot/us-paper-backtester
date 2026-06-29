from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


GITHUB_TOKEN_KEYS = {
    "GITHUB_TOKEN",
    "GITHUB_API_TOKEN",
    "GITHUB_API_KEY",
    "GH_TOKEN",
    "TOKEN",
    "API_TOKEN",
    "API_KEY",
}


def get_github_token(base_dir: Path | None = None, include_gh_cli: bool = True) -> str:
    """Read a GitHub token without logging it.

    Lookup order:
    1. Environment variables.
    2. Explicit token files such as GITHUB_TOKEN_FILE / GITHUB_API_FILE.
    3. Common local project files such as .env or config/github_token.txt.
    4. The local GitHub CLI login token.
    """
    token = _token_from_env()
    if token:
        return token

    root = (base_dir or Path.cwd()).resolve()
    for path in _candidate_token_files(root):
        token = _token_from_file(path)
        if token:
            return token

    if include_gh_cli:
        return _token_from_gh_cli()
    return ""


def _token_from_env() -> str:
    for key in ("GITHUB_TOKEN", "GITHUB_API_TOKEN", "GITHUB_API_KEY", "GH_TOKEN"):
        token = os.getenv(key, "").strip()
        if token:
            return _clean_token(token)
    return ""


def _candidate_token_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for env_key in ("GITHUB_TOKEN_FILE", "GITHUB_API_TOKEN_FILE", "GITHUB_API_FILE", "GH_TOKEN_FILE"):
        value = os.getenv(env_key, "").strip()
        if value:
            paths.append(Path(value).expanduser())

    search_roots = [root]
    if root.parent != root:
        search_roots.append(root.parent)

    for search_root in search_roots:
        paths.extend(
            [
                search_root / ".env",
                search_root / ".env.local",
                search_root / ".env.github",
                search_root / "github_token.txt",
                search_root / "github_api_token.txt",
                search_root / "github_api.txt",
                search_root / "github_api.json",
                search_root / "githubapi.txt",
                search_root / "githubapi.json",
                search_root / "config" / ".env",
                search_root / "config" / "github.env",
                search_root / "config" / "github_token.txt",
                search_root / "config" / "github_api_token.txt",
                search_root / "config" / "github_api.txt",
                search_root / "config" / "github_api.json",
                search_root / "config" / "githubapi.txt",
                search_root / "config" / "githubapi.json",
                search_root / "secrets" / "github_token.txt",
                search_root / "secrets" / "github_api.txt",
                search_root / "secrets" / "github_api.json",
                search_root / "secrets" / "githubapi.txt",
                search_root / "secrets" / "githubapi.json",
            ]
        )
        paths.extend(_glob_token_files(search_root))
        paths.extend(_glob_token_files(search_root / "config"))
        paths.extend(_glob_token_files(search_root / "secrets"))
    return _unique_paths(paths)


def _glob_token_files(directory: Path) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    candidates: list[Path] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.startswith(".env") or any(part in name for part in ("github", "token", "secret", "credential")):
            candidates.append(path)
    return candidates


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _token_from_file(path: Path) -> str:
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return ""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8-sig", errors="ignore").strip()
    except OSError:
        return ""

    if not text:
        return ""

    if path.suffix.lower() == ".json":
        return _token_from_json(text)
    return _token_from_text(text)


def _token_from_json(text: str) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in GITHUB_TOKEN_KEYS:
        value = payload.get(key) or payload.get(key.lower())
        if isinstance(value, str) and value.strip():
            return _clean_token(value)
    github = payload.get("github")
    if isinstance(github, dict):
        for key in GITHUB_TOKEN_KEYS:
            value = github.get(key) or github.get(key.lower())
            if isinstance(value, str) and value.strip():
                return _clean_token(value)
    return ""


def _token_from_text(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, value = stripped.split("=", 1)
            if key.strip() in GITHUB_TOKEN_KEYS:
                return _clean_token(value)
            continue
        candidate = _clean_token(stripped)
        if _looks_like_github_token(candidate):
            return candidate
    return ""


def _token_from_gh_cli() -> str:
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return _clean_token(result.stdout)


def _clean_token(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _looks_like_github_token(value: str) -> bool:
    return value.startswith(("ghp_", "github_pat_", "gho_", "ghu_", "ghs_", "ghr_")) or len(value) >= 30
