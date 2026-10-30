def greeting(name: str) -> str:
    """Return a friendly message, including a fallback for blank input."""
    recipient = name.strip() or "friend"
    return f"Hello, {recipient}!"
