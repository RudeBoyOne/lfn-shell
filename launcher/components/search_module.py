from __future__ import annotations

from typing import Optional
from urllib.parse import quote_plus

from launcher.components.query_models import QueryAction, RouterResult


_PREFIX = "?"


def handle_query(query: str) -> Optional[RouterResult]:
    if not query.startswith(_PREFIX):
        return None

    term = query[len(_PREFIX) :].strip()
    result = RouterResult(consume=True)

    if not term:
        result.items.append(
            (
                "__special__:web-search:hint",
                "Pesquisar na web",
            )
        )
        return result

    item_id = f"__special__:web-search:{quote_plus(term)}"
    result.items.append((item_id, f'Pesquisar "{term}" na web'))
    result.actions[item_id] = QueryAction(
        kind="web-search",
        payload={"term": term},
    )
    return result
