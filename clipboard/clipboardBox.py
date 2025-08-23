from typing import Optional, List, Tuple
import re
import sys

import gi
try:
    gi.require_version("GdkPixbuf", "2.0")
except Exception:
    pass
try:
    gi.require_version("Gtk", "3.0")
except Exception:
    # if Gtk already loaded (e.g. Gtk 4), allow fallback and hope the runtime is compatible
    pass
from gi.repository import GdkPixbuf, GLib, Gtk
from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.widgets.entry import Entry
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow

from clipboard.clipboardService import ClipboardService


class ClipBar(Box):
    def __init__(self, max_items=50, bar_height=56, item_width=260, controller: Optional[ClipboardService] = None, item_height: Optional[int] = None, **kwargs):
        super().__init__(
            name="clipbar-root",
            spacing=6,
            orientation="v",
            h_expand=True,
            v_expand=True,
            **kwargs,
        )

        self.bar_height = bar_height
        self.item_width = item_width
        # item_height defaulta para bar_height menos padding se não informado
        self.item_height = item_height or max(56, self.bar_height - 4)
        self.max_items = max_items

        # linha de itens (não expandir horizontal para permitir overflow)
        self.row = Box(
            name="clipbar-row",
            orientation="h",
            spacing=16,  # espaçamento maior entre cards
            h_expand=False,
            v_expand=True,
            h_align="fill",
            v_align="fill",
            style_classes="clipbar-row-padding",
        )

        # ScrolledWindow com barras visíveis
        self.scroll = ScrolledWindow(
            name="clipbar-scroll",
            child=self.row,
            h_expand=True,
            v_expand=True,
            h_align="fill",
            v_align="fill",
            propagate_width=False,
            propagate_height=False,
        )
        # barras horizontais visíveis quando necessário; sem overlay
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        try:
            self.scroll.set_overlay_scrolling(False)
        except Exception:
            pass

        # campo de busca acima da lista (debounced)
        self.search_entry = Entry(placeholder="Buscar...", style_classes="clipbar-search", h_expand=True)
        # cada mudança agenda um debounce; implementado em _schedule_search_update
        self.search_entry.connect("changed", lambda *_: self._schedule_search_update())

        self.add(self.search_entry)
        self.add(self.scroll)
        self.set_size_request(-1, self.bar_height)

        # estado UI
        self._buttons: List[Button] = []
        self._content_boxes: List[Box] = []
        # mapeamento: posição renderizada -> índice original em controller.items
        self._rendered_orig_indices: List[int] = []
        # filtro atual (lowercase)
        self._filter_text: str = ""
        # debounce id para a busca (GLib.timeout_add)
        self._search_debounce_id = 0

        # integra com o Service
        self.controller = controller
        if self.controller:
            self.controller.connect("notify::items", lambda *_: self._render_items())
            self.controller.connect("notify::selected-index", lambda *_: self._apply_selection_styles())

        # render inicial
        self._render_items()
        # garantir foco no campo de busca quando o ClipBar abrir
        try:
            GLib.idle_add(self._focus_search_entry)
        except Exception:
            try:
                # fallback direto
                self.search_entry.grab_focus()
            except Exception:
                pass

    def _render_items(self):
        # limpa
        self.row.children = []
        self._buttons.clear()
        self._content_boxes.clear()

        # coleta itens do service e aplica filtro (case-insensitive)
        all_items = (self.controller.items if self.controller else [])
        if self._filter_text:
            filtered = [(i, itm_id, txt) for i, (itm_id, txt) in enumerate(all_items) if self._filter_text in (txt or "").lower()]
        else:
            filtered = [(i, itm_id, txt) for i, (itm_id, txt) in enumerate(all_items)]

        # aplicar limite de max_items
        render_candidates = filtered[: self.max_items]

        # calcular altura desejada para os items de texto (wrap)
        # heurística: calcular número de linhas aproximado a partir do comprimento do texto
        max_text_lines = 0
        if render_candidates:
            chars_per_line = max(20, max(10, self.item_width // 8))
            for _, _, content in render_candidates:
                if not self._is_image_data(content):
                    display_len = len((content or "").strip())
                    lines = min(6, max(1, (display_len // chars_per_line) + 1))
                    if lines > max_text_lines:
                        max_text_lines = lines

        # se houver textos que demandam mais linhas, aumentamos a altura dos cards e do bar
        if max_text_lines > 1:
            line_height = 18  # px aproximado por linha para o tamanho de fonte atual
            computed_item_height = max(self.item_height, max_text_lines * line_height + 24)
        else:
            computed_item_height = self.item_height

        # ajustar a altura do clipbar (visual) para acomodar os cards maiores
        try:
            self.set_size_request(-1, max(self.bar_height, computed_item_height + 16))
        except Exception:
            pass

        if not render_candidates:
            msg = "(Clipboard vazio)" if not all_items else "(nenhum resultado)"
            self.row.add(Label(name="clipbar-empty", label=msg))
            self.show_all()
            return
        # reset mapping
        self._rendered_orig_indices = []

        for render_idx, (orig_idx, item_id, content) in enumerate(render_candidates):
            is_img = self._is_image_data(content)

            if is_img:
                # centraliza a imagem dentro do card (horizontal e verticalmente)
                content_box = Box(
                    orientation="v",  # empilha conteúdo verticalmente
                    spacing=8,
                    h_expand=True,
                    v_expand=True,
                    h_align="center",
                    v_align="center",
                    children=[Image(name="clipbar-thumb")],
                    style_classes="clipbar-image-card",
                )
            else:
                display = content.strip()
                # aumentar quantidade mostrada e permitir quebra de linha
                if len(display) > 600:
                    display = display[:597] + "..."
                content_box = Box(
                    orientation="v",
                    spacing=6,
                    h_expand=True,
                    v_expand=True,
                    h_align="center",
                    v_align="center",  # centraliza verticalmente o texto no card
                    children=[
                        Label(
                            name="clipbar-text",
                            label=display,
                            ellipsization="end",
                            wrap=True,  # permite múltiplas linhas
                            xalign=0.5,
                            yalign=0.5,
                            style_classes="clipbar-text-label",
                        )
                    ],
                    style_classes="clipbar-text-card",
                )

            btn = Button(
                name="clipbar-item",
                child=content_box,
                tooltip_text="[Imagem]" if is_img else (content or "").strip(),
                on_clicked=lambda *_, i=orig_idx: (self.controller.activate_index(i) if self.controller else None),
                v_expand=False,
                v_align="center",
            )
            # agora define altura fixa maior para dar aspecto de card
            # definir altura do botão com a altura calculada (ajustada para textos longos)
            btn.set_size_request(self.item_width, computed_item_height)
            btn.set_can_focus(True)

            self.row.add(btn)
            self._buttons.append(btn)
            self._content_boxes.append(content_box)
            self._rendered_orig_indices.append(orig_idx)

            if is_img:
                self._load_image_preview_async(item_id, btn)

        self.show_all()
        self._apply_selection_styles()

    def _apply_selection_styles(self):
        sel = self.controller.selected_index if self.controller else -1
        for i, (btn, content) in enumerate(zip(self._buttons, self._content_boxes)):
            ctx = btn.get_style_context()
            if i == sel:
                ctx.add_class("suggested-action")
                content.style = "padding: 8px; border-radius: 8px; background-color: rgba(255,255,255,0.12);"
            else:
                ctx.remove_class("suggested-action")
                content.style = "padding: 8px; border-radius: 8px;"
        # rola a scroll view para mostrar o item selecionado (se houver)
        try:
            if 0 <= sel < len(self._buttons):
                btn = self._buttons[sel]
                # certifica-se que o botão está visível horizontalmente
                hadj = self.scroll.get_hadjustment()
                alloc = btn.get_allocation()
                view_x = hadj.get_value()
                view_w = int(hadj.get_page_size())
                item_x = alloc.x
                item_w = alloc.width
                # se item está à esquerda do view ou à direita, ajuste
                if item_x < view_x:
                    hadj.set_value(max(0, item_x))
                elif item_x + item_w > view_x + view_w:
                    hadj.set_value(min(hadj.get_upper() - view_w, item_x + item_w - view_w))
                # garantir foco no botão selecionado
                try:
                    btn.grab_focus()
                except Exception:
                    pass
        except Exception:
            pass

    def focus_selected(self):
        """Traz o item selecionado à vista e foca o botão correspondente.

        Separado de `_apply_selection_styles` para permitir agendamento via
        `GLib.idle_add` quando necessário (por exemplo, depois de um key event).
        """
        try:
            sel = self.controller.selected_index if self.controller else -1
            if 0 <= sel < len(self._buttons):
                btn = self._buttons[sel]
                hadj = self.scroll.get_hadjustment()
                alloc = btn.get_allocation()
                view_x = hadj.get_value()
                view_w = int(hadj.get_page_size())
                item_x = alloc.x
                item_w = alloc.width
                if item_x < view_x:
                    hadj.set_value(max(0, item_x))
                elif item_x + item_w > view_x + view_w:
                    hadj.set_value(min(hadj.get_upper() - view_w, item_x + item_w - view_w))
                try:
                    btn.grab_focus()
                except Exception:
                    pass
        except Exception:
            pass

    def _is_image_data(self, content: str) -> bool:
        return (
            content.startswith("data:image/")
            or content.startswith("\x89PNG")
            or content.startswith("GIF8")
            or content.startswith("\xff\xd8\xff")
            or re.match(r"^\s*<img\s+", content) is not None
            or ("binary" in content.lower() and any(ext in content.lower() for ext in ["jpg", "jpeg", "png", "bmp", "gif"]))
        )

    def _load_image_preview_async(self, item_id, button):
        def load():
            try:
                # Decodifica via controller apenas; não executar subprocess aqui.
                raw = None
                if self.controller and hasattr(self.controller, "decode_item"):
                    try:
                        raw = self.controller.decode_item(item_id)
                    except Exception as e:
                        # falha ao decodificar no controller -> não carregar preview
                        print(f"[clipbar] controller.decode_item falhou: {e}", file=sys.stderr)
                        raw = None

                # se não obtemos bytes válidos, aborta sem chamar subprocess
                if not raw:
                    return False

                loader = GdkPixbuf.PixbufLoader()
                if isinstance(raw, str):
                    raw = raw.encode("utf-8", errors="ignore")
                loader.write(raw)
                loader.close()
                pixbuf = loader.get_pixbuf()

                padding = 16
                # limitar preview ao tamanho do card (largura menos padding, altura menos espaço para texto)
                max_w = max(1, self.item_width - padding)
                max_h = max(1, self.item_height - 48)
                w, h = pixbuf.get_width(), pixbuf.get_height()
                scale = min(max_w / w, max_h / h, 1.0)
                nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
                pixbuf = pixbuf.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR)

                box = button.get_child()
                if box and box.get_children():
                    img = box.get_children()[0]
                    if isinstance(img, Image):
                        img.set_from_pixbuf(pixbuf)
            except Exception as e:
                print(f"[clipbar] erro carregando preview: {e}", file=sys.stderr)
            return False
        GLib.idle_add(load)

    def _on_search_changed(self, *args):
        """Handler chamado quando o texto de busca muda; atualiza o filtro e re-renderiza."""
        # obter texto em lowercase para busca case-insensitive
        try:
            text = (self.search_entry.get_text() or "").strip().lower()
        except Exception:
            text = ""
        # armazenar e atualizar view na thread principal
        self._filter_text = text
        # re-renderiza (proteção leve para evitar crashes durante digitação)
        try:
            self._render_items()
        except Exception:
            pass

    def _schedule_search_update(self, debounce_ms: int = 200):
        """Agenda um timeout debounced para aplicar o filtro da busca.

        Se já houver um timeout agendado, cancela e re-agenda.
        """
        try:
            # remove qualquer agendamento anterior
            if getattr(self, "_search_debounce_id", 0):
                try:
                    GLib.source_remove(self._search_debounce_id)
                except Exception:
                    pass
            # agenda novo timeout
            self._search_debounce_id = GLib.timeout_add(int(debounce_ms), self._perform_debounced_search)
        except Exception:
            # fallback: chamada direta sem debounce
            GLib.idle_add(self._on_search_changed)

    def _perform_debounced_search(self):
        """Executa a atualização de busca agendada. Retorna False para não repetir a timeout."""
        try:
            self._on_search_changed()
        except Exception:
            pass
        # reset id e evitar re-execução
        try:
            self._search_debounce_id = 0
        except Exception:
            pass
        return False

    def _focus_search_entry(self):
        """Tenta focar o campo de busca; usado via GLib.idle_add após criação."""
        try:
            if hasattr(self, "search_entry") and self.search_entry:
                self.search_entry.grab_focus()
                return False
        except Exception:
            pass
        return False