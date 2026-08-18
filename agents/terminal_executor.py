"""Client for the optional, user-hosted "Cloud Terminal" companion service
(see cloud_terminal/server.py in this repo). The main dashboard is meant to
stay light enough to run on something like Vercel, so anything that needs a
real machine — executing generated code, compiling a real Android APK with
the SDK + Gradle — is delegated over HTTP to a terminal the user connects in
Settings, instead of trying to do it in the dashboard's own process.

Protocol (implemented by cloud_terminal/server.py):
    GET  {base}/health              -> {"status": "ok", "java": bool, "android_sdk": bool, "gradle": bool}
    POST {base}/execute             -> {"files": {...}, "entrypoint": str, "language": "python"|"node", "timeout": int}
                                     -> {"stdout": str, "stderr": str, "exit_code": int, "timed_out": bool}
    POST {base}/build-apk           -> {"backend_url": str|None, "app_name": str}
                                     -> raw APK bytes (application/vnd.android.package-archive)
"""
import requests

DEFAULT_TIMEOUT = 30


class TerminalError(RuntimeError):
    pass


def _base(url: str) -> str:
    return url.rstrip("/")


def check_health(terminal_url: str, timeout: int = 10) -> dict:
    if not terminal_url:
        raise TerminalError("No Cloud Terminal URL configured. Add one in Settings.")
    try:
        resp = requests.get(f"{_base(terminal_url)}/health", timeout=timeout)
    except requests.RequestException as exc:
        raise TerminalError(f"Could not reach Cloud Terminal at {terminal_url}: {exc}") from exc
    if resp.status_code != 200:
        raise TerminalError(f"Cloud Terminal /health returned {resp.status_code}")
    return resp.json()


def execute_code(terminal_url: str, files: dict, entrypoint: str, language: str = "python",
                  timeout: int = 30) -> dict:
    if not terminal_url:
        raise TerminalError("No Cloud Terminal URL configured. Add one in Settings.")
    if not files:
        raise TerminalError("No files to execute.")
    try:
        resp = requests.post(
            f"{_base(terminal_url)}/execute",
            json={"files": files, "entrypoint": entrypoint, "language": language, "timeout": timeout},
            timeout=timeout + 15,
        )
    except requests.RequestException as exc:
        raise TerminalError(f"Could not reach Cloud Terminal at {terminal_url}: {exc}") from exc
    if resp.status_code != 200:
        raise TerminalError(f"Cloud Terminal /execute returned {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def build_apk(terminal_url: str, backend_url: str | None, app_name: str, timeout: int = 480) -> bytes:
    if not terminal_url:
        raise TerminalError(
            "No Cloud Terminal connected. Connect one in Settings before building a real APK."
        )
    try:
        resp = requests.post(
            f"{_base(terminal_url)}/build-apk",
            json={"backend_url": backend_url, "app_name": app_name},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise TerminalError(f"Could not reach Cloud Terminal at {terminal_url}: {exc}") from exc
    if resp.status_code != 200:
        raise TerminalError(f"Cloud Terminal /build-apk returned {resp.status_code}: {resp.text[:300]}")
    return resp.content
