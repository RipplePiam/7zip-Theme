"""ResTuner 主窗口。

设计原则：
* 所有耗时操作放后台线程，界面只通过 ``queue`` 收日志，绝不阻塞；
* 破坏性动作（写回、还原）一律先弹确认；
* 权限不足时给出"以管理员身份重启"，而不是抛一串英文异常。
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable, List, Optional

from .. import __version__, paths
from ..backup import Backup, list_backups
from ..errors import ResTunerError
from ..logbus import LogBus
from ..service import ApplyOptions, ApplyReport, PatcherService
from ..target import TargetInfo, find_install_dir, is_admin

APP_TITLE = "7-Zip 主题工具 · ResTuner %s" % __version__

TAG_COLORS = {
    "ok": "#0a7d28",
    "warn": "#b06a00",
    "error": "#b00020",
    "info": "#1f4e79",
    "debug": "#666666",
}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("880x620")
        self.minsize(760, 540)
        icon = os.path.join(paths.assets_dir(), "filetype", "7z.ico")
        if os.path.isfile(icon):
            try:
                self.iconbitmap(default=icon)
            except tk.TclError:
                pass

        self._queue: "queue.Queue" = queue.Queue()
        self._busy = False
        self._service: Optional[PatcherService] = None
        self._info: Optional[TargetInfo] = None
        self._theme_root = paths.assets_dir()

        self.var_dir = tk.StringVar()
        self.var_status = tk.StringVar(value="尚未检查")
        self.var_theme = tk.StringVar(value="Windows 10 Default 文件图标 + Glyfz 2016 工具条")
        self.var_backup = tk.BooleanVar(value=True)
        self.var_force = tk.BooleanVar(value=False)
        self.var_progress = tk.StringVar(value="就绪")

        self._build_ui()
        self._autodetect()
        self.after(80, self._poll_queue)
        if self.var_dir.get().strip():
            self.after(250, self._check)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        # ---- 目标目录
        row = ttk.Frame(outer)
        row.pack(fill="x")
        ttk.Label(row, text="7-Zip 安装目录：", width=16).pack(side="left")
        entry = ttk.Entry(row, textvariable=self.var_dir)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览…", command=self._browse).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="检查", command=self._check).pack(side="left", padx=(6, 0))

        # ---- 状态
        box = ttk.LabelFrame(outer, text="状态", padding=(10, 8))
        box.pack(fill="x", pady=(10, 8))
        ttk.Label(box, text="目标：").grid(row=0, column=0, sticky="w")
        ttk.Label(box, textvariable=self.var_status, foreground="#1f4e79").grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(box, text="主题：").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(box, textvariable=self.var_theme).grid(row=1, column=1, sticky="w", pady=(4, 0))
        ttk.Label(box, text="权限：").grid(row=2, column=0, sticky="w", pady=(4, 0))
        perm = "管理员" if is_admin() else "普通用户"
        ttk.Label(box, text=perm + "（写入 Program Files 需要管理员）").grid(
            row=2, column=1, sticky="w", pady=(4, 0)
        )
        box.columnconfigure(1, weight=1)

        # ---- 选项
        opts = ttk.Frame(outer)
        opts.pack(fill="x")
        ttk.Checkbutton(opts, text="写回前自动备份（推荐）", variable=self.var_backup).pack(side="left")
        ttk.Checkbutton(
            opts, text="我知道风险，允许对未验证版本执行", variable=self.var_force
        ).pack(side="left", padx=(16, 0))

        # ---- 按钮
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 8))
        self.btn_apply = ttk.Button(buttons, text="应用主题", command=self._apply)
        self.btn_apply.pack(side="left")
        ttk.Button(buttons, text="还原备份", command=self._restore).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="刷新图标缓存", command=self._refresh_icons).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(buttons, text="打开备份目录", command=self._open_backup_dir).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(buttons, text="以管理员身份重启", command=self._elevate).pack(side="right")

        # ---- 日志
        logbox = ttk.LabelFrame(outer, text="日志", padding=(6, 6))
        logbox.pack(fill="both", expand=True)
        self.text = ScrolledText(logbox, height=16, wrap="word", font=("Consolas", 9))
        self.text.pack(fill="both", expand=True)
        for level, color in TAG_COLORS.items():
            self.text.tag_configure(level, foreground=color)
        self.text.configure(state="disabled")

        # ---- 进度
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(
            bottom, mode="determinate", maximum=100, value=0, length=180
        )
        self.progress.pack(side="left")
        ttk.Label(bottom, textvariable=self.var_progress).pack(side="left", padx=(10, 0))

    # ------------------------------------------------------------- 辅助

    def _log(self, level: str, message: str) -> None:
        self._queue.put(("log", level, message))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, *payload = self._queue.get_nowait()
                if kind == "log":
                    level, message = payload
                    self._append_log(level, message)
                elif kind == "done":
                    callback = payload[0]
                    callback()
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _append_log(self, level: str, message: str) -> None:
        symbol = {"ok": "✓", "warn": "!", "error": "✗", "info": "·", "debug": "·"}.get(level, "·")
        self.text.configure(state="normal")
        self.text.insert("end", "%s %s\n" % (symbol, message), level)
        self.text.see("end")
        self.text.configure(state="disabled")

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        if busy:
            self.progress.configure(mode="indeterminate", value=0)
            self.progress.start(12)
            self.var_progress.set(text or "处理中…")
        else:
            # 关键：indeterminate 模式停住后，那个色块会残留在槽里（看起来"只走了一点"）。
            # 必须先 stop()，再切回 determinate 且 value=0，槽才会被清空。
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=100, value=0)
            self.var_progress.set(text or "就绪")
        state = "disabled" if busy else "normal"
        self.btn_apply.configure(state=state)

    def _run_async(self, work: Callable[[], None], done: Callable[[], None]) -> None:
        if self._busy:
            messagebox.showinfo("请稍候", "上一个操作还没结束")
            return
        self._set_busy(True)

        def runner() -> None:
            try:
                work()
            except ResTunerError as exc:
                self._log("error", str(exc))
            except Exception as exc:  # noqa: BLE001
                self._log("error", "%s: %s" % (type(exc).__name__, exc))
            finally:
                self._queue.put(("done", done))

        threading.Thread(target=runner, daemon=True).start()

    def _service_instance(self) -> Optional[PatcherService]:
        directory = self.var_dir.get().strip()
        if not directory:
            messagebox.showwarning("缺少目录", "请先选择 7-Zip 的安装目录")
            return None
        try:
            bus = LogBus(sink=self._log, log_dir=paths.logs_dir())
            return PatcherService(self._theme_root, log=bus)
        except ResTunerError as exc:
            self._append_log("error", str(exc))
            messagebox.showerror("无法初始化", str(exc))
            return None
        except Exception as exc:  # noqa: BLE001
            self._append_log("error", "初始化失败：%s: %s" % (type(exc).__name__, exc))
            messagebox.showerror("无法初始化", "%s: %s" % (type(exc).__name__, exc))
            return None

    def report_callback_exception(self, exc_type, exc_value, tb) -> None:  # type: ignore[override]
        """Tk 回调里的异常必须显式报出来。

        默认行为是打到 stderr —— 打包成窗口程序后 stderr 根本看不见，
        界面就会停在"什么都没发生"的状态（这正是 v1.0 的一个真实缺陷）。
        """
        import traceback

        detail = "".join(traceback.format_exception(exc_type, exc_value, tb))
        try:
            self._set_busy(False, "出错")
        except Exception:  # noqa: BLE001
            pass
        try:
            self._append_log("error", "界面回调异常：%s: %s" % (exc_type.__name__, exc_value))
            self._append_log("debug", detail)
        except Exception:  # noqa: BLE001
            pass
        try:
            messagebox.showerror("内部错误", "%s: %s" % (exc_type.__name__, exc_value))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------- 动作

    def _autodetect(self) -> None:
        found = find_install_dir()
        if found:
            self.var_dir.set(found)
            self._append_log("info", "已自动找到 7-Zip 安装目录：%s" % found)
        else:
            self._append_log("warn", "没有自动找到 7-Zip 安装目录，请手动选择")

    def _browse(self) -> None:
        initial = self.var_dir.get().strip() or os.environ.get("ProgramFiles", "C:\\")
        chosen = filedialog.askdirectory(title="选择 7-Zip 安装目录", initialdir=initial)
        if chosen:
            self.var_dir.set(os.path.normpath(chosen))
            self._check()

    def _check(self) -> None:
        svc = self._service_instance()
        if svc is None:
            return
        self._info = None

        def work() -> None:
            info = svc.inspect(self.var_dir.get().strip())
            self._info = info
            self._queue.put(("log", "info", "—" * 40))
            self._queue.put(("log", "info", info.summary()))

        def done() -> None:
            self._set_busy(False)
            if self._info is not None:
                self.var_status.set(self._info.summary())
            else:
                self.var_status.set("检查失败，详见日志")

        self._run_async(work, done)

    def _apply(self) -> None:
        svc = self._service_instance()
        if svc is None:
            return
        directory = self.var_dir.get().strip()
        if not messagebox.askyesno(
            "确认",
            "即将改写以下文件：\n\n%s\n\n"
            "· 会先备份到 .restuner-backup\n"
            "· 建议先退出 7-Zip，改完后重启资源管理器让图标生效\n\n继续吗？" % directory,
        ):
            return
        force = bool(self.var_force.get())
        make_backup = bool(self.var_backup.get())
        report_holder: List[ApplyReport] = []

        def work() -> None:
            report = svc.apply(
                ApplyOptions(
                    directory=directory,
                    theme_root=self._theme_root,
                    force=force,
                    make_backup=make_backup,
                )
            )
            report_holder.append(report)

        def done() -> None:
            self._set_busy(False)
            report = report_holder[0] if report_holder else None
            if report and report.ok:
                self.var_status.set("7-Zip %s · 已打主题补丁" % report.version)
                if messagebox.askyesno(
                    "完成",
                    "主题已应用（7-Zip %s）。\n\n是否现在刷新图标缓存？\n"
                    "（资源管理器可能还需要重启才能在旧文件上看到新图标）" % report.version,
                ):
                    self._refresh_icons()
            else:
                self._set_busy(False, "失败")
                self.var_status.set("失败，详见日志")

        self._run_async(work, done)

    def _restore(self) -> None:
        directory = self.var_dir.get().strip()
        if not directory:
            messagebox.showwarning("缺少目录", "请先选择 7-Zip 的安装目录")
            return
        backups = list_backups(directory)
        if not backups:
            messagebox.showinfo("没有备份", "这个目录下没有找到 .restuner-backup 备份")
            return
        chosen = BackupDialog(self, backups).result
        if chosen is None:
            return
        svc = self._service_instance()
        if svc is None:
            return

        def work() -> None:
            svc.restore(chosen, directory)
            self._queue.put(("log", "ok", "还原完成，建议再点一次「检查」"))

        def done() -> None:
            self._set_busy(False)
            self.var_status.set("已还原到 %s" % chosen.version)
            messagebox.showinfo("完成", "已还原为备份中的原始文件")

        self._run_async(work, done)

    def _refresh_icons(self) -> None:
        def work() -> None:
            self._log("info", "刷新资源管理器图标缓存 …")
            for cmd in (["ie4uinit.exe", "-show"], ["ie4uinit.exe", "-ClearIconCache"]):
                try:
                    subprocess.run(cmd, check=False, timeout=20, capture_output=True)
                except Exception as exc:  # noqa: BLE001
                    self._log("warn", "调用 %s 失败：%s" % (cmd[0], exc))
            self._log("ok", "图标缓存已刷新；若仍显示旧图标，请重启资源管理器或注销一次")

        def done() -> None:
            self._set_busy(False)

        self._run_async(work, done)

    def _open_backup_dir(self) -> None:
        directory = self.var_dir.get().strip()
        if not directory:
            return
        target = os.path.join(directory, ".restuner-backup")
        if not os.path.isdir(target):
            messagebox.showinfo("没有备份", "还没有任何备份")
            return
        os.startfile(target)  # noqa: S606 - 打开资源管理器

    def _elevate(self) -> None:
        if is_admin():
            messagebox.showinfo("无需提权", "当前已经是管理员权限")
            return
        try:
            import ctypes

            if getattr(sys, "frozen", False):
                exe, params = sys.executable, ""
            else:
                exe = sys.executable
                params = '"%s"' % os.path.join(paths.project_root(), "run_gui.py")
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
            if rc <= 32:
                messagebox.showerror("提权失败", "ShellExecute 返回 %d（可能被用户取消）" % rc)
                return
            self.destroy()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("提权失败", str(exc))


class BackupDialog(tk.Toplevel):
    """选择一份备份来还原。"""

    def __init__(self, master: tk.Misc, backups: List[Backup]) -> None:
        super().__init__(master)
        self.title("选择要还原的备份")
        self.transient(master)
        self.resizable(False, False)
        self.result: Optional[Backup] = None
        self._backups = backups

        ttk.Label(self, text="备份越靠上越新：", padding=(10, 8)).pack(anchor="w")
        self.listbox = tk.Listbox(self, width=78, height=min(10, len(backups)), font=("Consolas", 9))
        self.listbox.pack(padx=10, fill="both", expand=True)
        for item in backups:
            self.listbox.insert("end", "%s  |  %s  |  %s" % (item.created, item.version, item.directory))
        self.listbox.selection_set(0)

        row = ttk.Frame(self, padding=10)
        row.pack(fill="x")
        ttk.Button(row, text="取消", command=self._cancel).pack(side="right")
        ttk.Button(row, text="还原", command=self._confirm).pack(side="right", padx=(0, 8))

        self.grab_set()
        self.wait_window(self)

    def _confirm(self) -> None:
        selection = self.listbox.curselection()
        if selection:
            self.result = self._backups[selection[0]]
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def main() -> int:
    try:
        app = App()
    except ResTunerError as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("启动失败", str(exc))
        return 1
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
