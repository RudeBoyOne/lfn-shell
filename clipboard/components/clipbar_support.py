from typing import Iterable, List, Sequence, Tuple

RenderCandidate = Tuple[int, str, str]


def normalize_query(text: str) -> str:
    """Return a lowercase, stripped query string."""
    return (text or "").strip().lower()


def extract_terms(query: str) -> List[str]:
    """Split a normalized query into non-empty terms."""
    norm = normalize_query(query)
    return [term for term in norm.split() if term]


def build_render_candidates(
    items: Sequence[Tuple[str, str]],
    terms: Iterable[str],
    max_items: int,
) -> List[RenderCandidate]:
    """Create render candidates after applying terms."""
    terms_list = [t for t in terms if t]
    if not items:
        return []

    def _match(content: str) -> bool:
        if not terms_list:
            return True
        lowered = (content or "").lower()
        return all(term in lowered for term in terms_list)

    candidates: List[RenderCandidate] = []
    for index, (item_id, content) in enumerate(items):
        if _match(content):
            candidates.append((index, item_id, content))
            if len(candidates) >= max(0, max_items):
                break
    return candidates


def adjust_selection_for_candidates(
    selected_index: int,
    candidates: Sequence[RenderCandidate],
    enforce_bounds: bool,
) -> int:
    """Clamp the selection to the available candidate indices when needed."""
    if not candidates:
        return selected_index
    if not enforce_bounds:
        return selected_index

    lowest = candidates[0][0]
    highest = candidates[-1][0]
    if selected_index < lowest:
        return lowest
    if selected_index > highest:
        return highest
    return selected_index
