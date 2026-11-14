"""API keys for cloud brains. A key lives in the operating system's own credential store (macOS Keychain, Windows
Credential Manager, the Secret Service on Linux), never in a config file, a log or the window. An environment variable
is read as a fallback so servers and CI can supply one."""
import os

SERVICE = "jarvis-ai"
ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def _ring():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def get(name):
    k = _ring()
    if k:
        try:
            v = k.get_password(SERVICE, name)
            if v:
                return v
        except Exception:
            pass
    return os.environ.get(ENV.get(name, ""), "")


def has(name):
    return bool(get(name))


def put(name, value):
    """Store a key. Raises RuntimeError when this machine has no credential store (then use the environment variable)."""
    value = (value or "").strip()
    if name not in ENV or not value or len(value) > 500 or any(c.isspace() for c in value):
        raise ValueError("that does not look like an API key")
    k = _ring()
    if not k:
        raise RuntimeError(f"no credential store on this machine; set the {ENV[name]} environment variable instead")
    try:
        k.set_password(SERVICE, name, value)
    except Exception as e:
        raise RuntimeError(f"the credential store refused it ({e}); set the {ENV[name]} environment variable instead")


def remove(name):
    k = _ring()
    if k:
        try:
            k.delete_password(SERVICE, name)
        except Exception:
            pass
