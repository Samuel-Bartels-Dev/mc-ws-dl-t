import json
import logging
import os
import queue
import threading
import time
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk
from typing import Any, cast

import customtkinter as ctk  # type: ignore[import-untyped]

from .config import ScraperConfig
from .core import (
    DownloadOptions,
    SeriesChapter,
    SeriesInfo,
    build_series_root_path,
    discover_series,
    download_images_from_payload,
    download_selected_chapters_as_cbz,
    run_download,
)
from .history import load_history
from .parsers import get_available_parser_names


class QueueLogHandler(logging.Handler):
    # Logging handler that forwards formatted messages to the UI event queue.
    def __init__(self, event_queue: "queue.Queue[tuple[str, object]]") -> None:
        super().__init__()
        self._event_queue = event_queue
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._event_queue.put(("log", self.format(record)))
        except Exception:
            # Keep logging failures from breaking the main UI flow.
            pass


class DownloaderUI:
    NERD_ICONS = {
        "app": "\uf02d",
        "download": "\uf019",
        "queue": "\uf0ae",
        "pause": "\uf04c",
        "resume": "\uf04b",
        "cancel": "\uf00d",
        "retry": "\uf01e",
        "folder": "\uf07c",
        "logs": "\uf15c",
        "clear": "\uf1f8",
        "debug": "\uf188",
        "source": "\uf0c1",
        "settings": "\uf013",
        "workspace": "\uf0e8",
        "chapters": "\uf02d",
        "terminal": "\uf120",
        "json": "\ue60b",
        "images": "\uf03e",
        "filter": "\uf0b0",
        "select": "\uf046",
        "run": "\uf0e7",
        "copy": "\uf0c5",
        "save": "\uf0c7",
        "browse": "\uf07b",
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("MC-WS-DL-T | Manga/Comic Downloader")
        self.root.geometry("1240x780")
        self.root.minsize(1040, 700)

        self.event_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.current_payload: dict[str, object] | None = None
        self.is_running = False
        self.current_series: SeriesInfo | None = None
        self.current_series_chapters: list[SeriesChapter] = []
        self.current_series_history: dict[str, object] = {}
        self.current_failed_chapter_urls: list[str] = []
        self._log_popup: tk.Toplevel | None = None
        self._popup_log_text: tk.Text | None = None
        self._menus: list[tk.Menu] = []
        self._current_palette: dict[str, str] = {}
        self.library_locations: list[str] = []

        # Queue state for large chapter batches.
        self.queue_active = False
        self.queue_paused = False
        self._queue_pause_event = threading.Event()
        self._queue_pause_event.set()
        self._queue_cancel_event = threading.Event()

        # UI state values.
        self.url_var = tk.StringVar()
        self.parser_var = tk.StringVar(value="auto")
        self.browser_var = tk.StringVar(value="chrome")
        self.prefer_dynamic_var = tk.BooleanVar(value=False)
        self.timeout_var = tk.StringVar(value="15")
        self.wait_var = tk.StringVar(value="5")
        self.retries_var = tk.StringVar(value="3")
        self.output_var = tk.StringVar()
        self.image_dir_var = tk.StringVar()
        self.auto_download_var = tk.BooleanVar(value=True)
        self.log_file_var = tk.StringVar()
        self.log_level_var = tk.StringVar(value="INFO")
        self.show_debug_var = tk.BooleanVar(value=False)
        self.theme_var = tk.StringVar(value="light")
        self.status_var = tk.StringVar(value="Ready.")
        self.summary_var = tk.StringVar(value="No results yet.")
        self.series_status_var = tk.StringVar(value="No series loaded.")
        self.chapter_filter_var = tk.StringVar(value="All chapters")
        self.retry_per_chapter_var = tk.StringVar(value="1")
        self._json_tab_visible = True
        self._url_tab_visible = True

        self.ui_font_family = self._choose_font_family(
            (
                "JetBrainsMono NFP",
                "JetBrainsMono NF",
                "JetBrainsMonoNL NFP",
                "MesloLGS Nerd Font Propo",
                "MesloLGS Nerd Font",
            ),
            "Segoe UI",
        )
        self.mono_font_family = self._choose_font_family(
            (
                "JetBrainsMono NFM",
                "JetBrainsMonoNL NFM",
                "JetBrainsMono NF",
                "MesloLGS Nerd Font Mono",
                "Cascadia Mono",
            ),
            "Consolas",
        )

        self.log_file_var.set(str(self._build_default_log_file_path()))
        self._load_library_settings()
        self._ensure_default_library()

        self._configure_style()
        self._build_modern_layout()
        self._apply_theme(self.theme_var.get())
        self._update_queue_control_states()

        # Poll queued events so worker thread updates are applied on the UI thread.
        self.root.after(100, self._process_events)

    def _choose_font_family(self, preferred: tuple[str, ...], fallback: str) -> str:
        try:
            available = {str(family) for family in tkfont.families(self.root)}
        except tk.TclError:
            return fallback

        for family in preferred:
            if family in available:
                return family
        return fallback

    def _build_default_log_file_path(self) -> Path:
        # Always create run logs in ./logs so users do not have to configure file paths.
        logs_dir = Path.cwd() / "logs"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return logs_dir / f"mc_ws_dl_t_{stamp}.log"

    def _default_library_path(self) -> Path:
        # Keep the default library anchored in the Pictures folder.
        return Path.home() / "Pictures" / "MC-WS-DL-Library"

    def _legacy_default_library_path(self) -> Path:
        # Previous builds used the home root; keep this so we can migrate cleanly.
        return Path.home() / "MC-WS-DL-Library"

    def _settings_path(self) -> Path:
        return Path.home() / ".mc_ws_dl_t" / "ui_settings.json"

    def _normalize_library_path(self, raw_path: str) -> str:
        return str(Path(raw_path).expanduser())

    def _load_library_settings(self) -> None:
        settings_path = self._settings_path()
        loaded_locations: list[str] = []
        default_library = ""
        try:
            if settings_path.exists():
                loaded = json.loads(settings_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    raw_locations = loaded.get("library_locations")
                    if isinstance(raw_locations, list):
                        loaded_locations = [
                            self._normalize_library_path(str(item))
                            for item in raw_locations
                            if str(item).strip()
                        ]
                    raw_default = loaded.get("default_library", "")
                    if isinstance(raw_default, str) and raw_default.strip():
                        default_library = self._normalize_library_path(raw_default)
        except Exception:
            loaded_locations = []
            default_library = ""

        deduped_locations: list[str] = []
        seen: set[str] = set()
        for location in loaded_locations:
            if location in seen:
                continue
            seen.add(location)
            deduped_locations.append(location)

        if default_library and default_library not in seen:
            deduped_locations.insert(0, default_library)
        self.library_locations = deduped_locations
        self.image_dir_var.set(default_library)

    def _save_library_settings(self) -> None:
        settings_path = self._settings_path()
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        deduped_locations: list[str] = []
        seen: set[str] = set()
        for location in self.library_locations:
            normalized = self._normalize_library_path(location)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped_locations.append(normalized)

        current_library = self.image_dir_var.get().strip()
        default_library = ""
        if current_library:
            default_library = self._normalize_library_path(current_library)
            self.image_dir_var.set(default_library)
            if default_library not in seen:
                deduped_locations.insert(0, default_library)
                seen.add(default_library)

        self.library_locations = deduped_locations

        payload = {
            "library_locations": self.library_locations,
            "default_library": default_library,
        }
        settings_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _ensure_default_library(self) -> None:
        # First run gets a practical default library path with no manual setup.
        preferred_default = self._normalize_library_path(str(self._default_library_path()))
        legacy_default = self._normalize_library_path(str(self._legacy_default_library_path()))

        default_library = self.image_dir_var.get().strip()
        normalized_default = self._normalize_library_path(default_library) if default_library else ""

        # Migrate old home-root default to Pictures and keep empty state deterministic.
        if not normalized_default or normalized_default == legacy_default:
            normalized_default = preferred_default
            self.image_dir_var.set(normalized_default)

        if normalized_default in self.library_locations:
            self.library_locations.remove(normalized_default)
        self.library_locations.insert(0, normalized_default)

        Path(normalized_default).mkdir(parents=True, exist_ok=True)
        self._save_library_settings()

    def _refresh_library_combo(self) -> None:
        if hasattr(self, "image_dir_combo"):
            self.image_dir_combo.configure(values=self.library_locations)

    def _persist_current_library(self) -> None:
        current_library = self.image_dir_var.get().strip()
        if not current_library:
            return

        normalized = self._normalize_library_path(current_library)
        self.image_dir_var.set(normalized)
        if normalized in self.library_locations:
            self.library_locations.remove(normalized)
        self.library_locations.insert(0, normalized)
        Path(normalized).mkdir(parents=True, exist_ok=True)
        self._refresh_library_combo()
        self._save_library_settings()

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self.root, tearoff=False)

        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Load Series Chapters", command=self._start_series_discovery)
        file_menu.add_separator()
        file_menu.add_command(label="Set Library Folder...", command=self._choose_library_folder)
        file_menu.add_command(label="Open Library Folder", command=self._open_current_library_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Open Log Folder", command=self._open_log_folder)
        file_menu.add_command(label="Pop Out Logs", command=self._open_log_popup)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menu_bar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu_bar, tearoff=False)
        edit_menu.add_command(label="Clear Logs", command=self._clear_logs)
        edit_menu.add_command(label="Copy Debug JSON", command=self._copy_json)
        menu_bar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menu_bar, tearoff=False)
        view_menu.add_checkbutton(
            label="Show Debug Tools",
            variable=self.show_debug_var,
            command=self._toggle_debug_tools,
        )
        view_menu.add_separator()
        view_menu.add_radiobutton(
            label="Light Mode",
            variable=self.theme_var,
            value="light",
            command=self._on_theme_change,
        )
        view_menu.add_radiobutton(
            label="Dark Mode",
            variable=self.theme_var,
            value="dark",
            command=self._on_theme_change,
        )
        view_menu.add_separator()
        view_menu.add_command(label="Pop Out Logs", command=self._open_log_popup)
        menu_bar.add_cascade(label="View", menu=view_menu)

        tools_menu = tk.Menu(menu_bar, tearoff=False)
        tools_menu.add_command(label="Run Single URL Parse (Legacy)", command=self._start_download)
        tools_menu.add_command(label="Download Images From Payload (Legacy)", command=self._start_image_download_from_payload)
        tools_menu.add_separator()
        tools_menu.add_command(label="Start Queue (Selected Chapters)", command=self._start_download_selected_chapters)
        tools_menu.add_command(label="Retry Failed Chapters", command=self._retry_failed_chapters)
        menu_bar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menu_bar, tearoff=False)
        help_menu.add_command(label="Quick Workflow", command=self._show_quick_workflow)
        help_menu.add_command(label="About", command=self._show_about)
        menu_bar.add_cascade(label="Help", menu=help_menu)

        self._menus = [menu_bar, file_menu, edit_menu, view_menu, tools_menu, help_menu]
        self.root.config(menu=menu_bar)

    def _configure_style(self) -> None:
        ui_font = self.ui_font_family
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        ctk.ThemeManager.theme["CTkFont"]["family"] = ui_font
        self.root.option_add("*Font", f"{{{ui_font}}} 10")
        self.style.configure("AppTitle.TLabel", font=(ui_font, 22, "bold"))
        self.style.configure("Title.TLabel", font=(ui_font, 13, "bold"))
        self.style.configure("Section.TLabel", font=(ui_font, 10, "bold"))
        self.style.configure("Meta.TLabel", font=(ui_font, 9))
        self.style.configure("Primary.TButton", padding=(14, 7))
        self.style.configure("Secondary.TButton", padding=(10, 6))
        self.style.configure("Slim.TButton", padding=(8, 4))

    def _on_theme_change(self) -> None:
        self._apply_theme(self.theme_var.get())

    def _apply_theme(self, mode: str) -> None:
        ctk.set_appearance_mode("dark" if mode == "dark" else "light")
        palettes: dict[str, dict[str, str]] = {
            "light": {
                "bg": "#f5f7fb",
                "panel": "#e8edf3",
                "surface": "#ffffff",
                "surface_alt": "#f8fafc",
                "input": "#ffffff",
                "fg": "#1b2430",
                "muted": "#667085",
                "border": "#d5dde7",
                "accent": "#2563eb",
                "accent_hover": "#1d4ed8",
                "accent_fg": "#ffffff",
                "success": "#15803d",
                "warning": "#b45309",
                "danger": "#b91c1c",
                "text_bg": "#ffffff",
                "text_fg": "#111827",
                "tree_bg": "#ffffff",
                "tree_fg": "#1f2937",
                "tree_alt": "#f7fafc",
                "tree_sel_bg": "#0f766e",
                "tree_sel_fg": "#ffffff",
                "tree_heading_bg": "#eef3f7",
                "tree_heading_fg": "#1f2937",
                "log_bg": "#101820",
                "log_fg": "#dbe7f1",
            },
            "dark": {
                "bg": "#101114",
                "panel": "#14161a",
                "surface": "#1a1c20",
                "surface_alt": "#23262d",
                "input": "#20232a",
                "fg": "#f4f6f8",
                "muted": "#a3aab6",
                "border": "#333842",
                "accent": "#60a5fa",
                "accent_hover": "#7bbcff",
                "accent_fg": "#07111e",
                "success": "#86efac",
                "warning": "#fbbf24",
                "danger": "#fca5a5",
                "text_bg": "#181a1f",
                "text_fg": "#f2f4f7",
                "tree_bg": "#181a1f",
                "tree_fg": "#edf1f5",
                "tree_alt": "#20232a",
                "tree_sel_bg": "#2563eb",
                "tree_sel_fg": "#ffffff",
                "tree_heading_bg": "#23262d",
                "tree_heading_fg": "#e5e9ef",
                "log_bg": "#101114",
                "log_fg": "#dce3ec",
            },
        }
        palette = palettes["dark" if mode == "dark" else "light"]
        self._current_palette = palette
        flat_bg = palette["bg"]
        surface = palette["surface"]
        panel = palette["panel"]

        # Base widgets.
        self.root.configure(bg=flat_bg)
        self.style.configure("TFrame", background=flat_bg)
        self.style.configure("App.TFrame", background=flat_bg)
        self.style.configure("Card.TFrame", background=surface, borderwidth=1, relief="solid")
        self.style.configure("Surface.TFrame", background=surface)
        self.style.configure("Toolbar.TFrame", background=palette["surface_alt"])
        self.style.configure("Status.TFrame", background=panel)
        self.style.configure("TLabel", background=flat_bg, foreground=palette["fg"])
        self.style.configure("AppTitle.TLabel", background=flat_bg, foreground=palette["fg"])
        self.style.configure("Title.TLabel", background=surface, foreground=palette["fg"])
        self.style.configure("Section.TLabel", background=surface, foreground=palette["fg"])
        self.style.configure("Hint.TLabel", background=flat_bg, foreground=palette["muted"])
        self.style.configure("Surface.TLabel", background=surface, foreground=palette["fg"])
        self.style.configure("SurfaceHint.TLabel", background=surface, foreground=palette["muted"])
        self.style.configure("Toolbar.TLabel", background=palette["surface_alt"], foreground=palette["fg"])
        self.style.configure("ToolbarHint.TLabel", background=palette["surface_alt"], foreground=palette["muted"])
        self.style.configure("Status.TLabel", background=panel, foreground=palette["muted"])
        self.style.configure(
            "Panel.TLabelframe",
            background=surface,
            bordercolor=palette["border"],
            borderwidth=1,
            relief="flat",
            lightcolor=surface,
            darkcolor=surface,
        )
        self.style.configure(
            "TLabelframe",
            background=surface,
            bordercolor=palette["border"],
            borderwidth=1,
            relief="flat",
            lightcolor=surface,
            darkcolor=surface,
        )
        self.style.configure(
            "Panel.TLabelframe.Label",
            background=surface,
            foreground=palette["fg"],
            font=(self.ui_font_family, 10, "bold"),
        )
        self.style.configure(
            "TLabelframe.Label",
            background=surface,
            foreground=palette["fg"],
            font=(self.ui_font_family, 10, "bold"),
        )

        # Inputs and buttons.
        self.style.configure(
            "TEntry",
            fieldbackground=palette["input"],
            foreground=palette["text_fg"],
            bordercolor=palette["border"],
            lightcolor=palette["border"],
            darkcolor=palette["border"],
            insertcolor=palette["text_fg"],
            padding=(7, 5),
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=palette["input"],
            foreground=palette["text_fg"],
            background=palette["input"],
            bordercolor=palette["border"],
            lightcolor=palette["border"],
            darkcolor=palette["border"],
            arrowcolor=palette["fg"],
            padding=(7, 4),
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette["input"])],
            foreground=[("readonly", palette["text_fg"])],
        )
        self.style.configure(
            "TSpinbox",
            fieldbackground=palette["input"],
            foreground=palette["text_fg"],
            background=palette["input"],
            bordercolor=palette["border"],
            lightcolor=palette["border"],
            darkcolor=palette["border"],
            arrowcolor=palette["fg"],
            padding=(5, 4),
        )
        self.style.configure(
            "TButton",
            background=surface,
            foreground=palette["fg"],
            bordercolor=palette["border"],
            lightcolor=palette["border"],
            darkcolor=palette["border"],
            focusthickness=1,
            focuscolor=palette["accent"],
            padding=(10, 6),
        )
        self.style.map(
            "TButton",
            background=[("active", palette["surface_alt"]), ("pressed", panel)],
            foreground=[("disabled", palette["muted"])],
        )
        self.style.configure(
            "Primary.TButton",
            background=palette["accent"],
            foreground=palette["accent_fg"],
            bordercolor=palette["accent"],
            lightcolor=palette["accent"],
            darkcolor=palette["accent"],
            padding=(14, 7),
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", palette["accent_hover"]), ("disabled", palette["border"])],
            foreground=[("disabled", palette["muted"])],
        )
        self.style.configure(
            "Secondary.TButton",
            background=palette["surface_alt"],
            foreground=palette["fg"],
            bordercolor=palette["border"],
            padding=(10, 6),
        )
        self.style.map("Secondary.TButton", background=[("active", panel), ("pressed", panel)])
        self.style.configure("Slim.TButton", padding=(8, 4))
        self.style.configure("TCheckbutton", background=surface, foreground=palette["fg"])
        self.style.map(
            "TCheckbutton",
            background=[("active", surface)],
            foreground=[("disabled", palette["muted"])],
        )

        # Notebook and tables.
        self.style.configure("TNotebook", background=surface, borderwidth=0, tabmargins=(0, 0, 0, 0))
        self.style.configure(
            "TNotebook.Tab",
            background=palette["surface_alt"],
            foreground=palette["fg"],
            bordercolor=surface,
            lightcolor=surface,
            darkcolor=surface,
            padding=(14, 8),
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", surface), ("active", panel)],
            foreground=[("selected", palette["accent"]), ("disabled", palette["muted"])],
        )
        self.style.configure(
            "Treeview",
            background=palette["tree_bg"],
            foreground=palette["tree_fg"],
            fieldbackground=palette["tree_bg"],
            bordercolor=palette["border"],
            borderwidth=0,
            relief="flat",
            rowheight=28,
            font=(self.ui_font_family, 10),
        )
        self.style.map(
            "Treeview",
            background=[("selected", palette["tree_sel_bg"])],
            foreground=[("selected", palette["tree_sel_fg"])],
        )
        self.style.configure(
            "Treeview.Heading",
            background=palette["tree_heading_bg"],
            foreground=palette["tree_heading_fg"],
            bordercolor=palette["border"],
            relief="flat",
            font=(self.ui_font_family, 9, "bold"),
            padding=(8, 6),
        )
        self.style.map("Treeview.Heading", background=[("active", panel)])

        # Modern slim scrollbars (no arrows), closer to web app visuals.
        vertical_scroll_layout: list[tuple[str, Any]] = [
            (
                "Vertical.Scrollbar.trough",
                {
                    "sticky": "ns",
                    "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})],
                },
            )
        ]
        horizontal_scroll_layout: list[tuple[str, Any]] = [
            (
                "Horizontal.Scrollbar.trough",
                {
                    "sticky": "we",
                    "children": [("Horizontal.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})],
                },
            )
        ]
        self.style.layout("Modern.Vertical.TScrollbar", cast(Any, vertical_scroll_layout))
        self.style.layout("Modern.Horizontal.TScrollbar", cast(Any, horizontal_scroll_layout))
        self.style.configure(
            "Modern.Vertical.TScrollbar",
            background=palette["border"],
            troughcolor=surface,
            bordercolor=surface,
            darkcolor=surface,
            lightcolor=surface,
            arrowcolor=surface,
            arrowsize=0,
            gripcount=0,
            relief="flat",
            width=8,
        )
        self.style.configure(
            "Modern.Horizontal.TScrollbar",
            background=palette["border"],
            troughcolor=surface,
            bordercolor=surface,
            darkcolor=surface,
            lightcolor=surface,
            arrowcolor=surface,
            arrowsize=0,
            gripcount=0,
            relief="flat",
            width=8,
        )
        self.style.map(
            "Modern.Vertical.TScrollbar",
            background=[("active", palette["accent"]), ("pressed", palette["accent"])],
        )
        self.style.map(
            "Modern.Horizontal.TScrollbar",
            background=[("active", palette["accent"]), ("pressed", palette["accent"])],
        )

        text_widgets = (
            (getattr(self, "json_text", None), palette["text_bg"], palette["text_fg"]),
            (getattr(self, "log_text", None), palette["log_bg"], palette["log_fg"]),
            (self._popup_log_text, palette["log_bg"], palette["log_fg"]),
        )
        for text_widget, bg, fg in text_widgets:
            if text_widget is not None and text_widget.winfo_exists():
                text_widget.configure(
                    background=bg,
                    foreground=fg,
                    insertbackground=fg,
                    selectbackground=palette["accent"],
                    selectforeground=palette["accent_fg"],
                    borderwidth=0,
                    highlightthickness=0,
                    highlightbackground=bg,
                )
        if hasattr(self, "chapter_table"):
            self.chapter_table.tag_configure("downloaded", foreground=palette["success"])
            self.chapter_table.tag_configure("pending", foreground=palette["tree_fg"])
        if hasattr(self, "url_table"):
            self.url_table.tag_configure("odd", background=palette["tree_alt"])

        # Combobox dropdown list colors.
        self.root.option_add("*TCombobox*Listbox.background", palette["input"])
        self.root.option_add("*TCombobox*Listbox.foreground", palette["text_fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", palette["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", palette["accent_fg"])

        # Tk menu colors for better dark/light parity.
        if hasattr(self, "_menus"):
            for menu in self._menus:
                menu.configure(
                    background=flat_bg,
                    foreground=palette["fg"],
                    activebackground=palette["accent"],
                    activeforeground=palette["accent_fg"],
                    borderwidth=0,
                )
        if self._log_popup and self._log_popup.winfo_exists():
            self._log_popup.configure(bg=palette["bg"])

    def _build_modern_layout(self) -> None:
        icons = self.NERD_ICONS
        ui_font = self.ui_font_family
        mono_font = self.mono_font_family
        action_font = (ui_font, 13, "bold")
        compact_button_font = (ui_font, 12, "bold")
        shell_bg = ("#f5f7fb", "#101114")
        panel_bg = ("#ffffff", "#1a1c20")
        panel_alt = ("#f8fafc", "#23262d")
        sidebar_bg = ("#111827", "#111216")
        sidebar_muted = ("#9ca3af", "#a3aab6")
        border = ("#d7dee8", "#333842")
        accent = ("#2563eb", "#60a5fa")
        accent_hover = ("#1d4ed8", "#7bbcff")
        accent_text = ("#ffffff", "#07111e")
        text = ("#111827", "#f4f6f8")
        muted = ("#667085", "#a3aab6")

        cast(Any, self.root).configure(fg_color=shell_bg)

        app = ctk.CTkFrame(self.root, fg_color=shell_bg, corner_radius=0)
        app.pack(fill=tk.BOTH, expand=True)
        app.grid_columnconfigure(1, weight=1)
        app.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(app, width=260, corner_radius=0, fg_color=sidebar_bg)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sidebar,
            text=f"{icons['app']}  MC-WS-DL-T",
            font=(ui_font, 25, "bold"),
            text_color="#f8fafc",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=22, pady=(24, 2))
        ctk.CTkLabel(
            sidebar,
            text=f"{icons['terminal']}  Download console",
            font=(ui_font, 12),
            text_color=sidebar_muted,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 28))

        self.load_series_button = ctk.CTkButton(
            sidebar,
            text=f"{icons['download']}  Load Chapters",
            command=self._start_series_discovery,
            height=42,
            corner_radius=8,
            fg_color=accent,
            hover_color=accent_hover,
            text_color=accent_text,
            font=action_font,
        )
        self.load_series_button.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 10))

        self.download_selected_button = ctk.CTkButton(
            sidebar,
            text=f"{icons['queue']}  Start Queue",
            command=self._start_download_selected_chapters,
            height=42,
            corner_radius=8,
            fg_color=("#243042", "#20232a"),
            hover_color=("#334155", "#303641"),
            text_color="#f8fafc",
            font=action_font,
        )
        self.download_selected_button.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 16))

        queue_controls = ctk.CTkFrame(sidebar, fg_color="transparent")
        queue_controls.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 18))
        queue_controls.grid_columnconfigure((0, 1), weight=1)
        self.pause_queue_button = ctk.CTkButton(
            queue_controls,
            text=f"{icons['pause']}  Pause",
            command=self._pause_queue,
            state=tk.DISABLED,
            height=34,
            corner_radius=8,
            fg_color=("#2d3748", "#22262e"),
            hover_color=("#46556c", "#303641"),
            text_color="#e5edf6",
            font=compact_button_font,
        )
        self.pause_queue_button.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))
        self.resume_queue_button = ctk.CTkButton(
            queue_controls,
            text=f"{icons['resume']}  Resume",
            command=self._resume_queue,
            state=tk.DISABLED,
            height=34,
            corner_radius=8,
            fg_color=("#2d3748", "#22262e"),
            hover_color=("#46556c", "#303641"),
            text_color="#e5edf6",
            font=compact_button_font,
        )
        self.resume_queue_button.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 8))
        self.cancel_queue_button = ctk.CTkButton(
            queue_controls,
            text=f"{icons['cancel']}  Cancel",
            command=self._cancel_queue,
            state=tk.DISABLED,
            height=34,
            corner_radius=8,
            fg_color=("#7f1d1d", "#451a1a"),
            hover_color=("#991b1b", "#5f1f1f"),
            text_color="#fee2e2",
            font=compact_button_font,
        )
        self.cancel_queue_button.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.retry_failed_button = ctk.CTkButton(
            queue_controls,
            text=f"{icons['retry']}  Retry Failed",
            command=self._retry_failed_chapters,
            state=tk.DISABLED,
            height=34,
            corner_radius=8,
            fg_color=("#2d3748", "#22262e"),
            hover_color=("#46556c", "#303641"),
            text_color="#e5edf6",
            font=compact_button_font,
        )
        self.retry_failed_button.grid(row=1, column=1, sticky="ew", padx=(6, 0))

        sidebar_section = ctk.CTkFrame(sidebar, fg_color=("#172033", "#191b21"), corner_radius=8)
        sidebar_section.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 18))
        sidebar_section.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            sidebar_section,
            text=f"{icons['settings']}  Queue Settings",
            text_color="#f8fafc",
            font=action_font,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
        retry_row = ctk.CTkFrame(sidebar_section, fg_color="transparent")
        retry_row.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))
        retry_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(retry_row, text="Retry/chapter", text_color=sidebar_muted).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 10),
        )
        self.retry_spin = ctk.CTkEntry(
            retry_row,
            textvariable=self.retry_per_chapter_var,
            width=58,
            height=32,
            corner_radius=8,
            fg_color=("#0f172a", "#20232a"),
            border_color=("#334155", "#3a404b"),
            text_color="#f8fafc",
        )
        self.retry_spin.grid(row=0, column=1, sticky="e")

        sidebar_tools = ctk.CTkFrame(sidebar, fg_color="transparent")
        sidebar_tools.grid(row=6, column=0, sticky="ew", padx=18, pady=(0, 20))
        sidebar_tools.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            sidebar_tools,
            text=f"{icons['folder']}  Open Library",
            command=self._open_current_library_folder,
            height=36,
            corner_radius=8,
            fg_color=("#1f2937", "#1d2027"),
            hover_color=("#374151", "#303641"),
            text_color="#e5edf6",
            font=compact_button_font,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkButton(
            sidebar_tools,
            text=f"{icons['logs']}  Pop Out Logs",
            command=self._open_log_popup,
            height=36,
            corner_radius=8,
            fg_color=("#1f2937", "#1d2027"),
            hover_color=("#374151", "#303641"),
            text_color="#e5edf6",
            font=compact_button_font,
        ).grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkButton(
            sidebar_tools,
            text=f"{icons['clear']}  Clear Logs",
            command=self._clear_logs,
            height=36,
            corner_radius=8,
            fg_color=("#1f2937", "#1d2027"),
            hover_color=("#374151", "#303641"),
            text_color="#e5edf6",
            font=compact_button_font,
        ).grid(row=2, column=0, sticky="ew")

        sidebar.grid_rowconfigure(7, weight=1)
        bottom_tools = ctk.CTkFrame(sidebar, fg_color="transparent")
        bottom_tools.grid(row=8, column=0, sticky="ew", padx=18, pady=(0, 22))
        bottom_tools.grid_columnconfigure(0, weight=1)
        self.debug_switch = ctk.CTkSwitch(
            bottom_tools,
            text=f"{icons['debug']}  Debug tools",
            variable=self.show_debug_var,
            command=self._toggle_debug_tools,
            progress_color=accent,
            text_color="#e5edf6",
            font=(ui_font, 12, "bold"),
        )
        self.debug_switch.grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.theme_segment = ctk.CTkSegmentedButton(
            bottom_tools,
            values=["light", "dark"],
            variable=self.theme_var,
            command=lambda _value: self._on_theme_change(),
            height=34,
            corner_radius=8,
            selected_color=accent,
            selected_hover_color=accent_hover,
            unselected_color=("#1f2937", "#1d2027"),
            unselected_hover_color=("#374151", "#303641"),
            text_color=("#ffffff", "#ecfeff"),
            font=compact_button_font,
        )
        self.theme_segment.grid(row=1, column=0, sticky="ew")

        content = ctk.CTkFrame(app, fg_color=shell_bg, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew", padx=18, pady=16)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(content, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text=f"{icons['app']}  Manga and comic downloader",
            font=(ui_font, 25, "bold"),
            text_color=text,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            textvariable=self.status_var,
            font=(ui_font, 12),
            text_color=muted,
            anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=(18, 0))
        ctk.CTkLabel(
            header,
            textvariable=self.summary_var,
            font=(ui_font, 12),
            text_color=muted,
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        source_card = ctk.CTkFrame(
            content,
            fg_color=panel_bg,
            border_width=1,
            border_color=border,
            corner_radius=8,
        )
        source_card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        source_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            source_card,
            text=f"{icons['source']}  Source",
            font=(ui_font, 15, "bold"),
            text_color=text,
            anchor="w",
        ).grid(row=0, column=0, columnspan=4, sticky="ew", padx=18, pady=(16, 10))
        ctk.CTkLabel(source_card, text="Series URL", text_color=muted, anchor="w").grid(
            row=1,
            column=0,
            sticky="w",
            padx=(18, 10),
            pady=(0, 10),
        )
        ctk.CTkEntry(
            source_card,
            textvariable=self.url_var,
            height=38,
            corner_radius=8,
            fg_color=panel_alt,
            border_color=border,
            text_color=text,
            font=(ui_font, 12),
            placeholder_text="https://...",
        ).grid(row=1, column=1, columnspan=3, sticky="ew", padx=(0, 18), pady=(0, 10))

        ctk.CTkLabel(source_card, text="Library", text_color=muted, anchor="w").grid(
            row=2,
            column=0,
            sticky="w",
            padx=(18, 10),
            pady=(0, 16),
        )
        self.image_dir_combo = ctk.CTkComboBox(
            source_card,
            variable=self.image_dir_var,
            values=self.library_locations,
            height=38,
            corner_radius=8,
            fg_color=panel_alt,
            border_color=border,
            button_color=panel_alt,
            button_hover_color=("#e2e8f0", "#303641"),
            dropdown_fg_color=panel_bg,
            dropdown_hover_color=("#e2e8f0", "#343b46"),
            text_color=text,
            dropdown_text_color=text,
            font=(ui_font, 12),
            dropdown_font=(ui_font, 12),
            command=lambda _choice: self._persist_current_library(),
        )
        self.image_dir_combo.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=(0, 16))
        self.image_dir_combo.bind("<FocusOut>", lambda _event: self._persist_current_library())
        self.image_dir_combo.bind("<Return>", lambda _event: self._persist_current_library())
        ctk.CTkButton(
            source_card,
            text=f"{icons['browse']}  Browse",
            command=self._browse_image_dir,
            height=38,
            width=104,
            corner_radius=8,
            fg_color=panel_alt,
            hover_color=("#e2e8f0", "#303641"),
            text_color=text,
            font=compact_button_font,
        ).grid(row=2, column=2, sticky="ew", padx=(0, 10), pady=(0, 16))
        ctk.CTkButton(
            source_card,
            text=f"{icons['folder']}  Open",
            command=self._open_current_library_folder,
            height=38,
            width=86,
            corner_radius=8,
            fg_color=panel_alt,
            hover_color=("#e2e8f0", "#303641"),
            text_color=text,
            font=compact_button_font,
        ).grid(row=2, column=3, sticky="ew", padx=(0, 18), pady=(0, 16))

        options_card = ctk.CTkFrame(
            content,
            fg_color=panel_bg,
            border_width=1,
            border_color=border,
            corner_radius=8,
        )
        options_card.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        for column in (1, 3, 5, 7, 9):
            options_card.grid_columnconfigure(column, weight=1)

        ctk.CTkLabel(options_card, text="Parser", text_color=muted).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(18, 8),
            pady=(14, 14),
        )
        self.parser_combo = ctk.CTkComboBox(
            options_card,
            variable=self.parser_var,
            values=get_available_parser_names(),
            state="readonly",
            height=34,
            corner_radius=8,
            fg_color=panel_alt,
            border_color=border,
            button_color=panel_alt,
            button_hover_color=("#e2e8f0", "#303641"),
            dropdown_fg_color=panel_bg,
            dropdown_hover_color=("#e2e8f0", "#343b46"),
            text_color=text,
            dropdown_text_color=text,
            font=(ui_font, 12),
            dropdown_font=(ui_font, 12),
        )
        self.parser_combo.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(14, 14))

        ctk.CTkLabel(options_card, text="Browser", text_color=muted).grid(row=0, column=2, sticky="w", padx=(0, 8))
        self.browser_combo = ctk.CTkComboBox(
            options_card,
            variable=self.browser_var,
            values=("chrome", "firefox"),
            state="readonly",
            height=34,
            corner_radius=8,
            fg_color=panel_alt,
            border_color=border,
            button_color=panel_alt,
            button_hover_color=("#e2e8f0", "#303641"),
            dropdown_fg_color=panel_bg,
            dropdown_hover_color=("#e2e8f0", "#343b46"),
            text_color=text,
            dropdown_text_color=text,
            font=(ui_font, 12),
            dropdown_font=(ui_font, 12),
        )
        self.browser_combo.grid(row=0, column=3, sticky="ew", padx=(0, 12), pady=(14, 14))

        numeric_specs = (
            ("Wait", self.wait_var),
            ("Timeout", self.timeout_var),
            ("Retries", self.retries_var),
        )
        for offset, (label, variable) in enumerate(numeric_specs):
            label_column = 4 + offset * 2
            entry_column = label_column + 1
            ctk.CTkLabel(options_card, text=label, text_color=muted).grid(
                row=0,
                column=label_column,
                sticky="w",
                padx=(0, 8),
            )
            ctk.CTkEntry(
                options_card,
                textvariable=variable,
                width=58,
                height=34,
                corner_radius=8,
                fg_color=panel_alt,
                border_color=border,
                text_color=text,
                font=(ui_font, 12),
            ).grid(row=0, column=entry_column, sticky="w", padx=(0, 12), pady=(14, 14))

        ctk.CTkSwitch(
            options_card,
            text="Dynamic first",
            variable=self.prefer_dynamic_var,
            progress_color=accent,
            text_color=text,
            font=(ui_font, 12),
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=(18, 12), pady=(0, 16))
        ctk.CTkSwitch(
            options_card,
            text="Auto-download",
            variable=self.auto_download_var,
            progress_color=accent,
            text_color=text,
            font=(ui_font, 12),
        ).grid(row=1, column=2, columnspan=2, sticky="w", padx=(0, 12), pady=(0, 16))
        ctk.CTkLabel(options_card, text="Log level", text_color=muted).grid(
            row=1,
            column=4,
            sticky="w",
            padx=(0, 8),
            pady=(0, 16),
        )
        self.level_combo = ctk.CTkComboBox(
            options_card,
            variable=self.log_level_var,
            values=("DEBUG", "INFO", "WARNING", "ERROR"),
            state="readonly",
            height=34,
            width=112,
            corner_radius=8,
            fg_color=panel_alt,
            border_color=border,
            button_color=panel_alt,
            button_hover_color=("#e2e8f0", "#303641"),
            dropdown_fg_color=panel_bg,
            dropdown_hover_color=("#e2e8f0", "#343b46"),
            text_color=text,
            dropdown_text_color=text,
            font=(ui_font, 12),
            dropdown_font=(ui_font, 12),
        )
        self.level_combo.grid(row=1, column=5, sticky="w", padx=(0, 12), pady=(0, 16))
        self.logs_path_hint = ctk.CTkLabel(
            options_card,
            text="Logs auto-save in ./logs.",
            text_color=muted,
            anchor="w",
        )
        self.logs_path_hint.grid(row=1, column=6, columnspan=4, sticky="ew", padx=(0, 18), pady=(0, 16))

        self.output_label = ctk.CTkLabel(options_card, text="Output JSON", text_color=muted)
        self.output_label.grid(row=2, column=0, sticky="w", padx=(18, 8), pady=(0, 16))
        self.output_entry = ctk.CTkEntry(
            options_card,
            textvariable=self.output_var,
            height=34,
            corner_radius=8,
            fg_color=panel_alt,
            border_color=border,
            text_color=text,
            font=(ui_font, 12),
        )
        self.output_entry.grid(row=2, column=1, columnspan=6, sticky="ew", padx=(0, 12), pady=(0, 16))
        self.output_browse_button = ctk.CTkButton(
            options_card,
            text=f"{icons['browse']}  Browse",
            command=self._browse_output_file,
            height=34,
            width=96,
            corner_radius=8,
            fg_color=panel_alt,
            hover_color=("#e2e8f0", "#303641"),
            text_color=text,
            font=compact_button_font,
        )
        self.output_browse_button.grid(row=2, column=7, sticky="ew", padx=(0, 12), pady=(0, 16))

        self.debug_actions_frame = ctk.CTkFrame(options_card, fg_color="transparent")
        self.debug_actions_frame.grid(row=2, column=8, columnspan=2, sticky="e", padx=(0, 18), pady=(0, 16))
        self.copy_json_button = ctk.CTkButton(
            self.debug_actions_frame,
            text=f"{icons['copy']}  Copy JSON",
            command=self._copy_json,
            width=96,
            height=34,
            corner_radius=8,
            fg_color=panel_alt,
            hover_color=("#e2e8f0", "#303641"),
            text_color=text,
            font=compact_button_font,
        )
        self.copy_json_button.pack(side=tk.LEFT, padx=(0, 8))
        self.save_json_button = ctk.CTkButton(
            self.debug_actions_frame,
            text=f"{icons['save']}  Save As",
            command=self._save_json_as,
            width=86,
            height=34,
            corner_radius=8,
            fg_color=panel_alt,
            hover_color=("#e2e8f0", "#303641"),
            text_color=text,
            font=compact_button_font,
        )
        self.save_json_button.pack(side=tk.LEFT)

        workspace = ctk.CTkFrame(
            content,
            fg_color=panel_bg,
            border_width=1,
            border_color=border,
            corner_radius=8,
        )
        workspace.grid(row=2, column=0, sticky="nsew")
        workspace.grid_columnconfigure(0, weight=1)
        workspace.grid_rowconfigure(2, weight=1)

        workspace_header = ctk.CTkFrame(workspace, fg_color="transparent")
        workspace_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        workspace_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            workspace_header,
            text=f"{icons['workspace']}  Workspace",
            font=(ui_font, 16, "bold"),
            text_color=text,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            workspace_header,
            textvariable=self.series_status_var,
            text_color=muted,
            anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=(16, 0))

        self.workspace_tab_var = tk.StringVar(value="Chapters")
        self.workspace_tab_colors = {
            "selected_fg": accent,
            "selected_hover": accent_hover,
            "selected_text": accent_text,
            "idle_fg": panel_alt,
            "idle_hover": ("#e2e8f0", "#303641"),
            "idle_text": text,
            "bar_fg": ("#eef2f7", "#20232a"),
        }
        self.workspace_tab_labels = {
            "Chapters": f"{icons['chapters']}  Chapters",
            "Logs": f"{icons['terminal']}  Logs",
            "Debug JSON": f"{icons['json']}  Debug JSON",
            "Image URLs": f"{icons['images']}  Image URLs",
        }
        self.workspace_tab_bar = ctk.CTkFrame(
            workspace,
            fg_color=self.workspace_tab_colors["bar_fg"],
            corner_radius=8,
        )
        self.workspace_tab_bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        self.workspace_tab_bar.grid_columnconfigure(10, weight=1)
        self.workspace_tab_buttons: dict[str, ctk.CTkButton] = {}

        self.workspace_body = ctk.CTkFrame(workspace, fg_color="transparent", corner_radius=0)
        self.workspace_body.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self.workspace_body.grid_columnconfigure(0, weight=1)
        self.workspace_body.grid_rowconfigure(0, weight=1)

        chapter_tab = ttk.Frame(self.workspace_body, style="Surface.TFrame")
        chapter_tab.columnconfigure(0, weight=1)
        chapter_tab.rowconfigure(2, weight=1)

        chapter_header = ttk.Frame(chapter_tab)
        chapter_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        chapter_header.columnconfigure(0, weight=1)
        ttk.Label(chapter_header, text="Series Chapters", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(chapter_header, text="Filter", style="SurfaceHint.TLabel").grid(
            row=0,
            column=1,
            sticky="e",
            padx=(8, 6),
        )
        self.chapter_filter_combo = ctk.CTkComboBox(
            chapter_header,
            variable=self.chapter_filter_var,
            values=("All chapters", "Downloaded only", "Not downloaded"),
            state="readonly",
            width=160,
            height=32,
            corner_radius=8,
            fg_color=panel_alt,
            border_color=border,
            button_color=panel_alt,
            button_hover_color=("#e2e8f0", "#303641"),
            dropdown_fg_color=panel_bg,
            dropdown_hover_color=("#e2e8f0", "#343b46"),
            text_color=text,
            dropdown_text_color=text,
            font=(ui_font, 12),
            dropdown_font=(ui_font, 12),
            command=lambda _choice: self._refresh_chapter_table(),
        )
        self.chapter_filter_combo.grid(row=0, column=2, sticky="e")

        chapter_btns = ttk.Frame(chapter_tab, style="Toolbar.TFrame", padding=(10, 8))
        chapter_btns.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        chapter_btns.columnconfigure(4, weight=1)
        ctk.CTkButton(
            chapter_btns,
            text=f"{icons['select']}  Select All",
            command=self._select_all_chapters,
            width=112,
            height=32,
            corner_radius=8,
            fg_color=panel_alt,
            hover_color=("#e2e8f0", "#303641"),
            text_color=text,
            font=compact_button_font,
        ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(
            chapter_btns,
            text=f"{icons['clear']}  Clear Selection",
            command=self._clear_chapter_selection,
            width=142,
            height=32,
            corner_radius=8,
            fg_color=panel_alt,
            hover_color=("#e2e8f0", "#303641"),
            text_color=text,
            font=compact_button_font,
        ).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(
            chapter_btns,
            text=f"{icons['run']}  Run URL Parse",
            command=self._start_download,
            width=148,
            height=32,
            corner_radius=8,
            fg_color=panel_alt,
            hover_color=("#e2e8f0", "#303641"),
            text_color=text,
            font=compact_button_font,
        ).grid(row=0, column=2, padx=(0, 8))
        ctk.CTkButton(
            chapter_btns,
            text=f"{icons['images']}  Payload Images",
            command=self._start_image_download_from_payload,
            width=158,
            height=32,
            corner_radius=8,
            fg_color=panel_alt,
            hover_color=("#e2e8f0", "#303641"),
            text_color=text,
            font=compact_button_font,
        ).grid(row=0, column=3, padx=(0, 8))

        chapter_list_frame = ttk.Frame(chapter_tab)
        chapter_list_frame.grid(row=2, column=0, sticky="nsew")
        chapter_list_frame.columnconfigure(0, weight=1)
        chapter_list_frame.rowconfigure(0, weight=1)

        self.chapter_table = ttk.Treeview(
            chapter_list_frame,
            columns=("status", "chapter", "release", "url"),
            show="headings",
            selectmode="extended",
        )
        self.chapter_table.heading("status", text="Downloaded")
        self.chapter_table.heading("chapter", text="Chapter")
        self.chapter_table.heading("release", text="Release")
        self.chapter_table.heading("url", text="URL")
        self.chapter_table.column("status", width=105, stretch=False, anchor=tk.CENTER)
        self.chapter_table.column("chapter", width=260, stretch=False, anchor=tk.W)
        self.chapter_table.column("release", width=160, stretch=False, anchor=tk.W)
        self.chapter_table.column("url", width=620, stretch=True, anchor=tk.W)

        self.chapter_scroll_y = ttk.Scrollbar(
            chapter_list_frame,
            orient=tk.VERTICAL,
            style="Modern.Vertical.TScrollbar",
            command=self.chapter_table.yview,
        )
        self.chapter_scroll_x = ttk.Scrollbar(
            chapter_list_frame,
            orient=tk.HORIZONTAL,
            style="Modern.Horizontal.TScrollbar",
            command=self.chapter_table.xview,
        )
        self.chapter_table.configure(
            yscrollcommand=self.chapter_scroll_y.set,
            xscrollcommand=self.chapter_scroll_x.set,
        )
        self.chapter_table.grid(row=0, column=0, sticky="nsew")
        self.chapter_scroll_y.grid(row=0, column=1, sticky="ns")
        self.chapter_scroll_x.grid(row=1, column=0, sticky="ew")

        logs_tab = ttk.Frame(self.workspace_body, style="Surface.TFrame")
        logs_tab.columnconfigure(0, weight=1)
        logs_tab.rowconfigure(1, weight=1)
        logs_toolbar = ttk.Frame(logs_tab, style="Toolbar.TFrame", padding=(10, 8))
        logs_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        logs_toolbar.columnconfigure(0, weight=1)
        ttk.Label(logs_toolbar, text="Session log", style="ToolbarHint.TLabel").grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            logs_toolbar,
            text=f"{icons['folder']}  Open Folder",
            command=self._open_log_folder,
            width=124,
            height=32,
            corner_radius=8,
            fg_color=panel_alt,
            hover_color=("#e2e8f0", "#303641"),
            text_color=text,
            font=compact_button_font,
        ).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(
            logs_toolbar,
            text=f"{icons['clear']}  Clear",
            command=self._clear_logs,
            width=88,
            height=32,
            corner_radius=8,
            fg_color=panel_alt,
            hover_color=("#e2e8f0", "#303641"),
            text_color=text,
            font=compact_button_font,
        ).grid(row=0, column=2)

        logs_body = ttk.Frame(logs_tab)
        logs_body.grid(row=1, column=0, sticky="nsew")
        logs_body.columnconfigure(0, weight=1)
        logs_body.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            logs_body,
            wrap=tk.WORD,
            font=(mono_font, 10),
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
        )
        self.log_scroll_y = ttk.Scrollbar(
            logs_body,
            orient=tk.VERTICAL,
            style="Modern.Vertical.TScrollbar",
            command=self.log_text.yview,
        )
        self.log_text.configure(yscrollcommand=self.log_scroll_y.set, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_scroll_y.grid(row=0, column=1, sticky="ns")

        self.json_tab = ttk.Frame(self.workspace_body, style="Surface.TFrame")
        self.json_tab.columnconfigure(0, weight=1)
        self.json_tab.rowconfigure(0, weight=1)
        self.json_text = tk.Text(
            self.json_tab,
            wrap=tk.NONE,
            font=(mono_font, 10),
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
        )
        self.json_scroll_y = ttk.Scrollbar(
            self.json_tab,
            orient=tk.VERTICAL,
            style="Modern.Vertical.TScrollbar",
            command=self.json_text.yview,
        )
        self.json_scroll_x = ttk.Scrollbar(
            self.json_tab,
            orient=tk.HORIZONTAL,
            style="Modern.Horizontal.TScrollbar",
            command=self.json_text.xview,
        )
        self.json_text.configure(
            yscrollcommand=self.json_scroll_y.set,
            xscrollcommand=self.json_scroll_x.set,
            state=tk.DISABLED,
        )
        self.json_text.grid(row=0, column=0, sticky="nsew")
        self.json_scroll_y.grid(row=0, column=1, sticky="ns")
        self.json_scroll_x.grid(row=1, column=0, sticky="ew")

        self.url_tab = ttk.Frame(self.workspace_body, style="Surface.TFrame")
        self.url_tab.columnconfigure(0, weight=1)
        self.url_tab.rowconfigure(0, weight=1)
        self.url_table = ttk.Treeview(self.url_tab, columns=("index", "url"), show="headings")
        self.url_table.heading("index", text="#")
        self.url_table.heading("url", text="Image URL")
        self.url_table.column("index", width=50, anchor=tk.E, stretch=False)
        self.url_table.column("url", width=900, anchor=tk.W, stretch=True)
        url_scroll_y = ttk.Scrollbar(
            self.url_tab,
            orient=tk.VERTICAL,
            style="Modern.Vertical.TScrollbar",
            command=self.url_table.yview,
        )
        url_scroll_x = ttk.Scrollbar(
            self.url_tab,
            orient=tk.HORIZONTAL,
            style="Modern.Horizontal.TScrollbar",
            command=self.url_table.xview,
        )
        self.url_table.configure(yscrollcommand=url_scroll_y.set, xscrollcommand=url_scroll_x.set)
        self.url_table.grid(row=0, column=0, sticky="nsew")
        url_scroll_y.grid(row=0, column=1, sticky="ns")
        url_scroll_x.grid(row=1, column=0, sticky="ew")

        self.workspace_frames = {
            "Chapters": chapter_tab,
            "Logs": logs_tab,
            "Debug JSON": self.json_tab,
            "Image URLs": self.url_tab,
        }
        self.workspace_tab_names = ["Chapters", "Logs"]
        for frame in self.workspace_frames.values():
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_remove()

        self._refresh_library_combo()
        self._toggle_debug_tools()

    def _build_layout(self) -> None:
        self.root.configure(bg="#f3f6f8")
        main = ttk.Frame(self.root, style="App.TFrame", padding=(16, 14, 16, 12))
        main.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(main, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)

        title_stack = ttk.Frame(header, style="App.TFrame")
        title_stack.grid(row=0, column=0, sticky="w")
        ttk.Label(title_stack, text="MC-WS-DL-T", style="AppTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            title_stack,
            text="Manga and comic download workspace",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(1, 0))

        header_actions = ttk.Frame(header, style="App.TFrame")
        header_actions.grid(row=0, column=1, sticky="e")
        ttk.Label(header_actions, text="Theme", style="Hint.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        self.theme_combo = ttk.Combobox(
            header_actions,
            textvariable=self.theme_var,
            values=("light", "dark"),
            state="readonly",
            width=8,
        )
        self.theme_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.theme_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_theme_change())
        ttk.Button(
            header_actions,
            text="Library",
            command=self._open_current_library_folder,
            style="Secondary.TButton",
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            header_actions,
            text="Logs",
            command=self._open_log_popup,
            style="Secondary.TButton",
        ).pack(side=tk.LEFT)

        control_box = ttk.Frame(main, style="Card.TFrame", padding=(14, 12))
        control_box.grid(row=1, column=0, sticky="ew")
        control_box.columnconfigure(1, weight=1)
        control_box.columnconfigure(2, weight=0)
        control_box.columnconfigure(3, weight=0)

        ttk.Label(control_box, text="Series URL", style="Surface.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 10),
            pady=(0, 8),
        )
        url_entry = ttk.Entry(control_box, textvariable=self.url_var)
        url_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        self.load_series_button = ttk.Button(
            control_box,
            text="Load Chapters",
            command=self._start_series_discovery,
            style="Primary.TButton",
            width=15,
        )
        self.load_series_button.grid(row=0, column=2, columnspan=2, sticky="ew", padx=(10, 0), pady=(0, 8))

        ttk.Label(control_box, text="Library", style="Surface.TLabel").grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 10),
            pady=(0, 8),
        )
        self.image_dir_combo = ttk.Combobox(
            control_box,
            textvariable=self.image_dir_var,
            values=self.library_locations,
            state="normal",
        )
        self.image_dir_combo.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        self.image_dir_combo.bind("<<ComboboxSelected>>", lambda _event: self._persist_current_library())
        self.image_dir_combo.bind("<FocusOut>", lambda _event: self._persist_current_library())
        self.image_dir_combo.bind("<Return>", lambda _event: self._persist_current_library())
        ttk.Button(
            control_box,
            text="Browse",
            command=self._browse_image_dir,
            style="Secondary.TButton",
            width=10,
        ).grid(row=1, column=2, sticky="ew", padx=(10, 0), pady=(0, 8))
        ttk.Button(
            control_box,
            text="Open",
            command=self._open_current_library_folder,
            style="Secondary.TButton",
            width=8,
        ).grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=(0, 8))

        settings_grid = ttk.Frame(control_box, style="Surface.TFrame")
        settings_grid.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(2, 0))
        for column in (1, 3, 5, 7, 9):
            settings_grid.columnconfigure(column, weight=1)

        ttk.Label(settings_grid, text="Parser", style="SurfaceHint.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 6),
        )
        self.parser_combo = ttk.Combobox(
            settings_grid,
            textvariable=self.parser_var,
            values=get_available_parser_names(),
            state="readonly",
            width=12,
        )
        self.parser_combo.grid(row=0, column=1, sticky="ew", padx=(0, 12))

        ttk.Label(settings_grid, text="Browser", style="SurfaceHint.TLabel").grid(
            row=0,
            column=2,
            sticky="w",
            padx=(0, 6),
        )
        self.browser_combo = ttk.Combobox(
            settings_grid,
            textvariable=self.browser_var,
            values=("chrome", "firefox"),
            state="readonly",
            width=12,
        )
        self.browser_combo.grid(row=0, column=3, sticky="ew", padx=(0, 12))

        ttk.Label(settings_grid, text="Wait", style="SurfaceHint.TLabel").grid(row=0, column=4, sticky="w", padx=(0, 6))
        ttk.Entry(settings_grid, textvariable=self.wait_var, width=5).grid(row=0, column=5, sticky="w", padx=(0, 12))

        ttk.Label(settings_grid, text="Timeout", style="SurfaceHint.TLabel").grid(
            row=0,
            column=6,
            sticky="w",
            padx=(0, 6),
        )
        ttk.Entry(settings_grid, textvariable=self.timeout_var, width=5).grid(
            row=0,
            column=7,
            sticky="w",
            padx=(0, 12),
        )

        ttk.Label(settings_grid, text="Retries", style="SurfaceHint.TLabel").grid(
            row=0,
            column=8,
            sticky="w",
            padx=(0, 6),
        )
        ttk.Entry(settings_grid, textvariable=self.retries_var, width=5).grid(row=0, column=9, sticky="w")

        option_row = ttk.Frame(control_box, style="Surface.TFrame")
        option_row.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Checkbutton(
            option_row,
            text="Prefer dynamic first",
            variable=self.prefer_dynamic_var,
        ).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Checkbutton(
            option_row,
            text="Auto-download",
            variable=self.auto_download_var,
        ).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Label(option_row, text="Log level", style="SurfaceHint.TLabel").pack(side=tk.LEFT, padx=(2, 6))
        self.level_combo = ttk.Combobox(
            option_row,
            textvariable=self.log_level_var,
            values=("DEBUG", "INFO", "WARNING", "ERROR"),
            state="readonly",
            width=9,
        )
        self.level_combo.pack(side=tk.LEFT)
        self.logs_path_hint = ttk.Label(
            option_row,
            text="Auto-saved in ./logs (session file).",
            style="SurfaceHint.TLabel",
        )
        self.logs_path_hint.pack(side=tk.LEFT, padx=(12, 0))

        self.output_label = ttk.Label(control_box, text="Output JSON", style="Surface.TLabel")
        self.output_label.grid(row=4, column=0, sticky="w", padx=(0, 10), pady=(10, 0))
        self.output_entry = ttk.Entry(control_box, textvariable=self.output_var)
        self.output_entry.grid(row=4, column=1, sticky="ew", pady=(10, 0))
        self.output_browse_button = ttk.Button(
            control_box,
            text="Browse",
            command=self._browse_output_file,
            style="Secondary.TButton",
            width=10,
        )
        self.output_browse_button.grid(row=4, column=2, sticky="ew", padx=(10, 0), pady=(10, 0))

        self.debug_actions_frame = ttk.Frame(control_box, style="Surface.TFrame")
        self.debug_actions_frame.grid(row=5, column=0, columnspan=4, sticky="e", pady=(10, 0))
        self.copy_json_button = ttk.Button(self.debug_actions_frame, text="Copy JSON", command=self._copy_json, style="Slim.TButton")
        self.copy_json_button.pack(side=tk.LEFT, padx=(0, 8))
        self.save_json_button = ttk.Button(self.debug_actions_frame, text="Save JSON As", command=self._save_json_as, style="Slim.TButton")
        self.save_json_button.pack(side=tk.LEFT)

        content_pane = ttk.Panedwindow(main, orient=tk.VERTICAL)
        content_pane.grid(row=2, column=0, sticky="nsew", pady=(12, 0))

        result_frame = ttk.Frame(content_pane, style="Card.TFrame", padding=(12, 10))
        logs_frame = ttk.Frame(content_pane, style="Card.TFrame", padding=(12, 10))
        content_pane.add(result_frame, weight=4)
        content_pane.add(logs_frame, weight=2)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(1, weight=1)

        result_header = ttk.Frame(result_frame, style="Surface.TFrame")
        result_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        result_header.columnconfigure(0, weight=1)
        ttk.Label(result_header, text="Workspace", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            result_header,
            textvariable=self.series_status_var,
            style="SurfaceHint.TLabel",
        ).grid(row=0, column=1, sticky="e")

        self.result_tabs = ttk.Notebook(result_frame)
        self.result_tabs.grid(row=1, column=0, sticky="nsew")

        chapter_tab = ttk.Frame(self.result_tabs, style="Surface.TFrame", padding=(0, 8, 0, 0))
        chapter_tab.columnconfigure(0, weight=1)
        chapter_tab.rowconfigure(2, weight=1)

        chapter_header = ttk.Frame(chapter_tab, style="Surface.TFrame")
        chapter_header.grid(row=0, column=0, sticky="ew", padx=2, pady=(0, 8))
        chapter_header.columnconfigure(0, weight=1)

        ttk.Label(chapter_header, text="Series Chapters", style="Section.TLabel").grid(row=0, column=0, sticky="w")

        ttk.Label(chapter_header, text="Filter", style="SurfaceHint.TLabel").grid(
            row=0,
            column=1,
            sticky="e",
            padx=(8, 6),
        )
        self.chapter_filter_combo = ttk.Combobox(
            chapter_header,
            textvariable=self.chapter_filter_var,
            values=("All chapters", "Downloaded only", "Not downloaded"),
            state="readonly",
            width=16,
        )
        self.chapter_filter_combo.grid(row=0, column=2, sticky="e")
        self.chapter_filter_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_chapter_table())

        chapter_btns = ttk.Frame(chapter_tab, style="Toolbar.TFrame", padding=(10, 8))
        chapter_btns.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        chapter_btns.columnconfigure(9, weight=1)

        self.download_selected_button = ttk.Button(
            chapter_btns,
            text="Start Queue",
            command=self._start_download_selected_chapters,
            style="Primary.TButton",
        )
        self.download_selected_button.grid(row=0, column=0, padx=(0, 8))

        self.pause_queue_button = ttk.Button(
            chapter_btns,
            text="Pause",
            command=self._pause_queue,
            state=tk.DISABLED,
            style="Slim.TButton",
        )
        self.pause_queue_button.grid(row=0, column=1, padx=(0, 8))

        self.resume_queue_button = ttk.Button(
            chapter_btns,
            text="Resume",
            command=self._resume_queue,
            state=tk.DISABLED,
            style="Slim.TButton",
        )
        self.resume_queue_button.grid(row=0, column=2, padx=(0, 8))

        self.cancel_queue_button = ttk.Button(
            chapter_btns,
            text="Cancel",
            command=self._cancel_queue,
            state=tk.DISABLED,
            style="Slim.TButton",
        )
        self.cancel_queue_button.grid(row=0, column=3, padx=(0, 8))

        self.retry_failed_button = ttk.Button(
            chapter_btns,
            text="Retry Failed",
            command=self._retry_failed_chapters,
            state=tk.DISABLED,
            style="Slim.TButton",
        )
        self.retry_failed_button.grid(row=0, column=4, padx=(0, 12))

        ttk.Label(chapter_btns, text="Retry/chapter", style="ToolbarHint.TLabel").grid(row=0, column=5, padx=(0, 6))
        self.retry_spin = ttk.Spinbox(
            chapter_btns,
            from_=0,
            to=10,
            textvariable=self.retry_per_chapter_var,
            width=4,
        )
        self.retry_spin.grid(row=0, column=6, padx=(0, 12))

        ttk.Button(chapter_btns, text="Select All", command=self._select_all_chapters, style="Slim.TButton").grid(
            row=0,
            column=7,
            padx=(0, 8),
        )
        ttk.Button(chapter_btns, text="Clear", command=self._clear_chapter_selection, style="Slim.TButton").grid(
            row=0,
            column=8,
            padx=(0, 4),
        )

        chapter_list_frame = ttk.Frame(chapter_tab, style="Surface.TFrame")
        chapter_list_frame.grid(row=2, column=0, sticky="nsew")
        chapter_list_frame.columnconfigure(0, weight=1)
        chapter_list_frame.rowconfigure(0, weight=1)

        self.chapter_table = ttk.Treeview(
            chapter_list_frame,
            columns=("status", "chapter", "release", "url"),
            show="headings",
            selectmode="extended",
        )
        self.chapter_table.heading("status", text="Downloaded")
        self.chapter_table.heading("chapter", text="Chapter")
        self.chapter_table.heading("release", text="Release")
        self.chapter_table.heading("url", text="URL")
        self.chapter_table.column("status", width=105, stretch=False, anchor=tk.CENTER)
        self.chapter_table.column("chapter", width=260, stretch=False, anchor=tk.W)
        self.chapter_table.column("release", width=160, stretch=False, anchor=tk.W)
        self.chapter_table.column("url", width=620, stretch=True, anchor=tk.W)

        self.chapter_scroll_y = ttk.Scrollbar(
            chapter_list_frame,
            orient=tk.VERTICAL,
            style="Modern.Vertical.TScrollbar",
            command=self.chapter_table.yview,
        )
        self.chapter_scroll_x = ttk.Scrollbar(
            chapter_list_frame,
            orient=tk.HORIZONTAL,
            style="Modern.Horizontal.TScrollbar",
            command=self.chapter_table.xview,
        )
        self.chapter_table.configure(
            yscrollcommand=self.chapter_scroll_y.set,
            xscrollcommand=self.chapter_scroll_x.set,
        )
        self.chapter_table.grid(row=0, column=0, sticky="nsew")
        self.chapter_scroll_y.grid(row=0, column=1, sticky="ns")
        self.chapter_scroll_x.grid(row=1, column=0, sticky="ew")

        self.result_tabs.add(chapter_tab, text="Series Chapters")

        self.json_tab = ttk.Frame(self.result_tabs, style="Surface.TFrame", padding=(0, 8, 0, 0))
        self.json_tab.columnconfigure(0, weight=1)
        self.json_tab.rowconfigure(0, weight=1)
        self.json_text = tk.Text(
            self.json_tab,
            wrap=tk.NONE,
            font=(self.mono_font_family, 10),
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
        )
        self.json_scroll_y = ttk.Scrollbar(
            self.json_tab,
            orient=tk.VERTICAL,
            style="Modern.Vertical.TScrollbar",
            command=self.json_text.yview,
        )
        self.json_scroll_x = ttk.Scrollbar(
            self.json_tab,
            orient=tk.HORIZONTAL,
            style="Modern.Horizontal.TScrollbar",
            command=self.json_text.xview,
        )
        self.json_text.configure(
            yscrollcommand=self.json_scroll_y.set,
            xscrollcommand=self.json_scroll_x.set,
            state=tk.DISABLED,
        )
        self.json_text.grid(row=0, column=0, sticky="nsew")
        self.json_scroll_y.grid(row=0, column=1, sticky="ns")
        self.json_scroll_x.grid(row=1, column=0, sticky="ew")
        self.result_tabs.add(self.json_tab, text="Debug JSON")

        self.url_tab = ttk.Frame(self.result_tabs, style="Surface.TFrame", padding=(0, 8, 0, 0))
        self.url_tab.columnconfigure(0, weight=1)
        self.url_tab.rowconfigure(0, weight=1)

        self.url_table = ttk.Treeview(self.url_tab, columns=("index", "url"), show="headings")
        self.url_table.heading("index", text="#")
        self.url_table.heading("url", text="Image URL")
        self.url_table.column("index", width=50, anchor=tk.E, stretch=False)
        self.url_table.column("url", width=900, anchor=tk.W, stretch=True)

        url_scroll_y = ttk.Scrollbar(
            self.url_tab,
            orient=tk.VERTICAL,
            style="Modern.Vertical.TScrollbar",
            command=self.url_table.yview,
        )
        url_scroll_x = ttk.Scrollbar(
            self.url_tab,
            orient=tk.HORIZONTAL,
            style="Modern.Horizontal.TScrollbar",
            command=self.url_table.xview,
        )
        self.url_table.configure(yscrollcommand=url_scroll_y.set, xscrollcommand=url_scroll_x.set)

        self.url_table.grid(row=0, column=0, sticky="nsew")
        url_scroll_y.grid(row=0, column=1, sticky="ns")
        url_scroll_x.grid(row=1, column=0, sticky="ew")

        self.result_tabs.add(self.url_tab, text="Image URLs")

        logs_frame.columnconfigure(0, weight=1)
        logs_frame.rowconfigure(1, weight=1)

        logs_toolbar = ttk.Frame(logs_frame, style="Surface.TFrame")
        logs_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        logs_toolbar.columnconfigure(0, weight=1)
        ttk.Label(logs_toolbar, text="Logs", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(logs_toolbar, text="Open Folder", command=self._open_log_folder, style="Slim.TButton").grid(
            row=0,
            column=1,
            padx=(0, 8),
        )
        ttk.Button(logs_toolbar, text="Pop Out", command=self._open_log_popup, style="Slim.TButton").grid(
            row=0,
            column=2,
            padx=(0, 8),
        )
        ttk.Button(logs_toolbar, text="Clear", command=self._clear_logs, style="Slim.TButton").grid(row=0, column=3)

        logs_body = ttk.Frame(logs_frame, style="Surface.TFrame")
        logs_body.grid(row=1, column=0, sticky="nsew")
        logs_body.columnconfigure(0, weight=1)
        logs_body.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            logs_body,
            wrap=tk.WORD,
            font=(self.mono_font_family, 10),
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
        )
        self.log_scroll_y = ttk.Scrollbar(
            logs_body,
            orient=tk.VERTICAL,
            style="Modern.Vertical.TScrollbar",
            command=self.log_text.yview,
        )
        self.log_text.configure(yscrollcommand=self.log_scroll_y.set, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_scroll_y.grid(row=0, column=1, sticky="ns")

        footer = ttk.Frame(main, style="Status.TFrame", padding=(10, 6))
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.summary_var, style="Status.TLabel", anchor=tk.W).grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel", anchor=tk.E).grid(
            row=0,
            column=1,
            sticky="e",
        )

        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)
        self._refresh_library_combo()
        self._toggle_debug_tools()

    def _show_workspace_tab(self, tab_name: str) -> None:
        frames = cast(dict[str, Any], getattr(self, "workspace_frames", {}))
        if not frames:
            return

        active_tab = tab_name if tab_name in frames else "Chapters"
        for frame_name, frame in frames.items():
            if frame_name == active_tab:
                frame.grid()
            else:
                frame.grid_remove()

        tab_var = cast(tk.StringVar | None, getattr(self, "workspace_tab_var", None))
        if tab_var is not None and tab_var.get() != active_tab:
            tab_var.set(active_tab)

        buttons = cast(dict[str, Any], getattr(self, "workspace_tab_buttons", {}))
        colors = cast(dict[str, Any], getattr(self, "workspace_tab_colors", {}))
        for button_name, button in buttons.items():
            if button_name == active_tab:
                button.configure(
                    fg_color=colors["selected_fg"],
                    hover_color=colors["selected_hover"],
                    text_color=colors["selected_text"],
                )
            else:
                button.configure(
                    fg_color=colors["idle_fg"],
                    hover_color=colors["idle_hover"],
                    text_color=colors["idle_text"],
                )

    def _rebuild_workspace_tab_buttons(self, tab_names: list[str]) -> None:
        tab_bar = cast(Any, getattr(self, "workspace_tab_bar", None))
        colors = cast(dict[str, Any], getattr(self, "workspace_tab_colors", {}))
        if tab_bar is None or not colors:
            return

        existing_buttons = cast(dict[str, Any], getattr(self, "workspace_tab_buttons", {}))
        for button in existing_buttons.values():
            button.destroy()

        self.workspace_tab_buttons = {}
        labels = cast(dict[str, str], getattr(self, "workspace_tab_labels", {}))
        for index, tab_name in enumerate(tab_names):
            button = ctk.CTkButton(
                tab_bar,
                text=labels.get(tab_name, tab_name),
                command=lambda name=tab_name: self._show_workspace_tab(name),
                width=154,
                height=34,
                corner_radius=8,
                border_width=0,
                fg_color=colors["idle_fg"],
                hover_color=colors["idle_hover"],
                text_color=colors["idle_text"],
                font=(self.ui_font_family, 12, "bold"),
            )
            button.grid(row=0, column=index, sticky="w", padx=(4 if index == 0 else 2, 2), pady=4)
            self.workspace_tab_buttons[tab_name] = button

    def _set_workspace_tabs(self, tab_names: list[str]) -> None:
        if not hasattr(self, "workspace_tab_bar"):
            return

        self.workspace_tab_names = tab_names
        self._rebuild_workspace_tab_buttons(tab_names)

        tab_var = cast(tk.StringVar, getattr(self, "workspace_tab_var"))
        current_tab = tab_var.get()
        if current_tab not in tab_names:
            current_tab = "Chapters"

        self._show_workspace_tab(current_tab)

    def _toggle_debug_tools(self) -> None:
        # Keep JSON export features available, but hide them from the default operator flow.
        show_debug = self.show_debug_var.get()

        if hasattr(self, "workspace_tab_bar"):
            if show_debug:
                self.output_label.grid()
                self.output_entry.grid()
                self.output_browse_button.grid()
                self.debug_actions_frame.grid()
                self._json_tab_visible = True
                self._url_tab_visible = True
                self._set_workspace_tabs(["Chapters", "Logs", "Debug JSON", "Image URLs"])
            else:
                self.output_label.grid_remove()
                self.output_entry.grid_remove()
                self.output_browse_button.grid_remove()
                self.debug_actions_frame.grid_remove()
                self._json_tab_visible = False
                self._url_tab_visible = False
                self._set_workspace_tabs(["Chapters", "Logs"])
            return

        if show_debug:
            self.output_label.grid()
            self.output_entry.grid()
            self.output_browse_button.grid()
            self.debug_actions_frame.grid()
            if not self._json_tab_visible:
                self.result_tabs.add(self.json_tab, text="Debug JSON")
                self._json_tab_visible = True
            if not self._url_tab_visible:
                self.result_tabs.add(self.url_tab, text="Image URLs")
                self._url_tab_visible = True
        else:
            self.output_label.grid_remove()
            self.output_entry.grid_remove()
            self.output_browse_button.grid_remove()
            self.debug_actions_frame.grid_remove()
            if self._json_tab_visible:
                self.result_tabs.hide(self.json_tab)
                self._json_tab_visible = False
            if self._url_tab_visible:
                self.result_tabs.hide(self.url_tab)
                self._url_tab_visible = False

    def _open_log_folder(self) -> None:
        log_path = Path(self.log_file_var.get())
        log_dir = log_path.parent
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(log_dir))  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Open log folder failed", str(exc))

    def _choose_library_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Choose library folder")
        if not chosen:
            return
        self.image_dir_var.set(chosen)
        self._persist_current_library()

    def _open_current_library_folder(self) -> None:
        current_library = self.image_dir_var.get().strip()
        if not current_library:
            messagebox.showinfo("Library folder", "No library folder is set yet.")
            return
        library_path = Path(current_library).expanduser()
        library_path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(library_path))  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Open library folder failed", str(exc))

    def _open_log_popup(self) -> None:
        if self._log_popup and self._log_popup.winfo_exists():
            self._log_popup.deiconify()
            self._log_popup.lift()
            return

        popup = tk.Toplevel(self.root)
        popup.title("MC-WS-DL-T Logs")
        popup.geometry("980x420")
        popup.minsize(760, 300)
        if hasattr(self, "_current_palette"):
            popup.configure(bg=self._current_palette["bg"])

        popup_frame = ttk.Frame(popup, padding=8)
        popup_frame.pack(fill=tk.BOTH, expand=True)
        popup_frame.columnconfigure(0, weight=1)
        popup_frame.rowconfigure(0, weight=1)
        self._popup_log_text = tk.Text(
            popup_frame,
            wrap=tk.WORD,
            font=(self.mono_font_family, 10),
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
        )
        popup_scroll_y = ttk.Scrollbar(
            popup_frame,
            orient=tk.VERTICAL,
            style="Modern.Vertical.TScrollbar",
            command=self._popup_log_text.yview,
        )
        self._popup_log_text.configure(yscrollcommand=popup_scroll_y.set, state=tk.DISABLED)
        self._popup_log_text.grid(row=0, column=0, sticky="nsew")
        popup_scroll_y.grid(row=0, column=1, sticky="ns")

        existing_logs = self.log_text.get("1.0", tk.END)
        self._popup_log_text.configure(state=tk.NORMAL)
        self._popup_log_text.insert(tk.END, existing_logs)
        self._popup_log_text.see(tk.END)
        self._popup_log_text.configure(state=tk.DISABLED)

        def _on_close() -> None:
            self._popup_log_text = None
            popup.destroy()

        popup.protocol("WM_DELETE_WINDOW", _on_close)
        self._log_popup = popup
        self._apply_theme(self.theme_var.get())

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{line}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        if self._popup_log_text and self._popup_log_text.winfo_exists():
            self._popup_log_text.configure(state=tk.NORMAL)
            self._popup_log_text.insert(tk.END, f"{line}\n")
            self._popup_log_text.see(tk.END)
            self._popup_log_text.configure(state=tk.DISABLED)

    def _clear_logs(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        if self._popup_log_text and self._popup_log_text.winfo_exists():
            self._popup_log_text.configure(state=tk.NORMAL)
            self._popup_log_text.delete("1.0", tk.END)
            self._popup_log_text.configure(state=tk.DISABLED)
        self.status_var.set("Logs cleared.")

    def _show_quick_workflow(self) -> None:
        messagebox.showinfo(
            "Quick Workflow",
            (
                "1) Paste a series URL.\n"
                "2) Click 'Load Series Chapters'.\n"
                "3) Select chapters in 'Series Chapters'.\n"
                "4) Click 'Start Queue' to download CBZ files."
            ),
        )

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About MC-WS-DL-T",
            "MC-WS-DL-T\nManga/Comic downloader with chapter queue, retry, and CBZ output.",
        )

    def _set_json_output(self, payload: dict[str, object]) -> None:
        rendered = json.dumps(payload, indent=2, ensure_ascii=False)
        self.json_text.configure(state=tk.NORMAL)
        self.json_text.delete("1.0", tk.END)
        self.json_text.insert(tk.END, rendered)
        self.json_text.configure(state=tk.DISABLED)

    def _set_url_table(self, image_urls: list[str]) -> None:
        for row in self.url_table.get_children():
            self.url_table.delete(row)
        for index, image_url in enumerate(image_urls, start=1):
            tags = ("odd",) if index % 2 else ()
            self.url_table.insert("", tk.END, values=(index, image_url), tags=tags)

    def _browse_output_file(self) -> None:
        chosen = filedialog.asksaveasfilename(
            title="Choose output JSON file",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if chosen:
            self.output_var.set(chosen)

    def _browse_image_dir(self) -> None:
        chosen = filedialog.askdirectory(title="Choose image download folder")
        if chosen:
            self.image_dir_var.set(chosen)
            self._persist_current_library()

    def _browse_log_file(self) -> None:
        chosen = filedialog.asksaveasfilename(
            title="Choose log file",
            defaultextension=".log",
            filetypes=(("Log files", "*.log"), ("All files", "*.*")),
        )
        if chosen:
            self.log_file_var.set(chosen)

    def _set_busy(self, busy: bool) -> None:
        self.is_running = busy
        run_state = tk.DISABLED if busy else tk.NORMAL
        self.load_series_button.configure(state=run_state)
        self.status_var.set("Running download..." if busy else "Ready.")
        self._update_queue_control_states()

    def _update_queue_control_states(self) -> None:
        # Queue controls stay active while a chapter batch is running so pause/cancel works.
        start_state = tk.DISABLED if self.is_running else tk.NORMAL
        if self.queue_active:
            start_state = tk.DISABLED
        self.download_selected_button.configure(state=start_state)

        if self.queue_active:
            self.pause_queue_button.configure(
                state=tk.NORMAL if not self.queue_paused and not self._queue_cancel_event.is_set() else tk.DISABLED
            )
            self.resume_queue_button.configure(
                state=tk.NORMAL if self.queue_paused and not self._queue_cancel_event.is_set() else tk.DISABLED
            )
            self.cancel_queue_button.configure(state=tk.NORMAL if not self._queue_cancel_event.is_set() else tk.DISABLED)
            self.retry_failed_button.configure(state=tk.DISABLED)
            self.retry_spin.configure(state=tk.DISABLED)
        else:
            self.pause_queue_button.configure(state=tk.DISABLED)
            self.resume_queue_button.configure(state=tk.DISABLED)
            self.cancel_queue_button.configure(state=tk.DISABLED)
            self.retry_spin.configure(state=tk.NORMAL if not self.is_running else tk.DISABLED)
            can_retry_failed = bool(self.current_failed_chapter_urls) and not self.is_running
            self.retry_failed_button.configure(state=tk.NORMAL if can_retry_failed else tk.DISABLED)

    def _parse_positive_int(self, raw_value: str, field_name: str) -> int:
        try:
            value = int(raw_value.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a number.") from exc
        if value <= 0:
            raise ValueError(f"{field_name} must be greater than zero.")
        return value

    def _parse_non_negative_int(self, raw_value: str, field_name: str) -> int:
        try:
            value = int(raw_value.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a number.") from exc
        if value < 0:
            raise ValueError(f"{field_name} cannot be negative.")
        return value

    def _build_options_from_form(self) -> DownloadOptions:
        url = self.url_var.get().strip()
        if not url:
            raise ValueError("URL is required.")

        timeout_seconds = self._parse_positive_int(self.timeout_var.get(), "Timeout")
        wait_seconds = self._parse_positive_int(self.wait_var.get(), "Wait")
        retries = self._parse_positive_int(self.retries_var.get(), "Retries")

        output_path = self.output_var.get().strip()
        output = Path(output_path) if output_path else None
        image_dir_path = self.image_dir_var.get().strip()

        image_download_dir: Path | None = None
        if self.auto_download_var.get():
            if not image_dir_path:
                raise ValueError("Image folder is required when auto-download is enabled.")
            image_download_dir = Path(image_dir_path)

        return DownloadOptions(
            url=url,
            browser=self.browser_var.get().strip(),
            prefer_dynamic=self.prefer_dynamic_var.get(),
            timeout_seconds=timeout_seconds,
            wait_seconds=wait_seconds,
            retries=retries,
            force_parser=self.parser_var.get().strip(),
            output=output,
            image_download_dir=image_download_dir,
        )

    def _build_ui_logger(self) -> logging.Logger:
        logger = logging.getLogger("mc_ws_dl_t.ui")
        logger.setLevel(getattr(logging, self.log_level_var.get().upper(), logging.INFO))
        logger.handlers.clear()
        logger.propagate = False

        logger.addHandler(QueueLogHandler(self.event_queue))

        # Session logs are written by default so issues can be reviewed later.
        log_file_value = self.log_file_var.get().strip()
        if not log_file_value:
            log_file_value = str(self._build_default_log_file_path())
            self.log_file_var.set(log_file_value)
        if log_file_value:
            log_file = Path(log_file_value)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(file_handler)

        return logger

    def _start_download(self) -> None:
        if self.is_running:
            return

        try:
            options = self._build_options_from_form()
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        self.current_payload = None
        self.summary_var.set("Download in progress...")
        self._set_busy(True)
        self._append_log("----- New run started -----")

        worker = threading.Thread(target=self._run_download_worker, args=(options,), daemon=True)
        worker.start()

    def _run_download_worker(self, options: DownloadOptions) -> None:
        logger = self._build_ui_logger()
        try:
            payload = run_download(options, logger=logger)
            self.event_queue.put(("result", payload))
        except Exception as exc:
            self.event_queue.put(("error", str(exc)))
            self.event_queue.put(("trace", traceback.format_exc()))
        finally:
            self.event_queue.put(("done", None))

    def _build_runtime_config(self) -> ScraperConfig:
        timeout_seconds = self._parse_positive_int(self.timeout_var.get(), "Timeout")
        wait_seconds = self._parse_positive_int(self.wait_var.get(), "Wait")
        retries = self._parse_positive_int(self.retries_var.get(), "Retries")
        return ScraperConfig(
            timeout_seconds=timeout_seconds,
            wait_seconds=wait_seconds,
            retries=retries,
        )

    def _series_root_from_current(self) -> Path | None:
        if not self.current_series:
            return None
        base_path_raw = self.image_dir_var.get().strip()
        if not base_path_raw:
            return None
        return build_series_root_path(Path(base_path_raw), self.current_series.title)

    def _refresh_chapter_table(self) -> None:
        selected_urls = {
            str(self.chapter_table.item(item, "values")[3])
            for item in self.chapter_table.selection()
            if self.chapter_table.item(item, "values")
        }
        for row in self.chapter_table.get_children():
            self.chapter_table.delete(row)

        downloaded_urls: set[str] = set()
        chapters_history = self.current_series_history.get("chapters")
        if isinstance(chapters_history, dict):
            downloaded_urls = set(str(url) for url in chapters_history.keys())

        active_filter = self.chapter_filter_var.get().strip()
        new_selection: list[str] = []
        for chapter in self.current_series_chapters:
            status = "Yes" if chapter.url in downloaded_urls else "No"
            is_downloaded = status == "Yes"
            if active_filter == "Downloaded only" and not is_downloaded:
                continue
            if active_filter == "Not downloaded" and is_downloaded:
                continue

            row_id = self.chapter_table.insert(
                "",
                tk.END,
                values=(status, chapter.title, chapter.release, chapter.url),
                tags=("downloaded" if is_downloaded else "pending",),
            )
            if chapter.url in selected_urls:
                new_selection.append(row_id)
        if new_selection:
            self.chapter_table.selection_set(new_selection)

    def _select_all_chapters(self) -> None:
        children = self.chapter_table.get_children()
        if children:
            self.chapter_table.selection_set(children)

    def _clear_chapter_selection(self) -> None:
        self.chapter_table.selection_remove(self.chapter_table.selection())

    def _start_series_discovery(self) -> None:
        if self.is_running:
            return

        series_url = self.url_var.get().strip()
        if not series_url:
            messagebox.showerror("Missing URL", "Enter a series URL first.")
            return

        try:
            config = self._build_runtime_config()
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        self._set_busy(True)
        self.status_var.set("Loading chapters...")
        self.series_status_var.set("Loading series information...")
        self._append_log("----- Series discovery started -----")

        worker = threading.Thread(
            target=self._run_series_discovery_worker,
            args=(series_url, config),
            daemon=True,
        )
        worker.start()

    def _run_series_discovery_worker(self, series_url: str, config: ScraperConfig) -> None:
        logger = self._build_ui_logger()
        try:
            series_info = discover_series(
                series_url=series_url,
                config=config,
                logger=logger,
                prefer_dynamic=self.prefer_dynamic_var.get(),
                browser=self.browser_var.get().strip(),
            )
            self.event_queue.put(("series_result", series_info))
        except Exception as exc:
            self.event_queue.put(("error", str(exc)))
            self.event_queue.put(("trace", traceback.format_exc()))
        finally:
            self.event_queue.put(("done", None))

    def _start_download_selected_chapters(self) -> None:
        if self.is_running:
            return
        if not self.current_series:
            messagebox.showinfo("No series", "Load series chapters first.")
            return

        selected_items = list(self.chapter_table.selection())
        if not selected_items:
            messagebox.showinfo("No selection", "Select one or more chapters first.")
            return

        base_path_raw = self.image_dir_var.get().strip()
        if not base_path_raw:
            messagebox.showerror("Missing folder", "Choose an image folder first.")
            return

        try:
            config = self._build_runtime_config()
            retry_per_chapter = self._parse_non_negative_int(self.retry_per_chapter_var.get(), "Retry/chapter")
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        selected_urls = {
            str(self.chapter_table.item(item, "values")[3])
            for item in selected_items
            if self.chapter_table.item(item, "values")
        }
        selected_chapters = [chapter for chapter in self.current_series_chapters if chapter.url in selected_urls]
        if not selected_chapters:
            messagebox.showinfo("No selection", "No valid chapters selected.")
            return

        self._start_chapter_queue(
            selected_chapters=selected_chapters,
            base_dir=Path(base_path_raw),
            config=config,
            retry_per_chapter=retry_per_chapter,
            queue_label="selected chapters",
        )

    def _start_chapter_queue(
        self,
        selected_chapters: list[SeriesChapter],
        base_dir: Path,
        config: ScraperConfig,
        retry_per_chapter: int,
        queue_label: str,
    ) -> None:
        # Reset queue-control events before starting a new batch worker.
        self._queue_pause_event.set()
        self._queue_cancel_event.clear()
        self.queue_active = True
        self.queue_paused = False
        self.current_failed_chapter_urls = []
        self._set_busy(True)
        self.status_var.set(f"Queue started for {queue_label}.")
        self.summary_var.set(f"Queue running for {queue_label}...")
        self._append_log(f"----- Queue started ({queue_label}) -----")
        self._update_queue_control_states()

        worker = threading.Thread(
            target=self._run_selected_download_worker,
            args=(selected_chapters, base_dir, config, retry_per_chapter),
            daemon=True,
        )
        worker.start()

    def _pause_queue(self) -> None:
        if not self.queue_active or self.queue_paused:
            return
        self.queue_paused = True
        self._queue_pause_event.clear()
        self.status_var.set("Queue paused.")
        self._append_log("Queue paused by user.")
        self._update_queue_control_states()

    def _resume_queue(self) -> None:
        if not self.queue_active or not self.queue_paused:
            return
        self.queue_paused = False
        self._queue_pause_event.set()
        self.status_var.set("Queue resumed.")
        self._append_log("Queue resumed by user.")
        self._update_queue_control_states()

    def _cancel_queue(self) -> None:
        if not self.queue_active:
            return
        self._queue_cancel_event.set()
        self._queue_pause_event.set()
        self.queue_paused = False
        self.status_var.set("Cancel requested. Finishing current step...")
        self._append_log("Queue cancel requested by user.")
        self._update_queue_control_states()

    def _retry_failed_chapters(self) -> None:
        if self.is_running:
            return
        if not self.current_series:
            messagebox.showinfo("No series", "Load a series first.")
            return
        if not self.current_failed_chapter_urls:
            messagebox.showinfo("No failed chapters", "There are no failed chapters to retry.")
            return

        base_path_raw = self.image_dir_var.get().strip()
        if not base_path_raw:
            messagebox.showerror("Missing folder", "Choose an image folder first.")
            return

        try:
            config = self._build_runtime_config()
            retry_per_chapter = self._parse_non_negative_int(self.retry_per_chapter_var.get(), "Retry/chapter")
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        failed_set = set(self.current_failed_chapter_urls)
        chapters_to_retry = [chapter for chapter in self.current_series_chapters if chapter.url in failed_set]
        if not chapters_to_retry:
            messagebox.showinfo("No failed chapters", "Failed chapter list no longer matches the loaded series.")
            return

        self._start_chapter_queue(
            selected_chapters=chapters_to_retry,
            base_dir=Path(base_path_raw),
            config=config,
            retry_per_chapter=retry_per_chapter,
            queue_label=f"{len(chapters_to_retry)} failed chapter(s)",
        )

    def _is_queue_canceled(self) -> bool:
        return self._queue_cancel_event.is_set()

    def _wait_if_queue_paused(self) -> None:
        while not self._queue_pause_event.is_set():
            if self._queue_cancel_event.is_set():
                return
            time.sleep(0.15)

    def _run_selected_download_worker(
        self,
        selected_chapters: list[SeriesChapter],
        base_dir: Path,
        config: ScraperConfig,
        retry_per_chapter: int,
    ) -> None:
        logger = self._build_ui_logger()
        try:
            if not self.current_series:
                raise RuntimeError("Series context was lost before download started.")
            result = download_selected_chapters_as_cbz(
                series_info=self.current_series,
                selected_chapters=selected_chapters,
                library_root_dir=base_dir,
                config=config,
                logger=logger,
                browser=self.browser_var.get().strip(),
                prefer_dynamic=self.prefer_dynamic_var.get(),
                retry_per_chapter=retry_per_chapter,
                should_cancel=self._is_queue_canceled,
                wait_if_paused=self._wait_if_queue_paused,
                progress_callback=lambda event: self.event_queue.put(("chapter_progress", event)),
            )
            self.event_queue.put(("chapter_download_result", result))
        except Exception as exc:
            self.event_queue.put(("error", str(exc)))
            self.event_queue.put(("trace", traceback.format_exc()))
        finally:
            self.event_queue.put(("done", None))

    def _start_image_download_from_payload(self) -> None:
        if self.is_running:
            return
        if not self.current_payload:
            messagebox.showinfo("No data", "Run a download first so image URLs are available.")
            return

        image_dir_path = self.image_dir_var.get().strip()
        if not image_dir_path:
            messagebox.showerror("Missing folder", "Choose an image folder first.")
            return

        try:
            config = self._build_runtime_config()
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        self._set_busy(True)
        self.status_var.set("Downloading images...")
        self.summary_var.set("Image download in progress...")
        self._append_log("----- Image download started from current payload -----")

        payload_copy = dict(self.current_payload)
        target_dir = Path(image_dir_path)
        worker = threading.Thread(
            target=self._run_image_download_worker,
            args=(payload_copy, target_dir, config),
            daemon=True,
        )
        worker.start()

    def _run_image_download_worker(
        self,
        payload: dict[str, object],
        target_dir: Path,
        config: ScraperConfig,
    ) -> None:
        logger = self._build_ui_logger()
        try:
            summary = download_images_from_payload(
                payload=payload,
                output_base_dir=target_dir,
                config=config,
                logger=logger,
            )
            self.event_queue.put(("image_download_result", summary))
        except Exception as exc:
            self.event_queue.put(("error", str(exc)))
            self.event_queue.put(("trace", traceback.format_exc()))
        finally:
            self.event_queue.put(("done", None))

    def _copy_json(self) -> None:
        if not self.current_payload:
            messagebox.showinfo("No data", "Run a download first so there is JSON to copy.")
            return
        rendered = json.dumps(self.current_payload, indent=2, ensure_ascii=False)
        self.root.clipboard_clear()
        self.root.clipboard_append(rendered)
        self.status_var.set("JSON copied to clipboard.")

    def _save_json_as(self) -> None:
        if not self.current_payload:
            messagebox.showinfo("No data", "Run a download first so there is JSON to save.")
            return

        chosen = filedialog.asksaveasfilename(
            title="Save payload JSON",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not chosen:
            return

        out_path = Path(chosen)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(self.current_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.status_var.set(f"Saved: {out_path}")

    def _process_events(self) -> None:
        while True:
            try:
                event_type, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break

            if event_type == "log":
                self._append_log(str(payload))
            elif event_type == "series_result":
                if isinstance(payload, SeriesInfo):
                    self.current_series = payload
                    self.current_series_chapters = list(payload.chapters)
                    self.current_failed_chapter_urls = []
                    self.url_var.set(payload.url)

                    series_root = self._series_root_from_current()
                    self.current_series_history = load_history(series_root) if series_root else {"chapters": {}}
                    self._refresh_chapter_table()
                    self.series_status_var.set(
                        f"{payload.title} | Chapters: {len(payload.chapters)} | Parser: {payload.parser}"
                    )
                    self.summary_var.set("Series chapters loaded. Select chapters to download as CBZ.")
                    self._update_queue_control_states()
            elif event_type == "chapter_progress":
                if isinstance(payload, dict):
                    progress_event = str(payload.get("event", ""))
                    chapter_title = str(payload.get("title", "")).strip()
                    index = int(payload.get("index", 0)) if str(payload.get("index", "")).isdigit() else 0
                    total = int(payload.get("total", 0)) if str(payload.get("total", "")).isdigit() else 0

                    if progress_event == "batch_start":
                        total_val = int(payload.get("total", 0))
                        self.status_var.set(f"Queue started. Chapters: {total_val}")
                        self.summary_var.set(f"Queue running. Total chapters: {total_val}")
                    elif progress_event == "chapter_start":
                        self.status_var.set(f"Chapter {index}/{total}: {chapter_title}")
                    elif progress_event == "chapter_retry":
                        next_attempt = int(payload.get("next_attempt", 0))
                        self._append_log(
                            f"Retry scheduled for chapter {index}/{total}: {chapter_title} (attempt {next_attempt})"
                        )
                    elif progress_event == "chapter_downloaded":
                        self.status_var.set(f"Downloaded {index}/{total}: {chapter_title}")
                    elif progress_event == "chapter_skipped":
                        self.status_var.set(f"Skipped {index}/{total}: {chapter_title} (already downloaded)")
                    elif progress_event == "chapter_failed":
                        error = str(payload.get("error", ""))
                        self.status_var.set(f"Failed {index}/{total}: {chapter_title}")
                        if error:
                            self._append_log(f"Chapter failed: {chapter_title} | {error}")
                    elif progress_event == "batch_canceled":
                        completed = int(payload.get("completed", 0))
                        total_val = int(payload.get("total", 0))
                        self.status_var.set(f"Queue canceled. Completed {completed}/{total_val}.")
                    elif progress_event == "batch_complete":
                        downloaded = int(payload.get("downloaded", 0))
                        skipped = int(payload.get("skipped", 0))
                        failed = int(payload.get("failed", 0))
                        canceled = bool(payload.get("canceled", False))
                        end_state = "canceled" if canceled else "complete"
                        self.summary_var.set(
                            f"Queue {end_state}. New: {downloaded} | Skipped: {skipped} | Failed: {failed}"
                        )
            elif event_type == "result":
                result_payload = payload if isinstance(payload, dict) else {}
                self.current_payload = result_payload
                self._set_json_output(result_payload)
                image_urls = result_payload.get("image_urls")
                if isinstance(image_urls, list):
                    self._set_url_table([str(item) for item in image_urls])
                    parser_name = str(result_payload.get("parser", "unknown"))
                    title = str(result_payload.get("title", "untitled"))
                    summary_line = f"Parser: {parser_name} | Images: {len(image_urls)} | Title: {title}"
                    download_info = result_payload.get("download")
                    if isinstance(download_info, dict):
                        downloaded = int(download_info.get("downloaded", 0))
                        failed = int(download_info.get("failed", 0))
                        summary_line = f"{summary_line} | Saved: {downloaded} | Failed: {failed}"
                    self.summary_var.set(summary_line)
            elif event_type == "image_download_result":
                if isinstance(payload, dict):
                    if self.current_payload is None:
                        self.current_payload = {}
                    self.current_payload["download"] = payload
                    self._set_json_output(self.current_payload)
                    downloaded = int(payload.get("downloaded", 0))
                    failed = int(payload.get("failed", 0))
                    output_dir = str(payload.get("output_dir", ""))
                    self.summary_var.set(
                        f"Image download complete. Saved: {downloaded} | Failed: {failed} | Folder: {output_dir}"
                    )
            elif event_type == "chapter_download_result":
                if isinstance(payload, dict):
                    self.queue_active = False
                    self.queue_paused = False
                    self._queue_pause_event.set()
                    self._queue_cancel_event.clear()

                    series_root = payload.get("series_root", "")
                    results = payload.get("results", [])
                    downloaded_count = 0
                    skipped_count = 0
                    failed_count = 0
                    if isinstance(results, list):
                        for item in results:
                            if not isinstance(item, dict):
                                continue
                            status = str(item.get("status", ""))
                            if status == "downloaded":
                                downloaded_count += 1
                            elif status == "skipped":
                                skipped_count += 1
                            elif status == "failed":
                                failed_count += 1

                    failed_urls = payload.get("failed_urls", [])
                    if isinstance(failed_urls, list):
                        self.current_failed_chapter_urls = [str(url) for url in failed_urls if str(url).strip()]
                    else:
                        self.current_failed_chapter_urls = []
                    was_canceled = bool(payload.get("canceled", False))

                    # Reload history so "Downloaded" flags in chapter table stay in sync.
                    if self.current_series:
                        series_root_path = self._series_root_from_current()
                        if series_root_path:
                            self.current_series_history = load_history(series_root_path)
                            self._refresh_chapter_table()
                    self.summary_var.set(
                        "Queue done. "
                        f"New: {downloaded_count} | Skipped: {skipped_count} | Failed: {failed_count} "
                        f"| Canceled: {'Yes' if was_canceled else 'No'} | Root: {series_root}"
                    )
                    self._update_queue_control_states()
            elif event_type == "error":
                self.queue_active = False
                self.queue_paused = False
                self._queue_pause_event.set()
                self._queue_cancel_event.clear()
                messagebox.showerror("Operation failed", str(payload))
                self.summary_var.set("Operation failed.")
            elif event_type == "trace":
                self._append_log(str(payload))
            elif event_type == "done":
                self._set_busy(False)
                self._update_queue_control_states()

        self.root.after(100, self._process_events)


def launch_ui() -> None:
    ctk.set_default_color_theme("blue")
    ctk.set_appearance_mode("light")
    root = ctk.CTk()
    DownloaderUI(root)
    root.mainloop()


def main() -> int:
    launch_ui()
    return 0
