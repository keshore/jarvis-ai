"""Jarvis's brain: where the words of an answer come from. One of
  claude   the Claude API, when you gave Jarvis an Anthropic API key
  openai   the OpenAI API (or any server that speaks it), when you gave it that key
  local    the model on this machine (MLX, llama.cpp or Ollama), which needs no key and sends nothing anywhere

The brain only produces text. It has no tools: it cannot read files, run commands, open apps or reach the internet,
and the instructions tell it to say so instead of pretending."""
import json, time, urllib.request

from . import keys, llm

SYSTEM = """You are {name}, a voice assistant on the user's own computer. Everything you write is read aloud, so:
- Answer in one to three short, plain sentences unless asked for more. No markdown, lists, code, links, emoji or symbols.
- Be direct and warm, with a dry sense of humour used sparingly. Never describe yourself as an AI language model.
- You have no tools yet. You cannot look anything up, see the screen, open apps, read files, set timers or change anything.
  If asked to do one of these, say plainly that you can't do that yet. Never claim to have done something.
- You do not know today's news, weather or prices. Today is {today}. Say when you are unsure instead of guessing.
{extra}"""


def system(cfg):
    extra = (cfg.get("persona") or "").strip()
    who = (cfg.get("call_me") or "").strip()
    if who:
        extra = (extra + f"\nThe user likes to be called {who}.").strip()
    return SYSTEM.format(name=(cfg.get("name") or "Jarvis").capitalize(), today=time.strftime("%A, %d %B %Y"), extra=extra).strip()


def provider(cfg):
    """Which brain answers right now: 'claude', 'openai', 'local' or None. `brain` in the settings can force one."""
    want = cfg.get("brain", "auto")
    if want in ("auto", "claude") and keys.has("anthropic"):
        return "claude"
    if want in ("auto", "openai") and keys.has("openai") and cfg.get("openai_model"):
        return "openai"
    if want in ("auto", "local") and llm.usable(cfg):
        return "local"
    return None


def describe(cfg):
    p = provider(cfg)
    if p == "claude":
        return f"Claude ({cfg.get('claude_model')}), in the cloud"
    if p == "openai":
        return f"OpenAI ({cfg.get('openai_model')}), in the cloud"
    if p == "local":
        return f"local model ({llm.backend(cfg)}), on this machine"
    return "none"


class BrainError(Exception):
    """Something the user can act on; the message is safe to show and to say."""


def _claude(messages, cfg, cancel):
    import anthropic
    client = anthropic.Anthropic(api_key=keys.get("anthropic"), max_retries=1, timeout=60.0)
    try:
        # Effort low: a spoken answer should start quickly. If the model declines, the API retries on its default fallback.
        with client.beta.messages.stream(
            model=cfg.get("claude_model") or "claude-opus-5-5", max_tokens=1024, system=system(cfg), messages=messages,
            output_config={"effort": "low"}, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        ) as stream:
            for text in stream.text_stream:
                if cancel and cancel.is_set():
                    return
                yield text
            if stream.get_final_message().stop_reason == "refusal":
                yield " I can't help with that one."
    except anthropic.AuthenticationError:
        raise BrainError("The Claude API key was not accepted. Check it in the settings.")
    except anthropic.PermissionDeniedError:
        raise BrainError("That Claude API key is not allowed to use this model.")
    except anthropic.NotFoundError:
        raise BrainError(f"Claude does not know the model {cfg.get('claude_model')}. Change it in the settings.")
    except anthropic.RateLimitError:
        raise BrainError("Claude is rate limiting this key. Try again in a moment.")
    except anthropic.APIStatusError as e:
        raise BrainError(f"Claude returned an error ({e.status_code}).")
    except anthropic.APIConnectionError:
        raise BrainError("I can't reach Claude. Check the internet connection.")


def _openai(messages, cfg, cancel):
    body = {"model": cfg["openai_model"], "stream": False,
            "messages": [{"role": "system", "content": system(cfg)}] + messages}
    req = urllib.request.Request((cfg.get("openai_url") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + keys.get("openai")})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            yield json.load(r)["choices"][0]["message"]["content"] or ""
    except urllib.error.HTTPError as e:
        raise BrainError("The OpenAI API key was not accepted. Check it in the settings." if e.code == 401
                         else f"OpenAI returned an error ({e.code}). Check the model name in the settings.")
    except OSError:
        raise BrainError("I can't reach OpenAI. Check the internet connection.")


def _local(messages, cfg, cancel):
    try:
        yield llm.generate([{"role": "system", "content": system(cfg)}] + messages, cfg, 220)
    except Exception as e:
        raise BrainError(f"The local model failed ({str(e)[:80]}).")


def stream(messages, cfg, cancel=None):
    """Yield the answer as pieces of text. `messages` is the conversation: [{"role": "user"|"assistant", "content": str}, ...]."""
    p = provider(cfg)
    if p is None:
        raise BrainError("I have no brain yet. Add a Claude API key in the settings, or set up the local model.")
    yield from {"claude": _claude, "openai": _openai, "local": _local}[p](messages, cfg, cancel)
