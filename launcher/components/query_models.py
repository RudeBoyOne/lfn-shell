from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class QueryAction:
    kind: str
    payload: Dict[str, str]


@dataclass
class RouterResult:
    items: List[Tuple[str, str]] = field(default_factory=list)
    actions: Dict[str, QueryAction] = field(default_factory=dict)
    consume: bool = False

    @classmethod
    def empty(cls) -> "RouterResult":
        return cls()
