from typing import Callable, Iterable, List
import html
import re


def handle_search_change(entry_getter: Callable[[], str]) -> str:
    """Normalize and return search text from an entry getter (lowercase, stripped)."""
    try:
        text = (entry_getter() or "").strip().lower()
    except Exception:
        text = ""
    return text


def highlight_markup_multi(text: str, needles: Iterable[str]) -> str:
    """
    Destaque múltiplos termos em `text` usando Pango Markup sem quebrar entidades.
    - Case-insensitive.
    - Ignora termos com tamanho < 2.
    - Evita duplicação de termos (normalização por lower()).
    """
    raw = text or ""
    norm_terms: List[str] = []
    seen = set()
    for t in needles or []:
        tt = (t or "").strip().lower()
        if len(tt) < 2:
            continue
        if tt in seen:
            continue
        seen.add(tt)
        norm_terms.append(tt)
    if not norm_terms:
        return html.escape(raw)
    try:
        # combinar todos os termos em um único regex com grupos
        pattern = re.compile("(" + "|".join(re.escape(t) for t in norm_terms) + ")", re.IGNORECASE)
        out: list[str] = []
        last = 0
        for m in pattern.finditer(raw):
            # trecho antes
            if m.start() > last:
                out.append(html.escape(raw[last:m.start()]))
            # match destacado
            out.append("<b>")
            out.append(html.escape(m.group(0)))
            out.append("</b>")
            last = m.end()
        # resto
        if last < len(raw):
            out.append(html.escape(raw[last:]))
        return "".join(out)
    except Exception:
        return html.escape(raw)


def highlight_markup(text: str, needle: str) -> str:
    """Compat: delega para a versão multi-termo com uma string."""
    return highlight_markup_multi(text, [needle] if needle else [])
