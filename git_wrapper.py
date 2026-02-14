import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class GitResult:
    success: bool
    failureMessage: Optional[str] = None
    realMessage: Optional[str] = None


class GitWrapper:
    def __init__(self, default_domain: str = "github.com"):
        self.default_domain = default_domain

    # -------------------------
    # Public API
    # -------------------------

    def is_git_installed(self) -> bool:
        return shutil.which("git") is not None

    def cloneTo(self, url: str, path: str) -> GitResult:
        if not self.is_git_installed():
            return GitResult(
                success=False,
                failureMessage="Git is not installed or not available in PATH.",
            )

        resolved_url = self._resolve_url(url)
        path_obj = Path(path)

        if path_obj.exists() and any(path_obj.iterdir()):
            return GitResult(
                success=False,
                failureMessage="Destination path already exists and is not empty.",
            )

        # Shallow clone
        result = self._run_git(
            ["clone", "--depth", "1", resolved_url, str(path_obj)])

        if result.returncode == 0:
            return GitResult(success=True)

        return self._handle_git_error(result)

    def updateRepoAtPath(self, path: Path) -> GitResult:

        if not self.is_git_installed():
            return GitResult(
                success=False,
                failureMessage="Git is not installed or not available in PATH.",
            )

        if not path.exists():
            return GitResult(
                success=False,
                failureMessage="Specified path does not exist.",
            )

        if not (path / ".git").exists():
            return GitResult(
                success=False,
                failureMessage="Specified path is not a git repository.",
            )

        branch_proc = self._run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(path),
        )

        if branch_proc.returncode != 0:
            return self._handle_git_error(branch_proc)

        branch = branch_proc.stdout.strip()

        fetch_proc = self._run_git(
            ["fetch", "origin", branch, "--depth", "1"],
            cwd=str(path),
        )

        if fetch_proc.returncode != 0:
            return self._handle_git_error(fetch_proc)

        local_rev = self._run_git(
            ["rev-parse", "HEAD"],
            cwd=str(path),
        )

        remote_rev = self._run_git(
            ["rev-parse", f"origin/{branch}"],
            cwd=str(path),
        )

        if local_rev.returncode != 0:
            return self._handle_git_error(local_rev)

        if remote_rev.returncode != 0:
            return self._handle_git_error(remote_rev)

        if local_rev.stdout.strip() == remote_rev.stdout.strip():
            return GitResult(
                success=False,
                failureMessage="Repository is already up to date.",
                realMessage=None,
            )

        reset_proc = self._run_git(
            ["reset", "--hard", f"origin/{branch}"],
            cwd=str(path),
        )

        if reset_proc.returncode != 0:
            return self._handle_git_error(reset_proc)

        clean_proc = self._run_git(
            ["clean", "-fd"],
            cwd=str(path),
        )

        if clean_proc.returncode != 0:
            return self._handle_git_error(clean_proc)

        gc_proc = self._run_git(
            ["gc", "--prune=now", "--aggressive"],
            cwd=str(path),
        )

        if gc_proc.returncode != 0:
            return self._handle_git_error(gc_proc)

        return GitResult(success=True)

    def _resolve_url(self, url: str) -> str:
        if url.startswith(("http://", "https://", "git://", "ssh://")):
            return url
        if "/" in url:
            return f"https://{self.default_domain}/{url}"
        return f"https://{self.default_domain}/{url}"

    def _run_git(self, args, cwd: Optional[str] = None):
        return subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
        )

    def _handle_git_error(self, process: subprocess.CompletedProcess) -> GitResult:
        real_message = (process.stderr or process.stdout or "").strip()

        # Custom failure mappings
        if "Repository not found" in real_message:
            return GitResult(
                success=False,
                failureMessage="Repository not found.",
                realMessage=real_message,
            )

        if "Authentication failed" in real_message:
            return GitResult(
                success=False,
                failureMessage="Authentication failed. Check your credentials.",
                realMessage=real_message,
            )

        if "Could not resolve host" in real_message:
            return GitResult(
                success=False,
                failureMessage="Could not resolve host. Check your internet connection.",
                realMessage=real_message,
            )

        # Fallback: use real message as failureMessage
        return GitResult(
            success=False,
            failureMessage=real_message if real_message else "Unknown git error.",
            realMessage=real_message,
        )
