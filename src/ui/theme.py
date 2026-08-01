"""Design system and reusable widgets for the Cookie Run Auto Bot desktop UI.

The interface intentionally keeps the familiar dark working environment while
using a softer indigo palette, clear hierarchy, larger touch targets and
consistent elevated surfaces.  All views consume these primitives so the
application stays visually coherent as it grows.
"""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Optional

import ttkbootstrap as ttk


# ---------------------------------------------------------------------------
# Visual tokens
# ---------------------------------------------------------------------------
THEME_NAME = "darkly"

# Layout
SIDEBAR_WIDTH = 272
SIDEBAR_WIDTH_COLLAPSED = 72
SIDEBAR_MIN_DRAG_WIDTH = 72
SIDEBAR_MAX_DRAG_WIDTH = 420
SIDEBAR_COLLAPSE_AT = 168
SASH_WIDTH = 5
PAD = 24
PAD_COMPACT = 16

# Responsive breakpoints
BP_NARROW = 880
BP_COMPACT = 1080
BP_WIDE = 1500
RESIZE_DEBOUNCE_MS = 90

# App palette.  These values are used by custom canvas/tk widgets; ttkbootstrap
# still supplies its standard semantic colors for regular controls.
APP_BG = "#0D1020"
APP_BG_ALT = "#11152A"
SIDEBAR_BG = "#111426"
SIDEBAR_ELEVATED = "#181C32"
SURFACE = "#191D33"
SURFACE_RAISED = "#202640"
SURFACE_HOVER = "#2A3152"
SURFACE_MUTED = "#15192C"
BORDER = "#323B61"
BORDER_SOFT = "#262D4B"
TEXT = "#F4F6FF"
TEXT_MUTED = "#AAB3D1"
TEXT_DIM = "#7680A8"
PRIMARY = "#8B7BFF"
PRIMARY_HOVER = "#A59AFF"
PRIMARY_SOFT = "#2C2854"
ACCENT_GOLD = "#FFC76A"
ACCENT_CYAN = "#62D7F5"
SUCCESS = "#47D39B"
SUCCESS_SOFT = "#143D3A"
DANGER = "#FF718B"
DANGER_SOFT = "#492238"
WARNING = "#FFB86B"
LOG_BG = "#0A0D18"
LOG_FG = "#9BE9D0"

# Typography — Rounded, friendly aesthetic aligned with Cookie Run brand
FONT_BRAND = ("Segoe UI Variable", 18, "bold")
FONT_EYEBROW = ("Segoe UI Variable", 8, "bold")
FONT_TITLE = ("Segoe UI Variable", 17, "bold")
FONT_H1 = ("Segoe UI Variable", 24, "bold")
FONT_H2 = ("Segoe UI Variable", 14, "bold")
FONT_H3 = ("Segoe UI Variable", 12, "bold")
FONT_SUBTITLE = ("Segoe UI Variable", 10, "normal")
FONT_BODY = ("Segoe UI Variable", 10, "normal")
FONT_BODY_BOLD = ("Segoe UI Variable", 10, "bold")
FONT_SMALL = ("Segoe UI Variable", 9, "normal")
FONT_STAT_VALUE = ("Segoe UI Variable", 20, "bold")
FONT_STAT_LABEL = ("Segoe UI Variable", 8, "bold")
FONT_MONO = ("Fira Code", 9, "normal")


@dataclass(frozen=True)
class Palette:
    """Semantic color groups for custom widgets."""

    name: str
    accent: str
    accent_soft: str
    icon: str


STAT_PALETTES = {
    "primary": Palette("primary", PRIMARY, PRIMARY_SOFT, PRIMARY_HOVER),
    "info": Palette("info", ACCENT_CYAN, "#153A52", "#A2EBFC"),
    "success": Palette("success", SUCCESS, SUCCESS_SOFT, "#A4F4CE"),
    "warning": Palette("warning", ACCENT_GOLD, "#4B3820", "#FFE1A6"),
    "danger": Palette("danger", DANGER, DANGER_SOFT, "#FFB6C3"),
    "secondary": Palette("secondary", TEXT_MUTED, "#252A42", "#D7DCF0"),
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def columns_for_width(width: int, min_col_width: int, minimum: int = 1,
                      maximum: Optional[int] = None) -> int:
    """Return an accessible number of equal-width grid columns."""
    if width <= 0:
        return minimum
    count = max(minimum, width // min_col_width)
    return min(count, maximum) if maximum else count


def debounce(widget: tk.Misc, delay_ms: int, fn: Callable):
    """Debounce resize/UI callbacks to keep window dragging fluid."""
    state = {"job": None}

    def _debounced(*args, **kwargs):
        if state["job"] is not None:
            try:
                widget.after_cancel(state["job"])
            except Exception:
                pass
        state["job"] = widget.after(delay_ms, lambda: fn(*args, **kwargs))

    return _debounced


def _hex_to_rgb(value: str):
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _rgb_to_hex(value):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(channel))) for channel in value)


def mix(first: str, second: str, amount: float) -> str:
    """Blend two hex colors; amount=0 keeps the first color."""
    try:
        left, right = _hex_to_rgb(first), _hex_to_rgb(second)
        return _rgb_to_hex(tuple(left[i] + (right[i] - left[i]) * amount for i in range(3)))
    except Exception:
        return first





def palette_for(bootstyle: str | None) -> Palette:
    """Map a ttk semantic style to a custom surface palette."""
    key = (bootstyle or "secondary").split("-")[0].lower()
    return STAT_PALETTES.get(key, STAT_PALETTES["secondary"])


def configure_design_system() -> None:
    """Apply calm defaults to ttk controls after the application root exists."""
    try:
        style = ttk.Style()
        style.configure("TFrame", background=SURFACE)
        style.configure("TLabelframe", background=SURFACE, bordercolor=BORDER_SOFT)
        style.configure("TLabelframe.Label", background=SURFACE, foreground=TEXT, font=FONT_H3)
        style.configure("TLabel", background=SURFACE, foreground=TEXT, font=FONT_BODY)
        # ttkbootstrap's stock secondary tone
        style.configure("secondary.TLabel", background=SURFACE, foreground=TEXT_MUTED)
        style.configure("light.TLabel", background=SURFACE, foreground=TEXT)
        style.configure("TButton", font=FONT_BODY_BOLD, padding=(12, 8))
        style.configure("secondary.Outline.TButton", foreground=TEXT_MUTED, bordercolor=TEXT_DIM)
        style.map("secondary.Outline.TButton", foreground=[("active", TEXT), ("!disabled", TEXT_MUTED)])
        style.configure("secondary.TButton", foreground=TEXT, background=SURFACE_RAISED)
        style.configure("TEntry", padding=(10, 8), fieldbackground=SURFACE_RAISED)
        style.configure("TCheckbutton", background=SURFACE)
        style.configure("Roundtoggle.Toolbutton", background=SURFACE)
        style.configure("success.Roundtoggle.Toolbutton", background=SURFACE)
        style.map("Roundtoggle.Toolbutton", background=[("selected", SURFACE), ("!selected", SURFACE)])
        style.map("success.Roundtoggle.Toolbutton", background=[("selected", SURFACE), ("!selected", SURFACE)])
        style.configure("TCombobox", padding=(9, 7), fieldbackground=SURFACE_RAISED)
        style.configure("TNotebook", background=APP_BG, borderwidth=0)
        style.configure("TNotebook.Tab", font=FONT_BODY_BOLD, padding=(14, 9))
        style.configure("Vertical.TScrollbar", background=SURFACE_RAISED, troughcolor=APP_BG)
    except Exception:
        # Styling should never stop the bot from launching.
        pass


def apply_window_chrome(window: tk.Misc, background: str = APP_BG) -> None:
    """Set a stable application background and optional Windows acrylic."""
    try:
        window.configure(background=background)
    except Exception:
        pass
    configure_design_system()


# ---------------------------------------------------------------------------
# Window effect
# ---------------------------------------------------------------------------
GLASS_OPACITY = 0.97


def enable_acrylic(window: tk.Misc, tint: str = APP_BG, opacity: float | None = None) -> None:
    """Apply a restrained translucent surface where the OS supports it.

    The opacity stays intentionally high so the UI preserves contrast and log
    text remains readable.  Every OS-specific operation is best-effort.
    """
    if opacity is None:
        opacity = GLASS_OPACITY
    try:
        window.update_idletasks()
    except Exception:
        pass

    if sys.platform.startswith("win"):
        try:
            _enable_acrylic_windows(window, tint, opacity)
        except Exception:
            pass
    try:
        window.attributes("-alpha", opacity)
    except Exception:
        pass


def _enable_acrylic_windows(window: tk.Misc, tint_hex: str, opacity: float) -> None:
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(window.winfo_id())
    if not hwnd:
        return

    class ACCENTPOLICY(ctypes.Structure):
        _fields_ = [
            ("AccentState", ctypes.c_int),
            ("AccentFlags", ctypes.c_int),
            ("GradientColor", ctypes.c_uint),
            ("AnimationId", ctypes.c_int),
        ]

    class WINCOMPATTRDATA(ctypes.Structure):
        _fields_ = [
            ("Attribute", ctypes.c_int),
            ("Data", ctypes.POINTER(ACCENTPOLICY)),
            ("SizeOfData", ctypes.c_size_t),
        ]

    red, green, blue = _hex_to_rgb(tint_hex)
    alpha = max(0, min(255, int(255 * (1 - opacity))))
    policy = ACCENTPOLICY(4, 2, (alpha << 24) | (blue << 16) | (green << 8) | red, 0)
    data = WINCOMPATTRDATA(19, ctypes.pointer(policy), ctypes.sizeof(policy))
    set_attribute = user32.SetWindowCompositionAttribute
    set_attribute.argtypes = [ctypes.c_void_p, ctypes.POINTER(WINCOMPATTRDATA)]
    set_attribute(hwnd, ctypes.pointer(data))


# ---------------------------------------------------------------------------
# Shared labels and surfaces
# ---------------------------------------------------------------------------
def make_eyebrow(parent: tk.Misc, text: str, color: str = PRIMARY, **kwargs) -> tk.Label:
    """Small all-caps label used to establish visual hierarchy."""
    bg = kwargs.pop("bg", _widget_bg(parent))
    return tk.Label(parent, text=text.upper(), bg=bg, fg=color, font=FONT_EYEBROW,
                    anchor="w", **kwargs)


def status_badge(parent: tk.Misc, running: bool) -> tk.Label:
    """Return a readable state chip rather than relying on color alone."""
    if running:
        text, bg, fg = "●  กำลังทำงาน", SUCCESS_SOFT, "#A4F4CE"
    else:
        text, bg, fg = "○  หยุดทำงาน", "#282D46", "#CCD3EA"
    return tk.Label(parent, text=text, bg=bg, fg=fg, font=FONT_SMALL,
                    padx=10, pady=5, anchor="center")


def device_chip(parent: tk.Misc, text: str) -> tk.Label:
    return tk.Label(parent, text=text, bg="#222943", fg="#C9D2EE", font=FONT_MONO,
                    padx=9, pady=4, anchor="w")


class ScrollableFrame(tk.Frame):
    """A minimal, color-consistent vertically scrollable frame."""

    def __init__(self, parent, bootstyle="dark", bg: Optional[str] = None, **kwargs):
        surface = bg or (SIDEBAR_BG if bootstyle == "dark" else APP_BG)
        super().__init__(parent, bg=surface, highlightthickness=0, **kwargs)
        self._canvas = tk.Canvas(self, bg=surface, highlightthickness=0, bd=0)
        self._scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self._canvas.yview,
                                        bootstyle="secondary-round")
        self._canvas.configure(yscrollcommand=self._toggle_scrollbar)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.body = tk.Frame(self._canvas, bg=surface, highlightthickness=0)
        self._window = self._canvas.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", self._on_body_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel(self._canvas)
        self._bind_mousewheel(self.body)

    def _toggle_scrollbar(self, first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            self._scrollbar.pack_forget()
        else:
            self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
        self._scrollbar.set(first, last)

    def _on_body_configure(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfigure(self._window, width=event.width)

    def _bind_mousewheel(self, widget):
        widget.bind("<Enter>", lambda _event: widget.bind_all("<MouseWheel>", self._on_wheel))
        widget.bind("<Leave>", lambda _event: widget.unbind_all("<MouseWheel>"))

    def _on_wheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class NavButton(tk.Frame):
    """Sidebar navigation row with accessible selected and running states."""

    def __init__(self, parent, text, icon, command, on_remove=None, **kwargs):
        base_bg = kwargs.pop("bg", _widget_bg(parent, SIDEBAR_BG))
        super().__init__(parent, bg=base_bg, cursor="hand2", highlightthickness=0, **kwargs)
        self._command = command
        self._on_remove = on_remove
        self._selected = False
        self._collapsed = False
        self._status_running = False
        self._icon = icon
        self._text = text
        self._base_bg = base_bg
        self._hover_bg = mix(base_bg, PRIMARY, 0.15)
        self._selected_bg = PRIMARY_SOFT
        self._current_bg = base_bg

        self._row = tk.Frame(self, bg=base_bg, highlightthickness=0)
        self._row.pack(fill=tk.X, expand=True, padx=4, pady=2)
        self._icon_lbl = tk.Label(self._row, text=icon, bg=base_bg, fg="#DDE2FA",
                                  font=("Segoe UI Emoji", 13), width=3, pady=10)
        self._icon_lbl.pack(side=tk.LEFT)
        self._text_lbl = tk.Label(self._row, text=text, bg=base_bg, fg="#DDE2FA",
                                  font=("Segoe UI Variable", 11, "bold"), anchor="w")
        self._text_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 2))
        self._status_dot = tk.Label(self._row, text="", bg=base_bg, fg=SUCCESS,
                                    font=("Segoe UI Variable", 11, "bold"), width=1)
        self._status_dot.pack(side=tk.RIGHT, padx=(4, 2))
        self._remove_lbl = None
        if on_remove:
            self._remove_lbl = tk.Label(self._row, text="×", bg=base_bg, fg=TEXT_DIM,
                                        font=("Segoe UI Variable", 15, "bold"), width=2, cursor="hand2")
            self._remove_lbl.pack(side=tk.RIGHT)
            self._remove_lbl.bind("<Button-1>", self._remove)
            self._remove_lbl.bind("<Enter>", lambda _event: self._remove_lbl.configure(fg=DANGER))
            self._remove_lbl.bind("<Leave>", lambda _event: self._remove_lbl.configure(fg=TEXT_DIM))

        for widget in (self, self._row, self._icon_lbl, self._text_lbl, self._status_dot):
            widget.bind("<Button-1>", lambda _event: self._command())
            widget.bind("<Enter>", lambda _event: self._set_hover(True))
            widget.bind("<Leave>", lambda _event: self._set_hover(False))

    def _remove(self, _event=None):
        if self._on_remove:
            self._on_remove()

    def _children(self):
        widgets = [self, self._row, self._icon_lbl, self._text_lbl, self._status_dot]
        if self._remove_lbl:
            widgets.append(self._remove_lbl)
        return widgets

    def _paint(self, bg: str, fg: str = "#DDE2FA"):
        self._current_bg = bg
        for widget in self._children():
            try:
                widget.configure(bg=bg)
            except Exception:
                pass
        self._icon_lbl.configure(fg=fg)
        self._text_lbl.configure(fg=fg)
        self._status_dot.configure(fg=SUCCESS if self._status_running else "#667095")

    def _set_hover(self, hovered: bool):
        if not self._selected:
            self._paint(self._hover_bg if hovered else self._base_bg)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._paint(self._selected_bg if selected else self._base_bg,
                    "#FFFFFF" if selected else "#DDE2FA")

    def set_status(self, running: bool):
        self._status_running = bool(running)
        self._status_dot.configure(text="●" if self._status_running else "", fg=SUCCESS)

    def set_collapsed(self, collapsed: bool):
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        if collapsed:
            self._text_lbl.pack_forget()
            self._status_dot.pack_forget()
            if self._remove_lbl:
                self._remove_lbl.pack_forget()
            self._icon_lbl.configure(width=4)
        else:
            self._icon_lbl.configure(width=3)
            self._text_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 2))
            self._status_dot.pack(side=tk.RIGHT, padx=(4, 2))
            if self._remove_lbl:
                self._remove_lbl.pack(side=tk.RIGHT)


class GlassCard(tk.Frame):
    """Raised card with smooth rounded borders and a gentle hover lift."""

    def __init__(self, parent, accent: Optional[str] = None, radius: int = 24,
                 padding: int | tuple = 18, bg: Optional[str] = None, **kwargs):
        outer_bg = bg or _widget_bg(parent, APP_BG)
        super().__init__(parent, bg=outer_bg, highlightthickness=0, **kwargs)
        self._outer_bg = outer_bg
        self._accent = accent or PRIMARY
        self._radius = radius
        self._hover = 0.0
        self._job = None
        self._canvas = tk.Canvas(self, bg=outer_bg, highlightthickness=0, bd=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        self._card_fill = mix(SURFACE, "#FFFFFF", 0.025)
        self._container = ttk.Frame(self._canvas)
        self._window = self._canvas.create_window((8, 8), window=self._container, anchor="nw")

        # Apply padding
        px, py = (padding[0], padding[1]) if isinstance(padding, tuple) else (padding, padding)
        self.body = ttk.Frame(self._container)
        self.body.pack(fill=tk.BOTH, expand=True, padx=px, pady=py)

        self._canvas.bind("<Configure>", self._on_configure)
        self._container.bind("<Configure>", self._sync_size)
        for widget in (self._canvas, self._container, self.body):
            widget.bind("<Enter>", lambda _event: self._animate(1.0))
            widget.bind("<Leave>", lambda _event: self._animate(0.0))
        self.after_idle(self._sync_size)

    def _sync_size(self, _event=None):
        try:
            self._canvas.configure(width=self._container.winfo_reqwidth() + 16,
                                   height=self._container.winfo_reqheight() + 16)
        except Exception:
            pass

    def _on_configure(self, event):
        width, height = max(8, event.width), max(8, event.height)
        self._canvas.itemconfigure(self._window, width=max(1, width - 16))
        self._draw(width, height)

    def _draw(self, width=None, height=None):
        width = width or self._canvas.winfo_width()
        height = height or self._canvas.winfo_height()
        if width < 8 or height < 8:
            return
        self._canvas.delete("surface")
        fill = mix(SURFACE, "#FFFFFF", 0.025 + self._hover * 0.025)
        outline = mix(BORDER_SOFT, self._accent, 0.36 + self._hover * 0.30)
        self._round_rect(1, 1, width - 1, height - 1, self._radius,
                         fill=fill, outline=outline, width=1.1 + self._hover, tags="surface")
        self._canvas.tag_lower("surface")

    def _round_rect(self, x1, y1, x2, y2, radius, **kwargs):
        radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return self._canvas.create_polygon(points, smooth=True, **kwargs)

    def _animate(self, target: float, steps: int = 8):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        start = self._hover

        def _step(index=0):
            if not self.winfo_exists():
                return
            self._hover = start + (target - start) * (index / steps)
            self._draw()
            if index < steps:
                self._job = self.after(16, lambda: _step(index + 1))
            else:
                self._job = None

        _step()


class StatTile(tk.Frame):
    """Compact metric card designed for quick scanning in the workspace."""

    def __init__(self, parent, icon, label, value="—", bootstyle="secondary", **kwargs):
        palette = palette_for(bootstyle)
        super().__init__(parent, bg=SURFACE, highlightthickness=1,
                         highlightbackground=mix(BORDER_SOFT, palette.accent, 0.30), **kwargs)
        self._palette = palette
        self._value = str(value)
        self._icon = tk.Label(self, text=icon, bg=palette.accent_soft, fg=palette.icon,
                              font=("Segoe UI Emoji", 12), width=3, pady=4)
        self._icon.grid(row=0, column=0, rowspan=2, padx=(12, 9), pady=12, sticky="n")
        self._value_lbl = tk.Label(self, text=self._value, bg=SURFACE, fg=TEXT,
                                   font=FONT_STAT_VALUE, anchor="w")
        self._value_lbl.grid(row=0, column=1, padx=(0, 12), pady=(11, 0), sticky="sw")
        self._label_lbl = tk.Label(self, text=label.upper(), bg=SURFACE, fg=TEXT_MUTED,
                                   font=FONT_STAT_LABEL, anchor="w")
        self._label_lbl.grid(row=1, column=1, padx=(0, 12), pady=(0, 11), sticky="nw")
        self.columnconfigure(1, weight=1)

    def set_value(self, value):
        self._value = str(value)
        self._value_lbl.configure(text=self._value)

    def get_value(self):
        return self._value


def _widget_bg(widget: tk.Misc, fallback: str = APP_BG) -> str:
    try:
        value = widget.cget("bg")
        if value:
            return value
    except Exception:
        pass
    return fallback
