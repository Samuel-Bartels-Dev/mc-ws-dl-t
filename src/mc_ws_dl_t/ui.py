import json
import logging
import os
import queue
import threading
import time
import traceback
from decimal import Decimal
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, cast

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
from .gui.validation import (
    extract_chapter_number,
    normalize_directory,
    normalize_output_file,
    parse_non_negative_int,
    parse_optional_chapter_range,
    parse_positive_int,
    validate_http_url,
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
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("MC-WS-DL-T | Manga/Comic Downloader")
        self.root.geometry("1180x720")
        self.root.minsize(980, 680)

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
        self.chapter_start_var = tk.StringVar(value="")
        self.chapter_end_var = tk.StringVar(value="")
        self.overall_progress_var = tk.DoubleVar(value=0.0)
        self.chapter_progress_var = tk.DoubleVar(value=0.0)
        self.overall_progress_text_var = tk.StringVar(value="Overall progress: 0%")
        self.chapter_progress_text_var = tk.StringVar(value="Current chapter: idle")
        self._batch_total = 0
        self._json_tab_visible = True
        self._url_tab_visible = True

        self.log_file_var.set(str(self._build_default_log_file_path()))
        self._load_library_settings()
        self._ensure_default_library()

        self._configure_style()
        self._build_layout()
        self._build_menu()
        self._apply_theme(self.theme_var.get())
        self._update_queue_control_states()

        # Poll queued events so worker thread updates are applied on the UI thread.
        self.root.after(100, self._process_events)

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
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.style.configure("Title.TLabel", font=("Segoe UI Semibold", 14))
        self.style.configure("Primary.TButton", padding=(8, 3))
        self.style.configure("Slim.TButton", padding=(6, 2))

    def _on_theme_change(self) -> None:
        self._apply_theme(self.theme_var.get())

    def _apply_theme(self, mode: str) -> None:
        palettes: dict[str, dict[str, str]] = {
            "light": {
                "bg": "#edf1f5",
                "panel": "#f6f8fb",
                "surface": "#ffffff",
                "fg": "#1f2a37",
                "muted": "#5d6b7c",
                "border": "#cfd8e3",
                "accent": "#2563eb",
                "accent_hover": "#1f59d1",
                "accent_fg": "#ffffff",
                "text_bg": "#f8fafc",
                "text_fg": "#111827",
                "tree_bg": "#ffffff",
                "tree_fg": "#1f2937",
                "tree_sel_bg": "#2563eb",
                "tree_sel_fg": "#ffffff",
                "tree_heading_bg": "#e7edf4",
                "tree_heading_fg": "#1f2937",
                "log_bg": "#0f1724",
                "log_fg": "#dbe7f4",
            },
            "dark": {
                "bg": "#11151a",
                "panel": "#1a212b",
                "surface": "#242d38",
                "fg": "#e6edf3",
                "muted": "#9aa6b2",
                "border": "#323d4a",
                "accent": "#4f8cff",
                "accent_hover": "#6aa0ff",
                "accent_fg": "#ffffff",
                "text_bg": "#1c232d",
                "text_fg": "#e6edf3",
                "tree_bg": "#171e27",
                "tree_fg": "#e6edf3",
                "tree_sel_bg": "#4f8cff",
                "tree_sel_fg": "#ffffff",
                "tree_heading_bg": "#242d38",
                "tree_heading_fg": "#dbe5ee",
                "log_bg": "#121923",
                "log_fg": "#d7e3ef",
            },
        }
        palette = palettes["dark" if mode == "dark" else "light"]
        self._current_palette = palette
        flat_bg = palette["bg"]

        # Base widgets.
        self.root.configure(bg=flat_bg)
        self.style.configure("Card.TFrame", background=flat_bg)
        self.style.configure("TFrame", background=flat_bg)
        self.style.configure("TLabel", background=flat_bg, foreground=palette["fg"])
        self.style.configure("Hint.TLabel", background=flat_bg, foreground=palette["muted"])
        self.style.configure(
            "Panel.TLabelframe",
            background=flat_bg,
            bordercolor=flat_bg,
            borderwidth=0,
            relief="flat",
            lightcolor=flat_bg,
            darkcolor=flat_bg,
        )
        self.style.configure(
            "TLabelframe",
            background=flat_bg,
            bordercolor=flat_bg,
            borderwidth=0,
            relief="flat",
            lightcolor=flat_bg,
            darkcolor=flat_bg,
        )
        self.style.configure(
            "Panel.TLabelframe.Label",
            background=flat_bg,
            foreground=palette["fg"],
            font=("Segoe UI", 10, "bold"),
        )
        self.style.configure(
            "TLabelframe.Label",
            background=flat_bg,
            foreground=palette["fg"],
            font=("Segoe UI", 10, "bold"),
        )

        # Inputs and buttons.
        self.style.configure(
            "TEntry",
            fieldbackground=flat_bg,
            foreground=palette["text_fg"],
            bordercolor=flat_bg,
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=flat_bg,
            foreground=palette["text_fg"],
            background=flat_bg,
            bordercolor=flat_bg,
            arrowcolor=palette["fg"],
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", flat_bg)],
            foreground=[("readonly", palette["text_fg"])],
        )
        self.style.configure(
            "TSpinbox",
            fieldbackground=flat_bg,
            foreground=palette["text_fg"],
            background=flat_bg,
            bordercolor=flat_bg,
            arrowcolor=palette["fg"],
        )
        self.style.configure(
            "TButton",
            background=flat_bg,
            foreground=palette["fg"],
            bordercolor=flat_bg,
            focusthickness=1,
            focuscolor=palette["accent"],
        )
        self.style.map(
            "TButton",
            background=[("active", flat_bg)],
            foreground=[("disabled", palette["muted"])],
        )
        self.style.configure(
            "Primary.TButton",
            background=palette["accent"],
            foreground=palette["accent_fg"],
            bordercolor=palette["accent"],
            padding=(8, 3),
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", palette["accent_hover"]), ("disabled", palette["border"])],
            foreground=[("disabled", palette["muted"])],
        )
        self.style.configure("Slim.TButton", padding=(6, 2))
        self.style.configure("TCheckbutton", background=flat_bg, foreground=palette["fg"])

        # Notebook and tables.
        self.style.configure("TNotebook", background=flat_bg, borderwidth=0, tabmargins=(0, 0, 0, 0))
        self.style.configure(
            "TNotebook.Tab",
            background=flat_bg,
            foreground=palette["fg"],
            bordercolor=flat_bg,
            padding=(10, 5),
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", palette["accent"]), ("active", flat_bg)],
            foreground=[("selected", palette["accent_fg"])],
        )
        self.style.configure(
            "Treeview",
            background=flat_bg,
            foreground=palette["tree_fg"],
            fieldbackground=flat_bg,
            bordercolor=flat_bg,
            borderwidth=0,
            relief="flat",
            rowheight=22,
        )
        self.style.map(
            "Treeview",
            background=[("selected", palette["tree_sel_bg"])],
            foreground=[("selected", palette["tree_sel_fg"])],
        )
        self.style.configure(
            "Treeview.Heading",
            background=flat_bg,
            foreground=palette["tree_heading_fg"],
            bordercolor=flat_bg,
            relief="flat",
            font=("Segoe UI Semibold", 9),
        )
        self.style.map("Treeview.Heading", background=[("active", flat_bg)])
        self.style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=flat_bg,
            background=palette["accent"],
            bordercolor=flat_bg,
            lightcolor=palette["accent"],
            darkcolor=palette["accent"],
        )

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
            troughcolor=flat_bg,
            bordercolor=flat_bg,
            darkcolor=flat_bg,
            lightcolor=flat_bg,
            arrowcolor=flat_bg,
            arrowsize=0,
            gripcount=0,
            relief="flat",
            width=8,
        )
        self.style.configure(
            "Modern.Horizontal.TScrollbar",
            background=palette["border"],
            troughcolor=flat_bg,
            bordercolor=flat_bg,
            darkcolor=flat_bg,
            lightcolor=flat_bg,
            arrowcolor=flat_bg,
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

        # Text widgets (tk.Text via ScrolledText).
        for text_widget in (
            getattr(self, "log_text", None),
            getattr(self, "json_text", None),
            self._popup_log_text,
        ):
            if text_widget is not None and text_widget.winfo_exists():
                text_widget.configure(
                    background=flat_bg,
                    foreground=palette["text_fg"],
                    insertbackground=palette["text_fg"],
                    selectbackground=palette["accent"],
                    selectforeground=palette["accent_fg"],
                    borderwidth=0,
                    highlightthickness=0,
                    highlightbackground=flat_bg,
                )

        # Combobox dropdown list colors.
        self.root.option_add("*TCombobox*Listbox.background", flat_bg)
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
        self._configure_log_tags()

    def _configure_log_tags(self) -> None:
        palette = self._current_palette
        tag_colors = {
            "log_info": palette["log_fg"],
            "log_debug": "#38bdf8",
            "log_warning": "#f59e0b",
            "log_error": "#ef4444",
            "log_success": "#22c55e",
        }
        for widget in (getattr(self, "log_text", None), self._popup_log_text):
            if widget is None or not widget.winfo_exists():
                continue
            for tag_name, color in tag_colors.items():
                widget.tag_configure(tag_name, foreground=color)

    def _build_layout(self) -> None:
        self.root.configure(bg="#e9edf5")
        main = ttk.Frame(self.root, style="Card.TFrame", padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        control_box = ttk.Frame(main, style="Card.TFrame", padding=8)
        control_box.grid(row=0, column=0, sticky="ew")
        control_box.columnconfigure(1, weight=1)
        control_box.columnconfigure(2, weight=0)

        ttk.Label(control_box, text="Series URL").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        url_entry = ttk.Entry(control_box, textvariable=self.url_var)
        url_entry.grid(row=0, column=1, sticky="ew", pady=2)
        self.load_series_button = ttk.Button(
            control_box,
            text="Load",
            command=self._start_series_discovery,
            style="Primary.TButton",
            width=9,
        )
        self.load_series_button.grid(row=0, column=2, sticky="w", padx=(8, 0), pady=2)

        self.output_label = ttk.Label(control_box, text="Output JSON")
        self.output_label.grid(row=4, column=0, sticky="w", padx=(0, 8), pady=2)
        self.output_entry = ttk.Entry(control_box, textvariable=self.output_var)
        self.output_entry.grid(row=4, column=1, sticky="ew", pady=2)
        self.output_browse_button = ttk.Button(control_box, text="Browse", command=self._browse_output_file, style="Slim.TButton")
        self.output_browse_button.grid(row=4, column=2, sticky="w", padx=(8, 0), pady=2)

        ttk.Label(control_box, text="Image folder").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        self.image_dir_combo = ttk.Combobox(
            control_box,
            textvariable=self.image_dir_var,
            values=self.library_locations,
            state="normal",
        )
        self.image_dir_combo.grid(row=1, column=1, sticky="ew", pady=2)
        self.image_dir_combo.bind("<<ComboboxSelected>>", lambda _event: self._persist_current_library())
        self.image_dir_combo.bind("<FocusOut>", lambda _event: self._persist_current_library())
        self.image_dir_combo.bind("<Return>", lambda _event: self._persist_current_library())
        ttk.Button(control_box, text="Browse", command=self._browse_image_dir, style="Slim.TButton", width=9).grid(
            row=1, column=2, sticky="w", padx=(8, 0), pady=2
        )

        settings_row = ttk.Frame(control_box)
        settings_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 2))
        ttk.Label(settings_row, text="Parser").pack(side=tk.LEFT, padx=(0, 4))
        self.parser_combo = ttk.Combobox(
            settings_row,
            textvariable=self.parser_var,
            values=get_available_parser_names(),
            state="readonly",
            width=11,
        )
        self.parser_combo.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(settings_row, text="Browser").pack(side=tk.LEFT, padx=(0, 4))
        self.browser_combo = ttk.Combobox(
            settings_row,
            textvariable=self.browser_var,
            values=("chrome", "firefox"),
            state="readonly",
            width=11,
        )
        self.browser_combo.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(settings_row, text="Wait").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(settings_row, textvariable=self.wait_var, width=4).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(settings_row, text="Timeout").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(settings_row, textvariable=self.timeout_var, width=4).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(settings_row, text="Retries").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(settings_row, textvariable=self.retries_var, width=4).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Checkbutton(
            settings_row,
            text="Prefer dynamic first",
            variable=self.prefer_dynamic_var,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(
            settings_row,
            text="Auto-download",
            variable=self.auto_download_var,
        ).pack(side=tk.LEFT, padx=(0, 2))

        ttk.Label(settings_row, text="Logs").pack(side=tk.LEFT, padx=(10, 4))
        self.logs_path_hint = ttk.Label(
            settings_row,
            text="Auto-saved in ./logs (session file).",
            style="Hint.TLabel",
        )
        self.logs_path_hint.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(settings_row, text="Log level").pack(side=tk.LEFT, padx=(0, 4))
        self.level_combo = ttk.Combobox(
            settings_row,
            textvariable=self.log_level_var,
            values=("DEBUG", "INFO", "WARNING", "ERROR"),
            state="readonly",
            width=8,
        )
        self.level_combo.pack(side=tk.LEFT)

        self.debug_actions_frame = ttk.Frame(control_box)
        self.debug_actions_frame.grid(row=5, column=0, columnspan=3, sticky="e", pady=(2, 0))
        self.copy_json_button = ttk.Button(self.debug_actions_frame, text="Copy JSON", command=self._copy_json, style="Slim.TButton")
        self.copy_json_button.pack(side=tk.LEFT, padx=(0, 8))
        self.save_json_button = ttk.Button(self.debug_actions_frame, text="Save JSON As", command=self._save_json_as, style="Slim.TButton")
        self.save_json_button.pack(side=tk.LEFT)

        content_pane = ttk.Panedwindow(main, orient=tk.VERTICAL)
        content_pane.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

        result_frame = ttk.Frame(content_pane, style="Card.TFrame", padding=8)
        logs_frame = ttk.Frame(content_pane, style="Card.TFrame", padding=8)
        content_pane.add(result_frame, weight=3)
        content_pane.add(logs_frame, weight=2)

        self.result_tabs = ttk.Notebook(result_frame)
        self.result_tabs.pack(fill=tk.BOTH, expand=True)

        self.json_tab = ttk.Frame(self.result_tabs)
        self.json_tab.columnconfigure(0, weight=1)
        self.json_tab.rowconfigure(0, weight=1)
        self.json_text = tk.Text(
            self.json_tab,
            wrap=tk.NONE,
            font=("Consolas", 10),
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

        self.url_tab = ttk.Frame(self.result_tabs)
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

        chapter_tab = ttk.Frame(self.result_tabs)
        chapter_tab.columnconfigure(0, weight=1)
        chapter_tab.rowconfigure(2, weight=1)

        chapter_header = ttk.Frame(chapter_tab)
        chapter_header.grid(row=0, column=0, sticky="ew", padx=2, pady=(2, 6))
        chapter_header.columnconfigure(0, weight=1)

        series_meta = ttk.Label(chapter_header, textvariable=self.series_status_var, style="Hint.TLabel")
        series_meta.grid(row=0, column=0, sticky="w")

        ttk.Label(chapter_header, text="Filter").grid(row=0, column=1, sticky="e", padx=(8, 6))
        self.chapter_filter_combo = ttk.Combobox(
            chapter_header,
            textvariable=self.chapter_filter_var,
            values=("All chapters", "Downloaded only", "Not downloaded"),
            state="readonly",
            width=16,
        )
        self.chapter_filter_combo.grid(row=0, column=2, sticky="e")
        self.chapter_filter_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_chapter_table())

        chapter_btns = ttk.Frame(chapter_tab)
        chapter_btns.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        chapter_btns.columnconfigure(99, weight=1)

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

        ttk.Label(chapter_btns, text="Retry/chapter").grid(row=0, column=5, padx=(0, 6))
        self.retry_spin = ttk.Spinbox(
            chapter_btns,
            from_=0,
            to=10,
            textvariable=self.retry_per_chapter_var,
            width=4,
        )
        self.retry_spin.grid(row=0, column=6, padx=(0, 12))

        ttk.Label(chapter_btns, text="Range").grid(row=0, column=7, padx=(0, 6))
        self.chapter_start_entry = ttk.Entry(chapter_btns, textvariable=self.chapter_start_var, width=6)
        self.chapter_start_entry.grid(row=0, column=8, padx=(0, 4))
        ttk.Label(chapter_btns, text="to").grid(row=0, column=9, padx=(0, 4))
        self.chapter_end_entry = ttk.Entry(chapter_btns, textvariable=self.chapter_end_var, width=6)
        self.chapter_end_entry.grid(row=0, column=10, padx=(0, 12))

        ttk.Button(chapter_btns, text="Select All", command=self._select_all_chapters, style="Slim.TButton").grid(
            row=0, column=11, padx=(0, 8)
        )
        ttk.Button(chapter_btns, text="Clear Selection", command=self._clear_chapter_selection, style="Slim.TButton").grid(
            row=0, column=12, padx=(0, 4)
        )

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
        self.chapter_table.column("status", width=90, stretch=False, anchor=tk.CENTER)
        self.chapter_table.column("chapter", width=220, stretch=False, anchor=tk.W)
        self.chapter_table.column("release", width=150, stretch=False, anchor=tk.W)
        self.chapter_table.column("url", width=600, stretch=True, anchor=tk.W)

        # Keep chapter scrollbars slim and subtle.
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

        logs_toolbar = ttk.Frame(logs_frame)
        logs_toolbar.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(logs_toolbar, text="Session logs are auto-saved.", style="Hint.TLabel").pack(side=tk.LEFT)

        logs_body = ttk.Frame(logs_frame)
        logs_body.pack(fill=tk.BOTH, expand=True)
        logs_body.columnconfigure(0, weight=1)
        logs_body.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            logs_body,
            wrap=tk.WORD,
            font=("Consolas", 10),
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

        progress_footer = ttk.Frame(main, style="Card.TFrame", padding=(4, 2))
        progress_footer.grid(row=2, column=0, sticky="ew", padx=4, pady=(6, 0))
        progress_footer.columnconfigure(1, weight=1)
        progress_footer.columnconfigure(3, weight=1)

        ttk.Label(progress_footer, text="Overall", style="Hint.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.overall_progress = ttk.Progressbar(
            progress_footer,
            style="Accent.Horizontal.TProgressbar",
            orient=tk.HORIZONTAL,
            mode="determinate",
            maximum=100,
            variable=self.overall_progress_var,
        )
        self.overall_progress.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        ttk.Label(progress_footer, textvariable=self.overall_progress_text_var, style="Hint.TLabel").grid(
            row=0, column=2, sticky="w", padx=(0, 8)
        )

        self.chapter_progress = ttk.Progressbar(
            progress_footer,
            style="Accent.Horizontal.TProgressbar",
            orient=tk.HORIZONTAL,
            mode="determinate",
            maximum=100,
            variable=self.chapter_progress_var,
        )
        self.chapter_progress.grid(row=0, column=3, sticky="ew", padx=(0, 10))
        ttk.Label(progress_footer, textvariable=self.chapter_progress_text_var, style="Hint.TLabel").grid(
            row=0, column=4, sticky="w"
        )

        footer = ttk.Frame(main, style="Card.TFrame")
        footer.grid(row=3, column=0, sticky="ew", padx=4, pady=(4, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.summary_var, style="Hint.TLabel", anchor=tk.W).grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.status_var, style="Hint.TLabel", anchor=tk.E).grid(row=0, column=1, sticky="e")

        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        self._refresh_library_combo()
        self._toggle_debug_tools()

    def _toggle_debug_tools(self) -> None:
        # Keep JSON export features available, but hide them from the default operator flow.
        show_debug = self.show_debug_var.get()

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
            font=("Consolas", 10),
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
        tag_name = self._resolve_log_tag(line)
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{line}\n", tag_name)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        if self._popup_log_text and self._popup_log_text.winfo_exists():
            self._popup_log_text.configure(state=tk.NORMAL)
            self._popup_log_text.insert(tk.END, f"{line}\n", tag_name)
            self._popup_log_text.see(tk.END)
            self._popup_log_text.configure(state=tk.DISABLED)

    def _resolve_log_tag(self, line: str) -> str:
        upper_line = line.upper()
        if "[ERROR]" in upper_line:
            return "log_error"
        if "[WARNING]" in upper_line or "[WARN]" in upper_line:
            return "log_warning"
        if "[DEBUG]" in upper_line:
            return "log_debug"
        if "[SUCCESS]" in upper_line:
            return "log_success"
        return "log_info"

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
            self.url_table.insert("", tk.END, values=(index, image_url))

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
            self.chapter_start_entry.configure(state=tk.DISABLED)
            self.chapter_end_entry.configure(state=tk.DISABLED)
        else:
            self.pause_queue_button.configure(state=tk.DISABLED)
            self.resume_queue_button.configure(state=tk.DISABLED)
            self.cancel_queue_button.configure(state=tk.DISABLED)
            self.retry_spin.configure(state=tk.NORMAL if not self.is_running else tk.DISABLED)
            range_entry_state = tk.NORMAL if not self.is_running else tk.DISABLED
            self.chapter_start_entry.configure(state=range_entry_state)
            self.chapter_end_entry.configure(state=range_entry_state)
            can_retry_failed = bool(self.current_failed_chapter_urls) and not self.is_running
            self.retry_failed_button.configure(state=tk.NORMAL if can_retry_failed else tk.DISABLED)

    def _parse_positive_int(self, raw_value: str, field_name: str) -> int:
        return parse_positive_int(raw_value, field_name)

    def _parse_non_negative_int(self, raw_value: str, field_name: str) -> int:
        return parse_non_negative_int(raw_value, field_name)

    def _build_options_from_form(self) -> DownloadOptions:
        url = validate_http_url(self.url_var.get(), field_name="URL")

        timeout_seconds = self._parse_positive_int(self.timeout_var.get(), "Timeout")
        wait_seconds = self._parse_positive_int(self.wait_var.get(), "Wait")
        retries = self._parse_positive_int(self.retries_var.get(), "Retries")

        output = normalize_output_file(self.output_var.get())
        image_dir_path = self.image_dir_var.get().strip()

        image_download_dir: Path | None = None
        if self.auto_download_var.get():
            image_download_dir = normalize_directory(image_dir_path, "Image folder")

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
        self._reset_progress_indicators()
        self._set_overall_progress(completed=0, total=1)
        self._set_chapter_progress(percent=15.0, title="Fetching chapter")
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

    def _select_chapters_by_range(
        self,
        range_start: Decimal | None,
        range_end: Decimal | None,
    ) -> list[SeriesChapter]:
        matched: list[SeriesChapter] = []
        for chapter in self.current_series_chapters:
            chapter_number = extract_chapter_number(chapter.chapter_key, chapter.title)
            if chapter_number is None:
                continue
            if range_start is not None and chapter_number < range_start:
                continue
            if range_end is not None and chapter_number > range_end:
                continue
            matched.append(chapter)
        return matched

    def _reset_progress_indicators(self) -> None:
        self._batch_total = 0
        self.overall_progress_var.set(0.0)
        self.chapter_progress_var.set(0.0)
        self.overall_progress_text_var.set("Overall progress: 0%")
        self.chapter_progress_text_var.set("Current chapter: idle")

    def _set_overall_progress(self, completed: int, total: int) -> None:
        safe_total = total if total > 0 else 1
        ratio = min(100.0, (completed / safe_total) * 100.0)
        self.overall_progress_var.set(ratio)
        self.overall_progress_text_var.set(f"Overall progress: {int(ratio)}% ({completed}/{total})")

    def _set_chapter_progress(self, percent: float, title: str) -> None:
        bounded = max(0.0, min(100.0, percent))
        self.chapter_progress_var.set(bounded)
        self.chapter_progress_text_var.set(f"Current chapter: {title} ({int(bounded)}%)")

    def _start_series_discovery(self) -> None:
        if self.is_running:
            return

        try:
            series_url = validate_http_url(self.url_var.get(), field_name="Series URL")
            config = self._build_runtime_config()
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        self._set_busy(True)
        self._reset_progress_indicators()
        self._set_overall_progress(completed=0, total=1)
        self._set_chapter_progress(percent=15.0, title="Loading series metadata")
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

        base_path_raw = self.image_dir_var.get().strip()

        try:
            config = self._build_runtime_config()
            retry_per_chapter = self._parse_non_negative_int(self.retry_per_chapter_var.get(), "Retry/chapter")
            base_directory = normalize_directory(base_path_raw, "Image folder")
            range_start, range_end = parse_optional_chapter_range(
                self.chapter_start_var.get(),
                self.chapter_end_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        selected_urls = {
            str(self.chapter_table.item(item, "values")[3])
            for item in selected_items
            if self.chapter_table.item(item, "values")
        }
        selected_chapters = [chapter for chapter in self.current_series_chapters if chapter.url in selected_urls]

        if range_start is not None or range_end is not None:
            selected_chapters = self._select_chapters_by_range(range_start=range_start, range_end=range_end)

        if not selected_chapters:
            if range_start is not None or range_end is not None:
                messagebox.showinfo("No chapters", "No chapters matched the chapter range.")
            else:
                messagebox.showinfo("No selection", "Select one or more chapters first.")
            return

        self._reset_progress_indicators()
        self._start_chapter_queue(
            selected_chapters=selected_chapters,
            base_dir=base_directory,
            config=config,
            retry_per_chapter=retry_per_chapter,
            queue_label=f"{len(selected_chapters)} chapter(s)",
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
        self._batch_total = len(selected_chapters)
        self._set_overall_progress(completed=0, total=self._batch_total)
        self._set_chapter_progress(percent=0.0, title="Queue started")
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

        try:
            config = self._build_runtime_config()
            retry_per_chapter = self._parse_non_negative_int(self.retry_per_chapter_var.get(), "Retry/chapter")
            base_directory = normalize_directory(base_path_raw, "Image folder")
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
            base_dir=base_directory,
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

        try:
            config = self._build_runtime_config()
            target_dir = normalize_directory(image_dir_path, "Image folder")
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        self._set_busy(True)
        self._reset_progress_indicators()
        self._set_overall_progress(completed=0, total=1)
        self._set_chapter_progress(percent=20.0, title="Downloading image files")
        self.status_var.set("Downloading images...")
        self.summary_var.set("Image download in progress...")
        self._append_log("----- Image download started from current payload -----")

        payload_copy = dict(self.current_payload)
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
                    self._set_overall_progress(completed=1, total=1)
                    self._set_chapter_progress(percent=100.0, title="Series metadata loaded")
                    self._update_queue_control_states()
            elif event_type == "chapter_progress":
                if isinstance(payload, dict):
                    progress_event = str(payload.get("event", ""))
                    chapter_title = str(payload.get("title", "")).strip()
                    index = int(payload.get("index", 0)) if str(payload.get("index", "")).isdigit() else 0
                    total = int(payload.get("total", 0)) if str(payload.get("total", "")).isdigit() else 0

                    if progress_event == "batch_start":
                        total_val = int(payload.get("total", 0))
                        self._batch_total = total_val
                        self._set_overall_progress(completed=0, total=total_val)
                        self._set_chapter_progress(percent=0.0, title="Waiting for chapter")
                        self.status_var.set(f"Queue started. Chapters: {total_val}")
                        self.summary_var.set(f"Queue running. Total chapters: {total_val}")
                    elif progress_event == "chapter_start":
                        self._set_chapter_progress(percent=20.0, title=chapter_title or "Chapter")
                        self._set_overall_progress(completed=max(index - 1, 0), total=total or self._batch_total)
                        self.status_var.set(f"Chapter {index}/{total}: {chapter_title}")
                    elif progress_event == "chapter_retry":
                        self._set_chapter_progress(percent=45.0, title=chapter_title or "Retrying chapter")
                        next_attempt = int(payload.get("next_attempt", 0))
                        self._append_log(
                            f"Retry scheduled for chapter {index}/{total}: {chapter_title} (attempt {next_attempt})"
                        )
                    elif progress_event == "chapter_downloaded":
                        self._set_chapter_progress(percent=100.0, title=chapter_title or "Downloaded")
                        self._set_overall_progress(completed=index, total=total or self._batch_total)
                        self.status_var.set(f"Downloaded {index}/{total}: {chapter_title}")
                    elif progress_event == "chapter_skipped":
                        self._set_chapter_progress(percent=100.0, title=chapter_title or "Skipped")
                        self._set_overall_progress(completed=index, total=total or self._batch_total)
                        self.status_var.set(f"Skipped {index}/{total}: {chapter_title} (already downloaded)")
                    elif progress_event == "chapter_failed":
                        self._set_chapter_progress(percent=100.0, title=chapter_title or "Failed")
                        self._set_overall_progress(completed=index, total=total or self._batch_total)
                        error = str(payload.get("error", ""))
                        self.status_var.set(f"Failed {index}/{total}: {chapter_title}")
                        if error:
                            self._append_log(f"Chapter failed: {chapter_title} | {error}")
                    elif progress_event == "batch_canceled":
                        completed = int(payload.get("completed", 0))
                        total_val = int(payload.get("total", 0))
                        self._set_overall_progress(completed=completed, total=total_val)
                        self._set_chapter_progress(percent=0.0, title="Canceled")
                        self.status_var.set(f"Queue canceled. Completed {completed}/{total_val}.")
                    elif progress_event == "batch_complete":
                        downloaded = int(payload.get("downloaded", 0))
                        skipped = int(payload.get("skipped", 0))
                        failed = int(payload.get("failed", 0))
                        canceled = bool(payload.get("canceled", False))
                        self._set_overall_progress(completed=total, total=total or self._batch_total)
                        self._set_chapter_progress(percent=100.0, title="Queue finished")
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
                self._set_overall_progress(completed=1, total=1)
                self._set_chapter_progress(percent=100.0, title="Chapter parse complete")
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
                    self._set_overall_progress(completed=1, total=1)
                    self._set_chapter_progress(percent=100.0, title="Image download complete")
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
                    total_complete = downloaded_count + skipped_count + failed_count
                    self._set_overall_progress(
                        completed=total_complete,
                        total=max(total_complete, self._batch_total),
                    )
                    self._set_chapter_progress(percent=100.0, title="Queue complete")
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
    root = tk.Tk()
    DownloaderUI(root)
    root.mainloop()


def main() -> int:
    launch_ui()
    return 0
