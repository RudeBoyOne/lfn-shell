import re
import subprocess
import sys

from gi.repository import GdkPixbuf, GLib, Gtk
from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.widgets.label import Label


class ClipBar(Box):
    def __init__(self, max_items=50, bar_height=56, item_width=260, **kwargs):
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

        # container horizontal (sem ScrolledWindow)
        self.row = Box(
            name="clipbar-row",
            orientation="h",
            spacing=6,
            h_expand=True,
            v_expand=True,
            h_align="fill",
            v_align="fill",
        )

        # adiciona a row diretamente
        self.add(self.row)

        # fixa a altura da barra
        self.set_size_request(-1, self.bar_height)

        self.max_items = max_items
        self.items = []
        self.selected_index = -1
        self.image_cache = {}

        GLib.idle_add(self._load_items)

    def _load_items(self):
        try:
            result = subprocess.run(
                ["cliphist", "list"],
                capture_output=True,
                check=True,
            )
            stdout_str = result.stdout.decode("utf-8", errors="replace")
            lines = [ln for ln in stdout_str.strip().split("\n") if ln.strip()]
            self.items = lines[: self.max_items]
            self._render_items()
        except subprocess.CalledProcessError as e:
            print(f"[clipbar] erro lendo cliphist: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[clipbar] erro inesperado: {e}", file=sys.stderr)
        return False

    def _render_items(self):
        self.row.children = []
        self.selected_index = -1

        if not self.items:
            self.row.add(Label(name="clipbar-empty", label="(Clipboard vazio)"))
            self.show_all()
            return

        for idx, line in enumerate(self.items):
            item_id, content = self._split_line(line)
            is_img = self._is_image_data(content)

            if is_img:
                btn = Button(
                    name="clipbar-item",
                    child=Box(
                        orientation="h",
                        spacing=6,
                        children=[
                            Image(name="clipbar-thumb"),
                            Label(name="clipbar-text", label="[Imagem]", ellipsization="end"),
                        ],
                    ),
                    tooltip_text="Imagem no clipboard",
                    on_clicked=lambda *_ , id=item_id: self._paste_item(id),
                    v_expand=True,
                    v_align="fill",
                )
                # largura fixa por item
                btn.set_size_request(self.item_width, -1)
                self._load_image_preview_async(item_id, btn)
            else:
                display = content.strip()
                if len(display) > 80:
                    display = display[:77] + "..."
                btn = Button(
                    name="clipbar-item",
                    child=Label(name="clipbar-text", label=display, ellipsization="end"),
                    tooltip_text=display,
                    on_clicked=lambda *_ , id=item_id: self._paste_item(id),
                    v_expand=True,
                    v_align="fill",
                )
                # largura fixa por item
                btn.set_size_request(self.item_width, -1)

            # navegação por teclado (setas esquerda/direita + Enter/Delete)
            btn.set_can_focus(True)
            btn.connect("key-press-event", self._on_item_key_press, item_id, idx)

            self.row.add(btn)

        self.show_all()

    def _split_line(self, line: str):
        parts = line.split("\t", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return "0", line

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
                if item_id in self.image_cache:
                    pixbuf = self.image_cache[item_id]
                else:
                    result = subprocess.run(
                        ["cliphist", "decode", item_id],
                        capture_output=True,
                        check=True,
                    )
                    loader = GdkPixbuf.PixbufLoader()
                    loader.write(result.stdout)
                    loader.close()
                    pixbuf = loader.get_pixbuf()

                    # thumbnail dimensionado pela altura da barra
                    padding = 12
                    max_size = max(1, min(72, self.bar_height - padding))
                    w, h = pixbuf.get_width(), pixbuf.get_height()
                    if w > h:
                        nw, nh = max_size, int(h * (max_size / w))
                    else:
                        nh, nw = max_size, int(w * (max_size / h))
                    pixbuf = pixbuf.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR)
                    self.image_cache[item_id] = pixbuf

                # aplica no primeiro filho do Box (Image)
                box = button.get_child()
                if box and box.get_children():
                    img = box.get_children()[0]
                    if isinstance(img, Image):
                        img.set_from_pixbuf(pixbuf)
            except Exception as e:
                print(f"[clipbar] erro carregando preview: {e}", file=sys.stderr)
            return False
        GLib.idle_add(load)

    def _paste_item(self, item_id):
        def paste():
            try:
                result = subprocess.run(
                    ["cliphist", "decode", item_id],
                    capture_output=True,
                    check=True,
                )
                subprocess.run(["wl-copy"], input=result.stdout, check=True)
            except subprocess.CalledProcessError as e:
                print(f"[clipbar] erro ao colar item: {e}", file=sys.stderr)
            return False
        GLib.idle_add(paste)

    def _delete_item(self, item_id):
        def delete():
            try:
                subprocess.run(["cliphist", "delete", item_id], check=True)
                GLib.idle_add(self._load_items)
            except subprocess.CalledProcessError as e:
                print(f"[clipbar] erro ao deletar item: {e}", file=sys.stderr)
            return False
        GLib.idle_add(delete)

    def _on_item_key_press(self, widget, event, item_id, idx):
        # Left/Right navegam, Enter cola, Delete remove
        from gi.repository import Gdk

        children = self.row.get_children()
        count = len(children)

        if event.keyval in (Gdk.KEY_Left, Gdk.KEY_Right) and count:
            idx = (idx - 1) % count if event.keyval == Gdk.KEY_Left else (idx + 1) % count
            self.selected_index = idx

            for i, child in enumerate(children):
                ctx = child.get_style_context()
                if i == idx:
                    ctx.add_class("selected")
                else:
                    ctx.remove_class("selected")

            children[idx].grab_focus()
            return True

        elif event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if 0 <= idx < len(self.items):
                self._paste_item(self.items[idx].split("\t", 1)[0])
                return True

        elif event.keyval == Gdk.KEY_Delete:
            if 0 <= idx < len(self.items):
                self._delete_item(self.items[idx].split("\t", 1)[0])
                return True

        return False  # não tratado, propaga o evento

    def _move_focus(self, new_index):
        children = self.row.get_children()
        if not children:
            return
        new_index = max(0, min(new_index, len(children) - 1))
        children[new_index].grab_focus()