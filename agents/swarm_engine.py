"""5-tier heavy coding cascade.

    Generator (Kimi)  ->  Auditor (GLM)  <-> loop until clean
                              |
                              v (loop exhausted twice)
                       Deep Reasoner (DeepSeek)
                              |
                              v
                      Syntax Verifier (Qwen-class coder model)
                              |
                              v (verifier still flags critical issues)
                        Safety Net (Nemotron Ultra)

Every stage is a real HTTP call to NVIDIA's NIM API. Progress is reported
through `on_event(dict)` so the frontend can render live swarm status.
"""
import json
import re
import time
import uuid
from pathlib import Path

from agents.nvidia_client import chat_completion, NvidiaAPIError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HISTORY_PATH = DATA_DIR / "projects_history.json"
PROJECTS_DIR = DATA_DIR / "projects"

CODE_BLOCK_RE = re.compile(
    r"```[ \t]*([a-zA-Z0-9_+-]+):([^\n`]+)\n(.*?)```", re.DOTALL
)

GENERATOR_SYSTEM = (
    "You are the Generator stage of a production coding swarm. Given a build "
    "request, output COMPLETE, working, production-grade source files. "
    "Absolutely no placeholders, no 'TODO', no omitted logic, no pseudo-code. "
    "Every file MUST be a fenced code block whose opening fence is exactly "
    "```language:relative/path/to/file — one block per file. Do not wrap the "
    "whole answer in extra prose beyond a short 1-2 sentence intro."
)

AUDITOR_SYSTEM = (
    "You are the Auditor stage of a coding swarm. Review the supplied source "
    "files line-by-line for syntax errors, undefined names, missing imports, "
    "logic bugs, and anything that would crash at runtime. Respond with ONLY "
    "a JSON object, no prose, no markdown fences, shaped exactly like: "
    '{"clean": true|false, "bugs": [{"file": "path", "issue": "...", '
    '"fix_instruction": "..."}]}. If there are no bugs, return "clean": true '
    'and an empty "bugs" list.'
)

REASONER_SYSTEM = (
    "You are the Deep Reasoner stage, triggered because the Generator/Auditor "
    "loop failed to converge twice in a row. Perform careful step-by-step "
    "algorithmic and execution-path analysis of the bug list and the current "
    "source, then output the FULLY corrected files using the same "
    "```language:relative/path/to/file fenced-block format. No placeholders."
)

VERIFIER_SYSTEM = (
    "You are the Syntax Verifier stage. Validate strict framework compliance "
    "for the given files (correct syntax for the language/framework in use, "
    "correct manifest/config structure if present, correct import syntax). "
    "Respond with ONLY JSON: {\"compliant\": true|false, \"issues\": ["
    "\"...\"]}."
)

SAFETY_NET_SYSTEM = (
    "You are the Ultimate Safety Net, the final fallback for unresolved "
    "system-architecture mismatches after generation, auditing, deep "
    "reasoning, and syntax verification all ran. Reconcile every remaining "
    "issue and output the final, authoritative, complete source files using "
    "```language:relative/path/to/file fenced blocks. No placeholders."
)


def parse_code_blocks(text: str) -> dict:
    """Extract {"path/to/file": "content"} from ```lang:path fenced blocks."""
    files = {}
    for _lang, path, content in CODE_BLOCK_RE.findall(text or ""):
        files[path.strip()] = content.rstrip("\n") + "\n"
    return files


def _extract_json(text: str) -> dict:
    """Pull the first balanced {...} object out of a model response, even if
    the model wrapped it in markdown fences or extra prose."""
    text = (text or "").strip()
    start = text.find("{")
    if start == -1:
        return {}
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return {}
    return {}


def _files_prompt(files: dict) -> str:
    parts = []
    for path, content in files.items():
        lang = path.rsplit(".", 1)[-1] if "." in path else "text"
        parts.append(f"```{lang}:{path}\n{content}```")
    return "\n\n".join(parts)


def _call(api_key, model, system, user, tier_name, on_event):
    on_event({"tier": tier_name, "status": "running", "model": model})
    try:
        text = chat_completion(
            api_key, model,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2, max_tokens=8192, stream=False,
        )
    except NvidiaAPIError as exc:
        on_event({"tier": tier_name, "status": "error", "model": model, "message": str(exc)})
        raise
    on_event({"tier": tier_name, "status": "done", "model": model})
    return text


def run_swarm(settings: dict, prompt: str, on_event=lambda e: None) -> dict:
    """Run the full cascade. Returns {"files": {...}, "log": [...], "id": str}.
    `on_event` is called with progress dicts as each tier runs, so callers can
    stream live status (see main.py's SSE endpoint)."""
    api_key = settings.get("nvidia_api_key", "")
    models = settings.get("models", {})
    max_loops = int(settings.get("max_audit_loops", 3))

    log = []

    def emit(event):
        log.append(event)
        on_event(event)

    # --- Tier 1: Generator ---
    gen_text = _call(
        api_key, models["generator"], GENERATOR_SYSTEM,
        f"Build request:\n{prompt}", "generator", emit,
    )
    files = parse_code_blocks(gen_text)
    if not files:
        raise NvidiaAPIError(
            "Generator returned no fenced ```language:path code blocks — "
            "cannot proceed to audit."
        )

    deep_reasoner_used = False
    bugs = None

    # --- Tier 2: Auditor <-> Generator loop ---
    for loop_index in range(max_loops):
        audit_text = _call(
            api_key, models["auditor"], AUDITOR_SYSTEM,
            f"Original request:\n{prompt}\n\nCurrent files:\n{_files_prompt(files)}",
            "auditor", emit,
        )
        audit = _extract_json(audit_text)
        bugs = audit.get("bugs", [])
        emit({"tier": "auditor", "status": "report", "clean": audit.get("clean", not bugs),
              "bug_count": len(bugs), "loop": loop_index + 1})

        if audit.get("clean", not bugs) or not bugs:
            bugs = []
            break

        if loop_index == max_loops - 1:
            break  # exhausted the loop; deep reasoner picks this up below

        if loop_index >= 1 and not deep_reasoner_used:
            # Two failed loops -> escalate to the Deep Reasoner instead of
            # bouncing back to the Generator a third time.
            reasoner_text = _call(
                api_key, models["deep_reasoner"], REASONER_SYSTEM,
                f"Original request:\n{prompt}\n\nCurrent files:\n{_files_prompt(files)}"
                f"\n\nOutstanding bug list:\n{json.dumps(bugs, indent=2)}",
                "deep_reasoner", emit,
            )
            reasoned_files = parse_code_blocks(reasoner_text)
            if reasoned_files:
                files = reasoned_files
            deep_reasoner_used = True
            continue

        fix_text = _call(
            api_key, models["generator"], GENERATOR_SYSTEM,
            f"Original request:\n{prompt}\n\nCurrent files:\n{_files_prompt(files)}"
            f"\n\nThe Auditor found these bugs — fix every one and re-emit ALL "
            f"files in full:\n{json.dumps(bugs, indent=2)}",
            "generator", emit,
        )
        fixed_files = parse_code_blocks(fix_text)
        if fixed_files:
            files = fixed_files

    if bugs:
        # Loop exhausted without a clean report and reasoner already ran once;
        # give the reasoner one last direct shot before moving on.
        reasoner_text = _call(
            api_key, models["deep_reasoner"], REASONER_SYSTEM,
            f"Original request:\n{prompt}\n\nCurrent files:\n{_files_prompt(files)}"
            f"\n\nOutstanding bug list:\n{json.dumps(bugs, indent=2)}",
            "deep_reasoner", emit,
        )
        reasoned_files = parse_code_blocks(reasoner_text)
        if reasoned_files:
            files = reasoned_files

    # --- Tier 4: Syntax Verifier ---
    verify_text = _call(
        api_key, models["syntax_verifier"], VERIFIER_SYSTEM,
        f"Files to verify:\n{_files_prompt(files)}", "syntax_verifier", emit,
    )
    verification = _extract_json(verify_text)
    compliant = verification.get("compliant", True)
    issues = verification.get("issues", [])
    emit({"tier": "syntax_verifier", "status": "report", "compliant": compliant,
          "issues": issues})

    # --- Tier 5: Safety Net (only if verifier is still unhappy) ---
    if not compliant and issues:
        safety_text = _call(
            api_key, models["safety_net"], SAFETY_NET_SYSTEM,
            f"Original request:\n{prompt}\n\nCurrent files:\n{_files_prompt(files)}"
            f"\n\nUnresolved compliance issues:\n{json.dumps(issues, indent=2)}",
            "safety_net", emit,
        )
        safety_files = parse_code_blocks(safety_text)
        if safety_files:
            files = safety_files

    result = {
        "id": uuid.uuid4().hex[:12],
        "prompt": prompt,
        "files": files,
        "log": log,
        "created_at": time.time(),
    }
    _save_history(result)
    return result


def _save_history(result: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    (PROJECTS_DIR / f"{result['id']}.json").write_text(json.dumps({
        "id": result["id"],
        "prompt": result["prompt"],
        "files": result["files"],
        "log": result["log"],
        "created_at": result["created_at"],
        "vercel_url": None,
    }, indent=2))

    try:
        history = json.loads(HISTORY_PATH.read_text()) if HISTORY_PATH.exists() else []
    except json.JSONDecodeError:
        history = []
    history.insert(0, {
        "id": result["id"],
        "prompt": result["prompt"],
        "files": list(result["files"].keys()),
        "created_at": result["created_at"],
        "vercel_url": None,
    })
    HISTORY_PATH.write_text(json.dumps(history[:200], indent=2))


def load_project(project_id: str) -> dict | None:
    path = PROJECTS_DIR / f"{project_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def set_project_vercel_url(project_id: str, url: str) -> None:
    path = PROJECTS_DIR / f"{project_id}.json"
    if path.exists():
        data = json.loads(path.read_text())
        data["vercel_url"] = url
        path.write_text(json.dumps(data, indent=2))
    if HISTORY_PATH.exists():
        history = json.loads(HISTORY_PATH.read_text())
        for entry in history:
            if entry.get("id") == project_id:
                entry["vercel_url"] = url
        HISTORY_PATH.write_text(json.dumps(history, indent=2))
