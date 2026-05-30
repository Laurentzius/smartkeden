"""
One-time Langfuse compatibility shim.  Import this module once at application
startup (it is idempotent) to ensure `langfuse.observe` and
`langfuse.get_client` are available regardless of the installed Langfuse
package version.
"""

import langfuse

_ALREADY_PATCHED = False


def _ensure_langfuse_compat() -> None:
    global _ALREADY_PATCHED
    if _ALREADY_PATCHED:
        return

    if not hasattr(langfuse, "observe"):
        from langfuse.decorators import observe as _observe

        langfuse.observe = _observe  # type: ignore[attr-defined]

    if not hasattr(langfuse, "get_client"):
        from langfuse import Langfuse as _Langfuse

        _client_instance = None

        def _get_client_compat():
            global _client_instance
            if _client_instance is None:
                _client_instance = _Langfuse()
            return _client_instance

        langfuse.get_client = _get_client_compat  # type: ignore[attr-defined]

    _ALREADY_PATCHED = True


_ensure_langfuse_compat()
