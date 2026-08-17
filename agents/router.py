"""Intent classifier: decides whether an incoming message should be answered
by the instant fast_chat engine or handed to the heavy 5-tier swarm cascade.
"""
import re

_CODE_SIGNAL_PATTERNS = [
    r"\bbuild\b", r"\bcreate\b", r"\bgenerate\b", r"\bimplement\b",
    r"\bfix\b.*\bbug\b", r"\brefactor\b", r"\bdeploy\b", r"\bapk\b",
    r"```", r"\bfunction\b", r"\bclass\b", r"\bcomponent\b", r"\bendpoint\b",
    r"\bscript\b", r"\bwebsite\b", r"\bapp\b", r"\bapi\b", r"\bdatabase\b",
    r"file:[\w./-]+",
]
_CODE_SIGNAL_RE = re.compile("|".join(_CODE_SIGNAL_PATTERNS), re.IGNORECASE)

FAST = "fast"
HEAVY = "heavy"


def classify_intent(message: str, force_mode: str | None = None) -> str:
    """Return FAST or HEAVY. `force_mode` lets the frontend's explicit
    chat/build toggle always win over the heuristic."""
    if force_mode in (FAST, HEAVY):
        return force_mode

    text = (message or "").strip()
    if not text:
        return FAST

    if len(text) > 350:
        return HEAVY

    if _CODE_SIGNAL_RE.search(text):
        return HEAVY

    return FAST
