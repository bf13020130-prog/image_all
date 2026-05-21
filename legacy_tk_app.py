#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import queue
import threading
from datetime import datetime
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from pipeline_core import *  # noqa: F403 - legacy UI relies on the old app.py namespace.

class GeneratorApp:
    def __init__(self, root: tk.Tk, context: AppContext) -> None:
        self.root = root
        self.context = context
        self.context.ensure_layout()
        self.settings = self.context.load_settings()
        self.ui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.logger = AppLogger(
            self.context.app_log_path,
            ui_callback=lambda line: self.ui_queue.put(("log", line)),
        )
        self.worker_thread: threading.Thread | None = None
        self.latest_run_record: dict[str, Any] | None = None

        self.root.title(APP_TITLE)
        self.root.geometry("1180x860")
        self.root.minsize(1020, 760)

        self.prompt_count_var = tk.StringVar(value=str(self.settings.default_prompt_count))
        self.aspect_ratio_var = tk.StringVar(value=self.settings.default_aspect_ratio)
        self.style_file_var = tk.StringVar(value="")
        self.style_url_var = tk.StringVar(value="")
        self.product_file_var = tk.StringVar(value="")
        self.product_url_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="空闲")
        self.settings_status_var = tk.StringVar(value="设置自动保存已开启")
        self._settings_autosave_job: str | None = None
        self._settings_autosave_suspended = False
        self._settings_trace_tokens: list[str] = []
        self.settings_text_widgets: dict[str, ScrolledText] = {}

        self.settings_vars = {
            "llm_api_base": tk.StringVar(value=self.settings.llm_api_base),
            "llm_api_key": tk.StringVar(value=self.settings.llm_api_key),
            "chat_model": tk.StringVar(value=self.settings.chat_model),
            "color_match_model": tk.StringVar(value=self.settings.color_match_model),
            "reasoning_effort": tk.StringVar(value=self.settings.reasoning_effort),
            "reasoning_wire_format": tk.StringVar(
                value=self.settings.reasoning_wire_format
            ),
            "llm_connect_timeout_seconds": tk.StringVar(
                value=str(self.settings.llm_connect_timeout_seconds)
            ),
            "chat_read_timeout_seconds": tk.StringVar(
                value=str(self.settings.chat_read_timeout_seconds)
            ),
            "llm_retry_count": tk.StringVar(value=str(self.settings.llm_retry_count)),
            "image_api_base": tk.StringVar(value=self.settings.image_api_base),
            "image_api_key": tk.StringVar(value=self.settings.image_api_key),
            "image_model": tk.StringVar(value=self.settings.image_model),
            "image_connect_timeout_seconds": tk.StringVar(
                value=str(self.settings.image_connect_timeout_seconds)
            ),
            "image_read_timeout_seconds": tk.StringVar(
                value=str(self.settings.image_read_timeout_seconds)
            ),
            "download_read_timeout_seconds": tk.StringVar(
                value=str(self.settings.download_read_timeout_seconds)
            ),
            "image_retry_count": tk.StringVar(value=str(self.settings.image_retry_count)),
            "chat_max_tokens": tk.StringVar(value=str(self.settings.chat_max_tokens)),
            "default_prompt_count": tk.StringVar(
                value=str(self.settings.default_prompt_count)
            ),
            "default_aspect_ratio": tk.StringVar(
                value=self.settings.default_aspect_ratio
            ),
            "default_images_per_prompt": tk.StringVar(
                value=str(self.settings.default_images_per_prompt)
            ),
            "default_concurrency": tk.StringVar(
                value=str(self.settings.default_concurrency)
            ),
        }

        self._configure_style()
        self._build_ui()
        self._setup_settings_autosave()
        self._load_log_file()
        self.refresh_history()
        self.poll_queue()
        self.logger.log("应用已启动")

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 11, "bold"))

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(self.root)
        notebook.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        self.task_tab = ttk.Frame(notebook)
        self.settings_tab = ttk.Frame(notebook)
        self.history_tab = ttk.Frame(notebook)
        self.logs_tab = ttk.Frame(notebook)

        notebook.add(self.task_tab, text="生成任务")
        notebook.add(self.settings_tab, text="设置")
        notebook.add(self.history_tab, text="历史")
        notebook.add(self.logs_tab, text="日志")

        self._build_task_tab()
        self._build_settings_tab()
        self._build_history_tab()
        self._build_logs_tab()

    def _build_task_tab(self) -> None:
        self.task_tab.columnconfigure(0, weight=1)
        self.task_tab.rowconfigure(4, weight=1)

        basic_frame = ttk.LabelFrame(self.task_tab, text="基础参数")
        basic_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        for column in range(4):
            basic_frame.columnconfigure(column, weight=1)

        ttk.Label(basic_frame, text="提示词数").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Spinbox(
            basic_frame,
            from_=1,
            to=50,
            textvariable=self.prompt_count_var,
            width=8,
        ).grid(row=0, column=1, sticky="ew", padx=6, pady=6)

        ttk.Label(basic_frame, text="比例").grid(row=0, column=2, sticky="w", padx=6, pady=6)
        ttk.Combobox(
            basic_frame,
            textvariable=self.aspect_ratio_var,
            values=SUPPORTED_OUTPUT_PRESETS,
            state="readonly",
        ).grid(row=0, column=3, sticky="ew", padx=6, pady=6)

        ttk.Label(
            basic_frame,
            text="任务结果会固定保存到 data/image/时间戳，下层分为 json 和 images 两个目录。",
        ).grid(row=1, column=0, columnspan=4, sticky="w", padx=6, pady=6)

        refs_frame = ttk.Frame(self.task_tab)
        refs_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        refs_frame.columnconfigure(0, weight=1)
        refs_frame.columnconfigure(1, weight=1)

        self._build_reference_panel(
            refs_frame,
            title="风格图",
            file_var=self.style_file_var,
            url_var=self.style_url_var,
            column=0,
        )
        self._build_reference_panel(
            refs_frame,
            title="产品图",
            file_var=self.product_file_var,
            url_var=self.product_url_var,
            column=1,
        )

        prompt_frame = ttk.LabelFrame(self.task_tab, text="用户提示词")
        prompt_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        prompt_frame.columnconfigure(0, weight=1)
        prompt_frame.rowconfigure(0, weight=1)
        self.task_user_prompt_text = ScrolledText(prompt_frame, height=10, wrap="word")
        self.task_user_prompt_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        action_frame = ttk.Frame(self.task_tab)
        action_frame.grid(row=3, column=0, sticky="ew", padx=8, pady=4)
        action_frame.columnconfigure(5, weight=1)

        self.start_button = ttk.Button(
            action_frame,
            text="开始生成",
            command=self.start_generation,
        )
        self.start_button.grid(row=0, column=0, padx=4, pady=4)

        ttk.Button(
            action_frame,
            text="打开 data 目录",
            command=lambda: self.try_open_path(self.context.data_dir),
        ).grid(row=0, column=1, padx=4, pady=4)

        ttk.Button(
            action_frame,
            text="打开最新结果",
            command=self.open_latest_run,
        ).grid(row=0, column=2, padx=4, pady=4)

        ttk.Button(
            action_frame,
            text="导出最新 ZIP",
            command=self.export_latest_zip,
        ).grid(row=0, column=3, padx=4, pady=4)

        ttk.Label(action_frame, textvariable=self.status_var).grid(
            row=0, column=4, sticky="w", padx=10, pady=4
        )

        self.progress = ttk.Progressbar(action_frame, mode="indeterminate")
        self.progress.grid(row=0, column=5, sticky="ew", padx=4, pady=4)

        result_frame = ttk.LabelFrame(self.task_tab, text="结果")
        result_frame.grid(row=4, column=0, sticky="nsew", padx=8, pady=8)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        self.result_text = ScrolledText(result_frame, wrap="word")
        self.result_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.result_text.insert(
            "1.0",
            "这里会显示本次任务的结果摘要、输出目录和图片路径。\n",
        )
        self.result_text.configure(state="disabled")

    def _build_reference_panel(
        self,
        parent: ttk.Frame,
        *,
        title: str,
        file_var: tk.StringVar,
        url_var: tk.StringVar,
        column: int,
    ) -> None:
        panel = ttk.LabelFrame(parent, text=title)
        panel.grid(row=0, column=column, sticky="nsew", padx=4, pady=4)
        panel.columnconfigure(1, weight=1)

        ttk.Label(panel, text="本地文件").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(panel, textvariable=file_var).grid(
            row=0, column=1, sticky="ew", padx=6, pady=6
        )
        ttk.Button(
            panel,
            text="浏览",
            command=lambda: self.choose_image(file_var),
        ).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(panel, text="图片链接").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(panel, textvariable=url_var).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=6, pady=6
        )

        ttk.Label(
            panel,
            text="本地文件和链接二选一即可；若两者都填，优先用本地文件。",
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=6)

    def _build_settings_tab(self) -> None:
        self.settings_tab.columnconfigure(0, weight=1)
        self.settings_tab.rowconfigure(4, weight=1)

        llm_frame = ttk.LabelFrame(self.settings_tab, text="大模型请求设置")
        llm_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        for column in range(4):
            llm_frame.columnconfigure(column, weight=1)

        self._labeled_entry(
            llm_frame,
            "API Base",
            self.settings_vars["llm_api_base"],
            0,
            0,
        )
        self._labeled_entry(
            llm_frame,
            "API Key",
            self.settings_vars["llm_api_key"],
            0,
            2,
            show="*",
        )
        self._labeled_entry(
            llm_frame,
            "Prompt Model",
            self.settings_vars["chat_model"],
            1,
            0,
        )
        self._labeled_entry(
            llm_frame,
            "连接超时(s)",
            self.settings_vars["llm_connect_timeout_seconds"],
            1,
            2,
        )

        ttk.Label(llm_frame, text="Reasoning Effort").grid(
            row=2, column=0, sticky="w", padx=6, pady=6
        )
        ttk.Combobox(
            llm_frame,
            textvariable=self.settings_vars["reasoning_effort"],
            values=("none", "low", "medium", "high", "xhigh"),
            state="readonly",
        ).grid(row=2, column=1, sticky="ew", padx=6, pady=6)

        ttk.Label(llm_frame, text="Reasoning 格式").grid(
            row=2, column=2, sticky="w", padx=6, pady=6
        )
        ttk.Combobox(
            llm_frame,
            textvariable=self.settings_vars["reasoning_wire_format"],
            values=("reasoning_effort", "reasoning"),
            state="readonly",
        ).grid(row=2, column=3, sticky="ew", padx=6, pady=6)

        self._labeled_entry(
            llm_frame,
            "提示词读超时(s)",
            self.settings_vars["chat_read_timeout_seconds"],
            3,
            0,
        )
        self._labeled_entry(
            llm_frame,
            "重试次数",
            self.settings_vars["llm_retry_count"],
            3,
            2,
        )
        self._labeled_entry(
            llm_frame,
            "Chat Max Tokens(0=自动)",
            self.settings_vars["chat_max_tokens"],
            4,
            0,
        )
        self._labeled_entry(
            llm_frame,
            "追色大模型 ID",
            self.settings_vars["color_match_model"],
            4,
            2,
        )

        image_frame = ttk.LabelFrame(self.settings_tab, text="生图请求设置")
        image_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        for column in range(4):
            image_frame.columnconfigure(column, weight=1)

        self._labeled_entry(
            image_frame,
            "API Base",
            self.settings_vars["image_api_base"],
            0,
            0,
        )
        self._labeled_entry(
            image_frame,
            "API Key",
            self.settings_vars["image_api_key"],
            0,
            2,
            show="*",
        )
        self._labeled_entry(
            image_frame,
            "Image Model",
            self.settings_vars["image_model"],
            1,
            0,
        )
        self._labeled_entry(
            image_frame,
            "连接超时(s)",
            self.settings_vars["image_connect_timeout_seconds"],
            1,
            2,
        )
        self._labeled_entry(
            image_frame,
            "生图读超时(s)",
            self.settings_vars["image_read_timeout_seconds"],
            2,
            0,
        )
        self._labeled_entry(
            image_frame,
            "下载读超时(s)",
            self.settings_vars["download_read_timeout_seconds"],
            2,
            2,
        )
        self._labeled_entry(
            image_frame,
            "重试次数",
            self.settings_vars["image_retry_count"],
            3,
            0,
        )

        defaults_frame = ttk.LabelFrame(self.settings_tab, text="默认任务参数")
        defaults_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        for column in range(4):
            defaults_frame.columnconfigure(column, weight=1)

        self._labeled_entry(
            defaults_frame,
            "默认提示词数",
            self.settings_vars["default_prompt_count"],
            0,
            0,
        )
        ttk.Label(defaults_frame, text="默认比例").grid(
            row=0, column=2, sticky="w", padx=6, pady=6
        )
        ttk.Combobox(
            defaults_frame,
            textvariable=self.settings_vars["default_aspect_ratio"],
            values=SUPPORTED_OUTPUT_PRESETS,
            state="readonly",
        ).grid(row=0, column=3, sticky="ew", padx=6, pady=6)
        self._labeled_entry(
            defaults_frame,
            "默认每条提示词出图数",
            self.settings_vars["default_images_per_prompt"],
            1,
            0,
        )
        self._labeled_entry(
            defaults_frame,
            "默认并发",
            self.settings_vars["default_concurrency"],
            1,
            2,
        )

        prompt_frame = ttk.LabelFrame(self.settings_tab, text="系统提示词")
        prompt_frame.grid(row=4, column=0, sticky="nsew", padx=8, pady=4)
        prompt_frame.columnconfigure(0, weight=1)
        prompt_frame.rowconfigure(0, weight=1)
        self.system_prompt_text = ScrolledText(prompt_frame, height=18, wrap="word")
        self.system_prompt_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self._set_text_widget(self.system_prompt_text, self.settings.system_prompt)
        self.settings_text_widgets["system_prompt"] = self.system_prompt_text

        button_frame = ttk.Frame(self.settings_tab)
        button_frame.grid(row=5, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(
            button_frame,
            text="立即保存一次",
            command=lambda: self.save_settings(show_message=True),
        ).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(
            button_frame,
            text="恢复默认",
            command=self.restore_default_settings,
        ).grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(
            button_frame,
            textvariable=self.settings_status_var,
        ).grid(row=0, column=2, sticky="w", padx=8, pady=4)

    def _build_history_tab(self) -> None:
        self.history_tab.columnconfigure(0, weight=1)
        self.history_tab.rowconfigure(1, weight=1)
        self.history_tab.rowconfigure(2, weight=1)

        action_frame = ttk.Frame(self.history_tab)
        action_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(action_frame, text="刷新历史", command=self.refresh_history).grid(
            row=0, column=0, padx=4, pady=4
        )
        ttk.Button(action_frame, text="打开选中目录", command=self.open_selected_history).grid(
            row=0, column=1, padx=4, pady=4
        )
        ttk.Button(action_frame, text="导出选中 ZIP", command=self.export_selected_zip).grid(
            row=0, column=2, padx=4, pady=4
        )

        columns = ("created_at", "project_name", "status", "prompt_count", "aspect_ratio")
        self.history_tree = ttk.Treeview(
            self.history_tab,
            columns=columns,
            show="headings",
            height=14,
        )
        self.history_tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self.history_tree.heading("created_at", text="时间")
        self.history_tree.heading("project_name", text="项目")
        self.history_tree.heading("status", text="状态")
        self.history_tree.heading("prompt_count", text="提示词")
        self.history_tree.heading("aspect_ratio", text="比例")
        self.history_tree.column("created_at", width=180, anchor="w")
        self.history_tree.column("project_name", width=260, anchor="w")
        self.history_tree.column("status", width=100, anchor="center")
        self.history_tree.column("prompt_count", width=90, anchor="center")
        self.history_tree.column("aspect_ratio", width=90, anchor="center")
        self.history_tree.bind("<<TreeviewSelect>>", self.on_history_select)

        self.history_detail = ScrolledText(self.history_tab, wrap="word")
        self.history_detail.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)

    def _build_logs_tab(self) -> None:
        self.logs_tab.columnconfigure(0, weight=1)
        self.logs_tab.rowconfigure(1, weight=1)

        action_frame = ttk.Frame(self.logs_tab)
        action_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(action_frame, text="刷新日志", command=self._load_log_file).grid(
            row=0, column=0, padx=4, pady=4
        )
        ttk.Button(
            action_frame,
            text="打开日志目录",
            command=lambda: self.try_open_path(self.context.logs_dir),
        ).grid(row=0, column=1, padx=4, pady=4)

        self.log_text = ScrolledText(self.logs_tab, wrap="word")
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

    def _labeled_entry(
        self,
        parent: ttk.LabelFrame | ttk.Frame,
        label: str,
        variable: tk.StringVar,
        row: int,
        column: int,
        *,
        show: str | None = None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=6, pady=6)
        ttk.Entry(parent, textvariable=variable, show=show).grid(
            row=row,
            column=column + 1,
            sticky="ew",
            padx=6,
            pady=6,
        )

    def choose_image(self, variable: tk.StringVar) -> None:
        file_path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[
                ("Image Files", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"),
                ("All Files", "*.*"),
            ],
        )
        if file_path:
            variable.set(file_path)

    def _read_text_widget(self, widget: ScrolledText) -> str:
        return widget.get("1.0", "end").rstrip("\n")

    def _set_text_widget(self, widget: ScrolledText, value: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.edit_modified(False)

    def _setup_settings_autosave(self) -> None:
        for variable in self.settings_vars.values():
            token = variable.trace_add("write", self.on_settings_var_changed)
            self._settings_trace_tokens.append(token)
        for widget in self.settings_text_widgets.values():
            widget.edit_modified(False)
            widget.bind("<<Modified>>", self.on_settings_text_modified)

    def _set_settings_vars(self, settings: Settings) -> None:
        self._settings_autosave_suspended = True
        try:
            for key, value in settings.to_dict().items():
                if key in self.settings_vars:
                    self.settings_vars[key].set(str(value))
            if "system_prompt" in self.settings_text_widgets:
                self._set_text_widget(
                    self.settings_text_widgets["system_prompt"],
                    settings.system_prompt,
                )
        finally:
            self._settings_autosave_suspended = False

    def on_settings_var_changed(self, *_args: Any) -> None:
        if self._settings_autosave_suspended:
            return
        self.settings_status_var.set("检测到变更，正在自动保存...")
        self.schedule_settings_autosave()

    def on_settings_text_modified(self, event: Any) -> None:
        widget = event.widget
        if not isinstance(widget, tk.Text):
            return
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        if self._settings_autosave_suspended:
            return
        self.settings_status_var.set("检测到变更，正在自动保存...")
        self.schedule_settings_autosave()

    def schedule_settings_autosave(
        self,
        delay_ms: int = SETTINGS_AUTOSAVE_DELAY_MS,
    ) -> None:
        if self._settings_autosave_job is not None:
            self.root.after_cancel(self._settings_autosave_job)
        self._settings_autosave_job = self.root.after(
            delay_ms,
            self.autosave_settings,
        )

    def autosave_settings(self) -> None:
        self._settings_autosave_job = None
        self.save_settings(show_message=False, mode="auto")

    def collect_settings(self) -> Settings:
        return Settings.from_dict(
            {
                "llm_api_base": self.settings_vars["llm_api_base"].get().strip()
                or DEFAULT_API_BASE,
                "llm_api_key": self.settings_vars["llm_api_key"].get().strip(),
                "chat_model": self.settings_vars["chat_model"].get().strip() or DEFAULT_CHAT_MODEL,
                "color_match_model": self.settings_vars["color_match_model"].get().strip()
                or DEFAULT_COLOR_MATCH_MODEL,
                "system_prompt": self._read_text_widget(self.system_prompt_text).strip()
                or SYSTEM_PROMPT,
                "reasoning_effort": self.settings_vars["reasoning_effort"].get().strip()
                or DEFAULT_REASONING_EFFORT,
                "reasoning_wire_format": self.settings_vars["reasoning_wire_format"].get().strip()
                or DEFAULT_REASONING_WIRE_FORMAT,
                "llm_connect_timeout_seconds": positive_int(
                    self.settings_vars["llm_connect_timeout_seconds"].get(),
                    "大模型连接超时",
                ),
                "chat_read_timeout_seconds": nonnegative_int(
                    self.settings_vars["chat_read_timeout_seconds"].get(),
                    "提示词读超时",
                ),
                "llm_retry_count": nonnegative_int(
                    self.settings_vars["llm_retry_count"].get(),
                    "大模型重试次数",
                ),
                "image_api_base": self.settings_vars["image_api_base"].get().strip()
                or DEFAULT_API_BASE,
                "image_api_key": self.settings_vars["image_api_key"].get().strip(),
                "image_model": self.settings_vars["image_model"].get().strip()
                or DEFAULT_IMAGE_MODEL,
                "image_connect_timeout_seconds": positive_int(
                    self.settings_vars["image_connect_timeout_seconds"].get(),
                    "生图连接超时",
                ),
                "image_read_timeout_seconds": nonnegative_int(
                    self.settings_vars["image_read_timeout_seconds"].get(),
                    "生图读超时",
                ),
                "download_read_timeout_seconds": nonnegative_int(
                    self.settings_vars["download_read_timeout_seconds"].get(),
                    "下载读超时",
                ),
                "image_retry_count": nonnegative_int(
                    self.settings_vars["image_retry_count"].get(),
                    "生图重试次数",
                ),
                "chat_max_tokens": nonnegative_int(
                    self.settings_vars["chat_max_tokens"].get(),
                    "Chat Max Tokens",
                ),
                "default_prompt_count": positive_int(
                    self.settings_vars["default_prompt_count"].get(),
                    "默认提示词数",
                ),
                "default_aspect_ratio": self.settings_vars["default_aspect_ratio"].get().strip()
                or DEFAULT_ASPECT_RATIO,
                "default_images_per_prompt": positive_int(
                    self.settings_vars["default_images_per_prompt"].get(),
                    "默认每条提示词出图数",
                ),
                "default_concurrency": positive_int(
                    self.settings_vars["default_concurrency"].get(),
                    "默认并发",
                ),
            }
        )

    def save_settings(self, *, show_message: bool, mode: str = "manual") -> bool:
        try:
            settings = self.collect_settings()
            settings.default_aspect_ratio = normalize_output_preset(
                settings.default_aspect_ratio
            )
            if settings.default_aspect_ratio not in SUPPORTED_OUTPUT_PRESETS:
                raise AppError("默认比例不在支持范围内。")
            if settings.default_concurrency > MAX_IMAGE_CONCURRENCY:
                raise AppError(f"默认并发不能超过 {MAX_IMAGE_CONCURRENCY}。")
            self.context.save_settings(settings)
            self.settings = settings
            save_time = datetime.now().strftime("%H:%M:%S")
            if mode == "auto":
                self.settings_status_var.set(f"已自动保存到 config.json  {save_time}")
                self.logger.log("设置已自动保存到 config.json")
            else:
                self.settings_status_var.set(f"已手动保存到 config.json  {save_time}")
                self.logger.log("设置已保存到 config.json")
            if show_message:
                messagebox.showinfo("保存成功", "设置已保存。")
            return True
        except Exception as exc:
            self.settings_status_var.set(f"当前内容未保存：{exc}")
            if show_message:
                messagebox.showerror("保存失败", str(exc))
            else:
                if mode != "auto":
                    self.logger.log(f"保存设置失败：{exc}")
            return False

    def restore_default_settings(self) -> None:
        if not messagebox.askyesno("恢复默认", "确定要把设置恢复成默认值吗？"):
            return
        defaults = Settings()
        self._set_settings_vars(defaults)
        self.settings_status_var.set("默认值已恢复，正在自动保存...")
        self.schedule_settings_autosave(delay_ms=0)
        self.logger.log("设置页已恢复默认值，并已触发自动保存。")

    def collect_run_options(self) -> RunOptions:
        prompt_count = positive_int(self.prompt_count_var.get(), "提示词数")
        output_resolution, output_aspect_ratio = parse_output_selection(
            legacy_output=self.aspect_ratio_var.get().strip(),
        )
        user_prompt = self._read_text_widget(self.task_user_prompt_text).strip()
        if not user_prompt:
            raise AppError("用户提示词不能为空。")
        return RunOptions(
            project_name=generate_project_name(),
            prompt_count=prompt_count,
            output_resolution=output_resolution,
            output_aspect_ratio=output_aspect_ratio,
            user_prompt=user_prompt,
            images_per_prompt=self.settings.default_images_per_prompt,
            concurrency=self.settings.default_concurrency,
            style_source=SourceSpec(
                file_path=self.style_file_var.get(),
                url=self.style_url_var.get(),
            ),
            product_source=SourceSpec(
                file_path=self.product_file_var.get(),
                url=self.product_url_var.get(),
            ),
        )

    def start_generation(self) -> None:
        if self.worker_thread is not None and self.worker_thread.is_alive():
            messagebox.showwarning("任务进行中", "当前已有生成任务在运行。")
            return
        if not self.save_settings(show_message=False):
            messagebox.showerror("设置无效", "请先修正设置页里的参数。")
            return
        try:
            options = self.collect_run_options()
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self.status_var.set("运行中")
        self.start_button.configure(state="disabled")
        self.progress.start(10)
        self._set_result_text("任务已启动，正在生成，请查看日志和结果输出。\n")
        self.logger.log(
            "准备启动任务："
            f"project={options.project_name}, prompt_count={options.prompt_count}, "
            f"resolution={options.output_resolution}, ratio={options.output_aspect_ratio}"
        )
        self.worker_thread = threading.Thread(
            target=self._run_worker,
            args=(options,),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_worker(self, options: RunOptions) -> None:
        try:
            settings = self.collect_settings()
            record = run_pipeline(self.context, settings, options, self.logger)
            self.ui_queue.put(("completed", record))
        except Exception as exc:
            self.ui_queue.put(("failed", str(exc)))

    def poll_queue(self) -> None:
        try:
            while True:
                event_type, payload = self.ui_queue.get_nowait()
                if event_type == "log":
                    self._append_log(payload)
                elif event_type == "completed":
                    self.on_generation_completed(payload)
                elif event_type == "failed":
                    self.on_generation_failed(payload)
        except queue.Empty:
            pass
        self.root.after(200, self.poll_queue)

    def on_generation_completed(self, record: dict[str, Any]) -> None:
        self.latest_run_record = record
        self.status_var.set("已完成")
        self.progress.stop()
        self.start_button.configure(state="normal")
        self.refresh_history()
        lines = [
            "本次任务完成。",
            f"项目名: {record.get('project_name', '')}",
            f"运行目录: {record.get('run_dir', '')}",
            f"提示词数: {record.get('prompt_count', '')}",
            f"出图总数: {record.get('rendered_image_count', '')}",
            f"调试日志: {record.get('debug_log_file', '')}",
        ]
        latest_images = record.get("latest_images") or []
        if latest_images:
            lines.append("图片文件:")
            lines.extend(latest_images)
        self._set_result_text("\n".join(lines) + "\n")
        messagebox.showinfo("任务完成", "生成完成，文件已保存到 data 目录。")

    def on_generation_failed(self, message: str) -> None:
        self.status_var.set("失败")
        self.progress.stop()
        self.start_button.configure(state="normal")
        self.refresh_history()
        self._set_result_text(f"任务失败：\n{message}\n")
        messagebox.showerror("任务失败", message)

    def refresh_history(self) -> None:
        history = self.context.load_history()
        for item_id in self.history_tree.get_children():
            self.history_tree.delete(item_id)
        for index, record in enumerate(history):
            item_id = str(index)
            self.history_tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    record.get("created_at", ""),
                    record.get("project_name", ""),
                    record.get("status", ""),
                    record.get("prompt_count", ""),
                    record.get("aspect_ratio", ""),
                ),
            )
        if history:
            self.latest_run_record = history[0]

    def on_history_select(self, _event: Any) -> None:
        record = self.get_selected_history_record()
        if record is None:
            return
        self.history_detail.delete("1.0", "end")
        self.history_detail.insert(
            "1.0",
            json.dumps(record, ensure_ascii=False, indent=2),
        )

    def get_selected_history_record(self) -> dict[str, Any] | None:
        selection = self.history_tree.selection()
        if not selection:
            return None
        index = int(selection[0])
        history = self.context.load_history()
        if 0 <= index < len(history):
            return history[index]
        return None

    def open_selected_history(self) -> None:
        record = self.get_selected_history_record()
        if record is None:
            messagebox.showwarning("未选择", "请先在历史里选中一条任务。")
            return
        self.try_open_path(Path(record["run_dir"]))

    def export_selected_zip(self) -> None:
        record = self.get_selected_history_record()
        if record is None:
            messagebox.showwarning("未选择", "请先在历史里选中一条任务。")
            return
        self._export_zip_for_record(record)

    def open_latest_run(self) -> None:
        if not self.latest_run_record:
            messagebox.showwarning("暂无结果", "还没有可打开的结果目录。")
            return
        self.try_open_path(Path(self.latest_run_record["run_dir"]))

    def export_latest_zip(self) -> None:
        if not self.latest_run_record:
            messagebox.showwarning("暂无结果", "还没有可导出的结果。")
            return
        self._export_zip_for_record(self.latest_run_record)

    def _export_zip_for_record(self, record: dict[str, Any]) -> None:
        try:
            run_dir = Path(record["run_dir"])
            zip_path = export_run_zip(run_dir)
            self.logger.log(f"已导出 ZIP：{zip_path}")
            self._set_result_text(f"ZIP 已导出：\n{zip_path}\n")
            if messagebox.askyesno("导出成功", "ZIP 已导出，是否立即打开所在目录？"):
                self.try_open_path(zip_path.parent)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    def try_open_path(self, path: Path) -> None:
        try:
            open_path(path)
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def _set_result_text(self, text: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    def _append_log(self, line: str) -> None:
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")

    def _load_log_file(self) -> None:
        text = ""
        if self.context.app_log_path.exists():
            text = self.context.app_log_path.read_text(encoding="utf-8", errors="replace")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", text)


def main() -> int:
    context = AppContext.detect()
    root = tk.Tk()
    GeneratorApp(root, context)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

