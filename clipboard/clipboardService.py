import subprocess
from typing import List, Tuple
import logging

from fabric.core.service import Service, Signal, Property
from fabric import Fabricator

logger = logging.getLogger(__name__)


class ClipboardService(Service):
    @Property(list, flags="read-write")
    def items(self) -> list:
        return self._items

    @items.setter
    def items(self, value: list):
        # evita notify desnecessário
        if value == getattr(self, "_items", []):
            return
        self._items = value

    @Property(int, flags="read-write")
    def selected_index(self) -> int:
        return self._selected_index

    @selected_index.setter
    def selected_index(self, value: int):
        # evita notify desnecessário
        if value == getattr(self, "_selected_index", -1):
            return
        self._selected_index = value

    @Signal
    def close_requested(self) -> None: ...

    def __init__(self, interval_ms: int = 1500, **kwargs):
        super().__init__(**kwargs)
        self._items: List[Tuple[str, str]] = []
        self._selected_index: int = -1
        self._last_raw: str = ""

        # Fabricator: atualiza itens periodicamente
        # Use função Python (sem shell) e normalize o texto
        def poll_history(_f) -> str:
            try:
                out = subprocess.run(
                    ["cliphist", "list"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                return out.strip()
            except subprocess.CalledProcessError:
                logger.debug("cliphist list failed", exc_info=True)
                return ""

        self._fabric = Fabricator(
            interval=interval_ms,
            default_value="",
            poll_from=poll_history,
            on_changed=lambda f, v: self._on_history_changed(v),
        )

    # chamado pelo Fabricator
    def _on_history_changed(self, raw: str):
        raw_norm = (raw or "").strip()
        if raw_norm == self._last_raw:
            return  # nada mudou, não notifica
        self._last_raw = raw_norm

        lines = [ln for ln in raw_norm.splitlines() if ln.strip()]
        parsed: List[Tuple[str, str]] = []
        for ln in lines:
            # "id \t preview"
            parts = ln.split("\t", 1)
            item_id = parts[0]
            content = parts[1] if len(parts) == 2 else ""
            parsed.append((item_id, content))

        if parsed != self._items:
            self.items = parsed
            # corrige seleção
            if not parsed:
                self.selected_index = -1
            elif self.selected_index < 0 or self.selected_index >= len(parsed):
                self.selected_index = 0

    # navegação
    def move_left(self):
        self._move(-1)

    def move_right(self):
        self._move(+1)

    def _move(self, delta: int):
        if not self.items:
            return
        idx = self.selected_index if self.selected_index >= 0 else 0
        new_idx = idx + delta
        # não permitir navegação circular: clamp entre 0 e len(items)-1
        new_idx = max(0, min(new_idx, len(self.items) - 1))
        # se não mudou, não reatribui (evita notify desnecessário)
        if new_idx != idx:
            self.selected_index = new_idx

    # ativar/colar
    def activate(self):
        if not self.items or self.selected_index < 0:
            return
        item_id, _ = self.items[self.selected_index]
        self.paste_item(item_id)
        # fecha após copiar
        self.request_close()

    def activate_index(self, idx: int):
        if not self.items:
            return
        if 0 <= idx < len(self.items):
            if idx != self.selected_index:
                self.selected_index = idx
            self.activate()

    def paste_item(self, item_id: str):
        try:
            result = subprocess.run(["cliphist", "decode", item_id], capture_output=True, check=True)
            subprocess.run(["wl-copy"], input=result.stdout, check=True)
        except subprocess.CalledProcessError:
            logger.exception("paste_item failed for %s", item_id)

    def decode_item(self, item_id: str) -> bytes:
        """Decode an item using cliphist and return raw bytes.

        Centraliza a chamada ao `cliphist decode` para que outros componentes
        (por exemplo, UI) não executem subprocess diretamente.
        Retorna bytes vazios em caso de falha.
        """
        try:
            result = subprocess.run(["cliphist", "decode", item_id], capture_output=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError:
            logger.debug("decode_item failed for %s", item_id, exc_info=True)
            return b""

    def delete_current(self):
        if not self.items or self.selected_index < 0:
            return
        item_id, _ = self.items[self.selected_index]
        self.delete_item(item_id)

    def delete_item(self, item_id: str):
        try:
            subprocess.run(["cliphist", "delete", item_id], check=True)
        except subprocess.CalledProcessError:
            logger.exception("delete_item failed for %s", item_id)
        finally:
            # Fabricator vai atualizar no próximo tick
            pass

    def request_close(self):
        self.close_requested()