"""Cloud Terminal — the companion service the Void Cutting Slash dashboard
delegates real compute to.

The main dashboard (main.py) is meant to be deployable somewhere light
(Vercel, a small container) that has no Android SDK and shouldn't be
running arbitrary generated code in its own process. This server is the
opposite: run it on a real machine (this repo's own dev container is one —
it already has Java, the Android SDK, and Gradle installed) with the
android/ directory checked out next to it, point the dashboard's Settings
-> Cloud Terminal URL at it, and two things become real instead of
simulated:

  * /execute  — actually run swarm-generated code and return real stdout/
    stderr/exit code, instead of trusting the Auditor's opinion alone.
  * /build-apk — actually compile android/ with Gradle into a signed debug
    APK, optionally pre-pointed at a deployment URL.

Run it with:  uvicorn cloud_terminal.server:app --host 0.0.0.0 --port 8800
"""
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
ANDROID_PROJECT_DIR = REPO_ROOT / "android"

app = FastAPI(title="Void Cutting Slash — Cloud Terminal")

RUNNERS = {
    "python": ["python3"],
    "node": ["node"],
}


def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


@app.get("/health")
async def health():
    gradlew = ANDROID_PROJECT_DIR / "gradlew"
    return {
        "status": "ok",
        "java": _which("java"),
        "node": _which("node"),
        "python": _which("python3"),
        "android_project_present": (ANDROID_PROJECT_DIR / "app").exists(),
        "gradlew_present": gradlew.exists(),
    }


class ExecuteIn(BaseModel):
    files: dict
    entrypoint: str
    language: str = "python"
    timeout: int = 30


@app.post("/execute")
async def execute(body: ExecuteIn):
    if body.language not in RUNNERS:
        raise HTTPException(400, f"Unsupported language '{body.language}'. Use one of: {list(RUNNERS)}")
    if body.entrypoint not in body.files:
        raise HTTPException(400, f"entrypoint '{body.entrypoint}' not found in supplied files")

    workdir = Path(tempfile.mkdtemp(prefix="vcs-exec-"))
    try:
        for path, content in body.files.items():
            target = workdir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        cmd = RUNNERS[body.language] + [body.entrypoint]
        try:
            proc = subprocess.run(
                cmd, cwd=workdir, capture_output=True, text=True,
                timeout=max(1, min(body.timeout, 120)),
            )
            return {
                "stdout": proc.stdout[-20000:],
                "stderr": proc.stderr[-20000:],
                "exit_code": proc.returncode,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "stdout": (exc.stdout or "")[-20000:] if exc.stdout else "",
                "stderr": (exc.stderr or "")[-20000:] if exc.stderr else "",
                "exit_code": -1,
                "timed_out": True,
            }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


class BuildApkIn(BaseModel):
    backend_url: str | None = None
    app_name: str | None = None


@app.post("/build-apk")
async def build_apk(body: BuildApkIn):
    if not (ANDROID_PROJECT_DIR / "gradlew").exists():
        raise HTTPException(
            500,
            "android/gradlew not found next to cloud_terminal/ — check out the full "
            "void-cutting-slash repo on this machine before running the terminal.",
        )

    build_id = uuid.uuid4().hex[:8]
    workdir = Path(tempfile.mkdtemp(prefix=f"vcs-apk-{build_id}-"))
    project_copy = workdir / "android"
    try:
        shutil.copytree(
            ANDROID_PROJECT_DIR, project_copy,
            ignore=shutil.ignore_patterns(".gradle", "build", "*.apk", "local.properties"),
        )

        strings_path = project_copy / "app/src/main/res/values/strings.xml"
        strings_xml = strings_path.read_text()
        if body.backend_url:
            strings_xml = re.sub(
                r'(<string name="default_backend_url">).*?(</string>)',
                lambda m: m.group(1) + body.backend_url.replace("&", "&amp;") + m.group(2),
                strings_xml,
            )
        if body.app_name:
            strings_xml = re.sub(
                r'(<string name="app_name">).*?(</string>)',
                lambda m: m.group(1) + body.app_name.replace("&", "&amp;") + m.group(2),
                strings_xml,
            )
        strings_path.write_text(strings_xml)

        android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        if not android_home:
            raise HTTPException(
                500,
                "ANDROID_HOME / ANDROID_SDK_ROOT is not set on this Cloud Terminal — "
                "point it at your Android SDK install before building APKs.",
            )
        (project_copy / "local.properties").write_text(f"sdk.dir={android_home}\n")

        proc = subprocess.run(
            ["./gradlew", "assembleDebug", "--no-daemon"],
            cwd=project_copy, capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            raise HTTPException(
                502,
                f"Gradle build failed (exit {proc.returncode}):\n"
                f"{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}",
            )

        apk_path = project_copy / "app/build/outputs/apk/debug/app-debug.apk"
        if not apk_path.exists():
            raise HTTPException(502, "Gradle reported success but no APK was found at the expected path.")

        apk_bytes = apk_path.read_bytes()
        return Response(
            content=apk_bytes,
            media_type="application/vnd.android.package-archive",
            headers={"Content-Disposition": 'attachment; filename="void-cutting-slash.apk"'},
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("cloud_terminal.server:app", host="0.0.0.0", port=8800)
