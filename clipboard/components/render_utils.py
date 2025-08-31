from typing import List, Tuple


def compute_computed_item_height(
    render_candidates: List[Tuple[int, str, str]],
    item_width: int,
    base_item_height: int,
) -> int:
    """Compute a suggested item height based on text lengths and image presence.

    render_candidates: list of (orig_idx, item_id, content)
    returns the computed item height in pixels.
    """
    max_text_lines = 0
    if render_candidates:
        chars_per_line = max(20, max(10, item_width // 8))
        for _, _, content in render_candidates:
            if not content:
                continue
            display_len = len((content or "").strip())
            lines = min(6, max(1, (display_len // chars_per_line) + 1))
            if lines > max_text_lines:
                max_text_lines = lines
    if max_text_lines > 1:
        line_height = 18
        computed_item_height = max(base_item_height, max_text_lines * line_height + 24)
    else:
        computed_item_height = base_item_height
    return computed_item_height
