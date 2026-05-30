import langfuse

# Ensure Langfuse v2 compatibility for observe and get_client root-level imports
if not hasattr(langfuse, "observe"):
    from langfuse.decorators import observe

    langfuse.observe = observe

if not hasattr(langfuse, "get_client"):
    from langfuse import Langfuse

    _client_instance = None

    def get_client_compat():
        global _client_instance
        if _client_instance is None:
            _client_instance = Langfuse()
        return _client_instance

    langfuse.get_client = get_client_compat
