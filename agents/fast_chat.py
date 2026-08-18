"""Fast conversational engine: a single cheap/lightweight model for instant
back-and-forth chat, bypassing the heavy swarm cascade entirely.
"""
from agents.nvidia_client import chat_completion

SYSTEM_PROMPT = (
    "You are ChomU, the AI assistant inside Void Cutting Slash — an AI "
    "website and APK builder. In this fast-chat mode, answer briefly, "
    "directly, and conversationally. You do not generate production code "
    "yourself here — if the user actually wants a site, app, or script "
    "built, tell them to phrase it as a build/implementation request so the "
    "heavy 5-tier swarm cascade (Generator -> Auditor -> Deep Reasoner -> "
    "Syntax Verifier -> Safety Net) can take over and hand back a real, "
    "deployable project."
)


def run_fast_chat(api_key: str, model: str, message: str, history=None, stream=True):
    """history: list of {"role": "user"|"assistant", "content": str}"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or [])[-10:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})

    return chat_completion(
        api_key, model, messages, temperature=0.6, max_tokens=1024, stream=stream
    )
