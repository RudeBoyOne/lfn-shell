from typing import Callable


def handle_search_change(entry_getter: Callable[[], str]) -> str:
    """Normalize and return search text from an entry getter (lowercase, stripped)."""
    try:
        text = (entry_getter() or "").strip().lower()
    except Exception:
        text = ""
    return text
