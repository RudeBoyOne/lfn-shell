from __future__ import annotations

from typing import Any, ClassVar

from gi.repository import GLib


class SingletonLayerMixin:
    """Reusable mixin to keep GTK overlay layers as singletons."""

    _instance: ClassVar[SingletonLayerMixin | None] = None

    def __new__(cls, *_args: Any, **_kwargs: Any):
        existing = cls._instance
        if existing is not None:

            def _present() -> bool:
                cls._present_existing(existing)
                return False

            GLib.idle_add(_present)
            return existing

        instance = super().__new__(cls)
        cls._instance = instance
        return instance

    def _prepare_singleton(self) -> bool:
        if getattr(self, "_singleton_initialized", False):
            return False
        self._singleton_initialized = True
        return True

    def _register_singleton_cleanup(self) -> None:
        self.connect("destroy", self._on_singleton_destroy)

    @classmethod
    def _present_existing(cls, instance: Any) -> None:
        try:
            instance.present()
        except (AttributeError, RuntimeError):
            return
        cls._focus_existing(instance)

    @staticmethod
    def _focus_existing(instance: Any) -> None:
        child = getattr(instance, "child", None)
        grab_focus = getattr(child, "grab_focus", None)
        if callable(grab_focus):
            try:
                grab_focus()
            except (AttributeError, RuntimeError):
                pass

    def _on_singleton_destroy(self, *_: Any) -> None:
        type(self)._instance = None
        self._singleton_initialized = False
        self._after_singleton_destroy()

    def _after_singleton_destroy(self) -> None:
        """Hook for subclasses that need extra cleanup."""
        return
