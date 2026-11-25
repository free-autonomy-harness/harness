#!/usr/bin/env python3
"""Общие помощники harness: GitHub API, git, манифесты target-репозиториев."""
from __future__ import annotations

import base64
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
TARGETS_DIR = ROOT / "targets"
DEFAULT_API = "https://api.github.com"
USER_AGENT = "free-autonomy-harness"


class HarnessError(RuntimeError):
    """Ошибка harness, которую можно показать в issue."""


class GitHubError(HarnessError):
    def __init__(self, status: int, body: str, url: str = "") -> None:
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"GitHub API {status} for {url}: {body[:800]}")


class GitHub:
    """Минимальный клиент GitHub REST API на stdlib."""

    def __init__(self, token: str | None = None, api: str = DEFAULT_API) -> None:
        self.token = (token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
        self.api = api.rstrip("/")
        self._labels_checked: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------ HTTP
    def _request(
        self,
        method: str,
        path: str,
        data: Any = None,
        *,
        accept: str = "application/vnd.github+json",
        raw: bool = False,
        timeout: int = 60,
    ) -> tuple[Any, Any]:
        url = path if path.startswith("http") else self.api + path
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
                resp_headers = dict(resp.headers.items())
                status = resp.status
        except urllib.error.HTTPError as exc:
            err = exc.read().decode("utf-8", "replace")
            raise GitHubError(exc.code, err, url) from exc
        except urllib.error.URLError as exc:
            raise HarnessError(f"network error for {url}: {exc.reason}") from exc

        if raw:
            return payload, resp_headers
        if not payload:
            return None, resp_headers
        try:
            return json.loads(payload), resp_headers
        except json.JSONDecodeError as exc:
            raise HarnessError(f"invalid JSON from {url}: {payload[:300]!r}") from exc

    def request(self, method: str, path: str, data: Any = None, **kwargs: Any) -> Any:
        payload, _ = self._request(method, path, data, **kwargs)
        return payload

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, data: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, data, **kwargs)

    def patch(self, path: str, data: Any = None, **kwargs: Any) -> Any:
        return self.request("PATCH", path, data, **kwargs)

    def put(self, path: str, data: Any = None, **kwargs: Any) -> Any:
        return self.request("PUT", path, data, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    # ------------------------------------------------------------------ repos
    def get_repo(self, repo: str) -> dict[str, Any]:
        return self.get(f"/repos/{repo}")

    def default_branch(self, repo: str) -> str:
        return self.get_repo(repo).get("default_branch", "main")

    def branch_sha(self, repo: str, branch: str) -> str:
        try:
            ref = self.get(f"/repos/{repo}/git/ref/heads/{urllib.parse.quote(branch, safe='')}")
            return ref["object"]["sha"]
        except GitHubError as exc:
            if exc.status != 404:
                raise
            data = self.get(f"/repos/{repo}/branches/{urllib.parse.quote(branch, safe='')}")
            return data["commit"]["sha"]

    # ----------------------------------------------------------------- issues
    def list_issues(
        self,
        repo: str,
        *,
        labels: str | None = None,
        state: str = "open",
        sort: str = "created",
        direction: str = "asc",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = {"state": state, "sort": sort, "direction": direction, "per_page": "100"}
        if labels:
            query["labels"] = labels
        out: list[dict[str, Any]] = []
        page = 1
        while len(out) < limit:
            query["page"] = str(page)
            path = f"/repos/{repo}/issues?{urllib.parse.urlencode(query)}"
            batch = self.get(path) or []
            batch = [x for x in batch if "pull_request" not in x]
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return out[:limit]

    def get_issue(self, repo: str, number: int) -> dict[str, Any]:
        return self.get(f"/repos/{repo}/issues/{number}")

    def update_issue(self, repo: str, number: int, **fields: Any) -> dict[str, Any]:
        return self.patch(f"/repos/{repo}/issues/{number}", fields)

    def close_issue(self, repo: str, number: int) -> dict[str, Any]:
        return self.update_issue(repo, number, state="closed", state_reason="completed")

    def comment(self, repo: str, number: int, body: str) -> dict[str, Any]:
        return self.post(f"/repos/{repo}/issues/{number}/comments", {"body": body})

    def ensure_label(self, repo: str, name: str, color: str = "ededed", description: str = "") -> None:
        key = (repo, name)
        if key in self._labels_checked:
            return
        quoted = urllib.parse.quote(name, safe="")
        try:
            self.get(f"/repos/{repo}/labels/{quoted}")
        except GitHubError as exc:
            if exc.status != 404:
                raise
            try:
                self.post(
                    f"/repos/{repo}/labels",
                    {"name": name, "color": color, "description": description[:100]},
                )
            except GitHubError as create_exc:
                if create_exc.status != 422:
                    raise
        self._labels_checked.add(key)

    def add_labels(self, repo: str, number: int, names: Iterable[str]) -> Any:
        names = [n for n in names if n]
        for name in names:
            self.ensure_label(repo, name)
        if not names:
            return None
        return self.post(f"/repos/{repo}/issues/{number}/labels", {"labels": names})

    def remove_label(self, repo: str, number: int, name: str) -> None:
        quoted = urllib.parse.quote(name, safe="")
        try:
            self.delete(f"/repos/{repo}/issues/{number}/labels/{quoted}")
        except GitHubError as exc:
            if exc.status != 404:
                raise

    # ----------------------------------------------------------------- actions
    def dispatch_workflow(self, repo: str, workflow: str, ref: str, inputs: dict[str, Any]) -> None:
        payload = {"ref": ref, "inputs": {k: str(v) for k, v in inputs.items()}}
        self.post(
            f"/repos/{repo}/actions/workflows/{urllib.parse.quote(workflow, safe='')}/dispatches",
            payload,
        )

    def get_workflow_run(self, repo: str, run_id: int | str) -> dict[str, Any]:
        return self.get(f"/repos/{repo}/actions/runs/{run_id}")

    def list_run_artifacts(self, repo: str, run_id: int | str) -> list[dict[str, Any]]:
        data = self.get(f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100") or {}
        return data.get("artifacts", [])

    def find_artifact(self, repo: str, run_id: int | str, name: str) -> dict[str, Any] | None:
        for artifact in self.list_run_artifacts(repo, run_id):
            if artifact.get("name") == name and not artifact.get("expired"):
                return artifact
        return None

    def download_artifact(self, repo: str, artifact_id: int, dest: Path) -> Path:
        payload, _ = self._request(
            "GET",
            f"/repos/{repo}/actions/artifacts/{artifact_id}/zip",
            raw=True,
            timeout=120,
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        return dest

    def download_artifact_named(self, repo: str, run_id: int | str, name: str, dest_dir: Path) -> Path:
        artifact = self.find_artifact(repo, run_id, name)
        if not artifact:
            raise HarnessError(f"artifact {name!r} not found in {repo} run {run_id}")
        zip_path = dest_dir.parent / f"{name}-{run_id}.zip"
        self.download_artifact(repo, int(artifact["id"]), zip_path)
        dest_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest_dir)
        return dest_dir

    # ------------------------------------------------------------------- pulls
    def create_pull(self, repo: str, title: str, head: str, base: str, body: str) -> dict[str, Any]:
        return self.post(
            f"/repos/{repo}/pulls",
            {"title": title, "head": head, "base": base, "body": body, "draft": False},
        )

    def get_pull(self, repo: str, number: int) -> dict[str, Any]:
        return self.get(f"/repos/{repo}/pulls/{number}")

    def update_pull(self, repo: str, number: int, **fields: Any) -> dict[str, Any]:
        return self.patch(f"/repos/{repo}/pulls/{number}", fields)

    def merge_pull(
        self,
        repo: str,
        number: int,
        sha: str,
        *,
        method: str = "squash",
        title: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"merge_method": method, "sha": sha}
        if title:
            payload["commit_title"] = title
        if message:
            payload["commit_message"] = message
        return self.put(f"/repos/{repo}/pulls/{number}/merge", payload)

    def delete_branch(self, repo: str, branch: str) -> None:
        try:
            self.delete(f"/repos/{repo}/git/refs/heads/{urllib.parse.quote(branch, safe='/')}")
        except GitHubError as exc:
            if exc.status not in (404, 422):
                raise

    # ---------------------------------------------------------------- statuses
    def create_status(
        self,
        repo: str,
        sha: str,
        context: str,
        state: str,
        description: str = "",
        target_url: str | None = None,
    ) -> dict[str, Any]:
        payload = {"context": context, "state": state, "description": description[:140]}
        if target_url:
            payload["target_url"] = target_url
        return self.post(f"/repos/{repo}/statuses/{sha}", payload)

    def combined_status(self, repo: str, ref: str) -> dict[str, Any]:
        try:
            return self.get(f"/repos/{repo}/commits/{ref}/status")
        except GitHubError as exc:
            if exc.status == 404:
                return {}
            raise

    def check_runs(self, repo: str, ref: str) -> list[dict[str, Any]]:
        try:
            data = self.get(f"/repos/{repo}/commits/{ref}/check-runs?per_page=100")
        except GitHubError as exc:
            if exc.status == 404:
                return []
            raise
        return (data or {}).get("check_runs", [])

    # --------------------------------------------------------------- variables
    def get_variable(self, repo: str, name: str) -> str | None:
        try:
            data = self.get(f"/repos/{repo}/actions/variables/{urllib.parse.quote(name, safe='')}")
            return data.get("value")
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise

    def set_variable(self, repo: str, name: str, value: str) -> None:
        payload = {"name": name, "value": value}
        try:
            self.patch(f"/repos/{repo}/actions/variables/{urllib.parse.quote(name, safe='')}", payload)
        except GitHubError as exc:
            if exc.status != 404:
                raise
            self.post(f"/repos/{repo}/actions/variables", payload)


# --------------------------------------------------------------------- helpers
def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise HarnessError(f"required environment variable {name} is not set")
    return value or ""


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def issue_labels(issue: dict[str, Any]) -> list[str]:
    return [x["name"] if isinstance(x, dict) else str(x) for x in issue.get("labels", [])]


def target_alias(labels: Iterable[str]) -> str | None:
    for label in labels:
        if label.startswith("target:"):
            return label.split(":", 1)[1]
    return None


def load_target(alias: str) -> dict[str, Any]:
    path = TARGETS_DIR / f"{alias}.yml"
    if not path.exists():
        raise HarnessError(f"unknown target {alias!r}: {path} not found")
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise HarnessError("PyYAML is required (pip install -r requirements.txt)") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise HarnessError(f"target {alias}: manifest must be a mapping")
    data.setdefault("alias", alias)
    for field in ("repo", "branch"):
        if not data.get(field):
            raise HarnessError(f"target {alias}: missing {field}")
    if "/" not in str(data["repo"]):
        raise HarnessError(f"target {alias}: repo must be owner/name")
    data.setdefault("verify", [])
    data.setdefault("kernel_paths", [])
    data.setdefault("require_native_ci", alias != "sandbox")
    for check in data["verify"]:
        if not isinstance(check, dict) or not check.get("name") or not check.get("run"):
            raise HarnessError(f"target {alias}: each verify entry needs name and run")
    return data


def repo_name(full_name: str) -> str:
    return full_name.split("/", 1)[-1]


def repo_owner(full_name: str) -> str:
    return full_name.split("/", 1)[0]


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    for pattern in patterns or []:
        pattern = str(pattern).strip()
        if not pattern:
            continue
        if pattern.endswith("/"):
            if normalized == pattern[:-1] or normalized.startswith(pattern):
                return True
        elif fnmatch.fnmatch(normalized, pattern):
            return True
        elif "/" not in pattern and fnmatch.fnmatch(Path(normalized).name, pattern):
            return True
    return False


def is_kernel_path(path: str, kernel_paths: Iterable[str]) -> bool:
    return matches_any(path, kernel_paths)


def render_prompt(template: str, values: dict[str, Any]) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", str(value))
    return out


def git_env(token: str | None = None) -> dict[str, str]:
    result = os.environ.copy()
    result["GIT_TERMINAL_PROMPT"] = "0"
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        result["GIT_CONFIG_COUNT"] = "1"
        result["GIT_CONFIG_KEY_0"] = "http.extraheader"
        result["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {basic}"
    return result


def run(
    args: Iterable[Any],
    *,
    cwd: str | Path | None = None,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    cmd = [str(x) for x in args]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise HarnessError(
            f"command failed ({proc.returncode}): {' '.join(cmd[:6])}\n"
            f"stdout:\n{proc.stdout[-4000:]}\nstderr:\n{proc.stderr[-4000:]}"
        )
    return proc


def git(repo: str | Path, *args: Any, token: str | None = None, check: bool = True, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args], env=git_env(token), check=check, timeout=timeout)


def write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact(text: str, secrets: Iterable[str]) -> str:
    result = text
    for secret in secrets:
        if secret and len(secret) >= 4:
            result = result.replace(secret, "***")
    return result


def truncate(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... truncated {len(text) - limit} chars ..."


def split_csv(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def label_color(name: str) -> str:
    return {
        "harness:task": "1D76DB",
        "harness:active": "FBCA04",
        "harness:failed": "D93F0B",
        "harness:blocked": "B60205",
        "harness:done": "0E8A16",
        "harness:needs-approval": "5319E7",
        "harness:dry-run": "F9D0C4",
        "allow-tests": "C2E0C6",
        "allow-deps": "C2E0C6",
        "target:sandbox": "BFD4F2",
        "target:core": "BFD4F2",
    }.get(name, "EDEDED")


def fail(message: str, code: int = 1) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def is_int(value: str) -> bool:
    return bool(re.fullmatch(r"\d+", str(value).strip()))
