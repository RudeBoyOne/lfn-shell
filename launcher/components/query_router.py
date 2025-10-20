from __future__ import annotations

from typing import Callable, Iterable

from launcher.components import calculator_module, search_module
from launcher.components.query_models import RouterResult


Handler = Callable[[str], object]


def route_special_query(query: str) -> RouterResult:
    if not query:
        return RouterResult.empty()

    for handler in _handlers():
        result = handler(query)
        if isinstance(result, RouterResult):
            return result
    return RouterResult.empty()


def _handlers() -> Iterable[Callable[[str], RouterResult | None]]:
    return (
        calculator_module.handle_query,
        search_module.handle_query,
    )
