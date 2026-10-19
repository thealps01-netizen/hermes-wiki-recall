"""wiki-recall: before each model turn, add pointers to possibly relevant LLM Wiki pages."""
from typing import Any

from . import recall


def _make_hook(skip):
    def _pre_llm_call(user_message: Any = None, **_: Any):
        def lookup(name):
            # Imported per call: agent.secret_scope exists only inside a running Hermes process,
            # and an import failure is logged by recall.read_token instead of failing the turn.
            from agent.secret_scope import get_secret
            return get_secret(name)
        query = recall.message_text(user_message)
        text = recall.format_context(recall.search(query, token=recall.read_token(lookup), skip=skip))
        return {"context": text} if text else None
    return _pre_llm_call


def register(ctx: Any) -> None:
    ctx.register_hook("pre_llm_call", _make_hook(recall.compile_skip(ctx.get_config("skip_pattern", ""))))
