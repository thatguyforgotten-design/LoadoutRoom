"""Native LoadoutRoom desktop interface."""
import io
import json
import os
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from urllib.parse import urlparse

# pythonw has no console streams. Libraries must not depend on a terminal.
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

import requests
from PIL import Image, ImageTk
from src.desktop_backend import Collector, sample_snapshot, HeadshotCollector
from src.desktop_stats import team_summary
from src import desktop_updates as updates
from src.desktop_colors import agent_color
from src.windows_identity import set_process_identity, set_window_identity

BG, PANEL, CARD, LINE = "#0d1017", "#11151e", "#1a202c", "#29303d"
FG, MUTED, CORAL, BLUE, RED = "#f2f4fc", "#9aa8c0", "#ff626a", "#8bbfff", "#ff8790"


def percent(value):
    return "N/A" if value is None else format(value, ".1f") + "%"


def allowed_art(url):
    try:
        parsed = urlparse(url or "")
        return parsed.scheme == "https" and (parsed.hostname == "media.valorant-api.com"
            or (parsed.hostname == "cdn.source.gs" and parsed.path.startswith("/valorant/img/")))
    except ValueError:
        return False


def fetch_art(url):
    if not allowed_art(url):
        return None
    try:
        with requests.get(url, stream=True, timeout=10) as response:
            response.raise_for_status()
            parts, size = [], 0
            for part in response.iter_content(65536):
                size += len(part)
                if size > 4_000_000:
                    return None
                parts.append(part)
        image = Image.open(io.BytesIO(b"".join(parts))).convert("RGBA")
        image.thumbnail((230, 88), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return None


def rounded_points(x1, y1, x2, y2, r):
    r = min(r, max(0, (x2-x1)/2), max(0, (y2-y1)/2))
    return [x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,x2,y2-r,x2,y2,
            x2-r,y2,x1+r,y2,x1,y2,x1,y2-r,x1,y1+r,x1,y1]


class Surface(tk.Frame):
    """A rounded panel with normal native widget layout inside."""
    def __init__(self, parent, fill=PANEL, border=LINE, padding=16, radius=15):
        super().__init__(parent, bg=parent.cget("bg"), bd=0)
        self.fill, self.border, self.radius = fill, border, radius
        self.backdrop = tk.Canvas(self, bg=parent.cget("bg"), bd=0, highlightthickness=0)
        self.backdrop.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=fill)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)
        self.last_size = None
        self.bind("<Configure>", self.draw)

    def draw(self, event=None):
        w, h = self.winfo_width(), self.winfo_height()
        if (w, h) == self.last_size:
            return
        self.last_size = (w, h)
        self.backdrop.delete("all")
        self.backdrop.create_polygon(rounded_points(0, 0, w, h, self.radius),
            fill=self.border, outline="", smooth=True, splinesteps=24)
        self.backdrop.create_polygon(rounded_points(1, 1, w-1, h-1, self.radius),
            fill=self.fill, outline="", smooth=True, splinesteps=24)


class TrackerWindow:
    def __init__(self, root, start_collector=True):
        self.root = root
        root.title("LoadoutRoom")
        width = min(1320, max(1080, root.winfo_screenwidth() - 80))
        height = min(900, max(700, root.winfo_screenheight() - 100))
        root.geometry(str(width) + "x" + str(height))
        root.minsize(1080, 700)
        root.configure(bg=BG)
        icon = Path(__file__).parent / "assets/Logo.ico"
        if icon.is_file():
            try:
                root.iconbitmap(str(icon))
            except tk.TclError:
                pass
        self.events = queue.Queue()
        self.collector = Collector(self.events)
        self.headshots = HeadshotCollector(self.events)
        self.hs_results = {}
        self.hs_subject = None
        self.network_enabled = start_collector
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Artwork")
        self.images, self.pending, self.waiting = {}, set(), {}
        self.snapshot = None
        self.selected = None
        self.sample = False
        self.closed = False
        self.render_job = None
        self.render_key = None
        self.team_filter = "All"
        self.update_busy = False
        self.search = tk.StringVar()
        self.weapon_filter = tk.StringVar(value="All weapons")
        self.always_top = tk.BooleanVar()
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Treeview", background=PANEL, foreground=FG, fieldbackground=PANEL,
                        borderwidth=0, rowheight=54, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=CARD, foreground=MUTED,
                        borderwidth=0, relief="flat", font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", "#3c3554")], foreground=[("selected", "white")])
        style.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=FG,
                        arrowcolor=FG, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", CARD)],
                  foreground=[("readonly", FG)], selectbackground=[("readonly", CARD)])
        style.configure("Vertical.TScrollbar", background=CARD, troughcolor=PANEL,
                        arrowcolor=MUTED, bordercolor=PANEL)
        self.build()
        self.search.trace_add("write", lambda *args: self.schedule_render())
        self.weapon_filter.trace_add("write", lambda *args: self.schedule_render())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(0, self.apply_window_style)
        root.after(100, self.process_events)
        if start_collector:
            self.collector.start()
            self.headshots.start()
            settings = updates.read_settings()
            if settings["feed"] and settings["check_on_start"]:
                root.after(2500, lambda: self.check_updates(quiet=True))

    def label(self, parent, text, size=10, color=FG, bold=False, **kw):
        return tk.Label(parent, text=text, fg=color, bg=parent.cget("bg"),
                        font=("Segoe UI Semibold" if bold else "Segoe UI", size), **kw)

    def button(self, parent, title, action, accent=False):
        return tk.Button(parent, text=title, command=action, bg=CORAL if accent else CARD,
                         fg=BG if accent else FG, activebackground="#d0c4ff" if accent else "#37415b",
                         activeforeground=BG if accent else FG, relief="flat", bd=0,
                         padx=20, pady=11, cursor="hand2", font=("Segoe UI Semibold", 10))

    def build(self):
        # Reserve the footer before the expanding loadout panel, including at
        # the minimum window size.
        foot = tk.Frame(self.root, bg=BG, padx=28, pady=8)
        foot.pack(side="bottom", fill="x")
        self.label(foot, "Unofficial VALORANT companion",
                   9, MUTED).pack(side="left")
        self.version_label = self.label(foot, "v" + updates.VERSION, 9, MUTED)
        self.version_label.pack(side="right", padx=(16, 0))
        self.updated = self.label(foot, "No live match received", 9, MUTED)
        self.updated.pack(side="right")
        head = tk.Frame(self.root, bg=BG, padx=20, pady=10)
        head.pack(fill="x")
        logo = tk.Canvas(head, width=42, height=42, bg=BG, highlightthickness=0)
        logo.pack(side="left", padx=(0, 13))
        try:
            self.brand_image = ImageTk.PhotoImage(Image.open(Path(__file__).parent / "assets/brand.png").resize((42, 42), Image.Resampling.LANCZOS), master=self.root)
            logo.create_image(21, 21, image=self.brand_image)
        except (OSError, tk.TclError):
            logo.create_text(21, 21, text="LR", fill=CORAL, font=("Segoe UI", 18, "bold"))
        self.label(head, "Loadout", 25, bold=True).pack(side="left")
        self.label(head, "Room", 25, color=CORAL).pack(side="left")
        self.button(head, "Refresh match", self.refresh, True).pack(side="right", padx=(10, 0))
        self.button(head, "Updates", self.update_menu).pack(side="right", padx=(8, 0))
        self.sample_button = self.button(head, "Show sample", self.toggle_sample)
        self.sample_button.pack(side="right")
        self.label(head, "MATCH INTELLIGENCE", 8, color=MUTED).pack(side="right", padx=20)
        meta = tk.Frame(self.root, bg=BG, padx=28)
        meta.pack(fill="x")
        self.connection = self.label(meta, "Open VALORANT. Connecting automatically...", 10, MUTED, anchor="w")
        self.connection.pack(side="left", fill="x", expand=True)
        tk.Checkbutton(meta, text="Keep on top", variable=self.always_top, command=lambda:
            self.root.attributes("-topmost", self.always_top.get()), bg=BG, fg=MUTED,
            selectcolor=CARD, activebackground=BG, activeforeground=FG,
            font=("Segoe UI", 9)).pack(side="right")
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=20, pady=(8, 10))
        stats_panel = tk.Frame(top, bg=PANEL, width=230)
        stats_panel.pack(side="left", fill="y", padx=(0, 12))
        roster_panel = tk.Frame(top, bg=BG)
        roster_panel.pack(side="left", fill="both", expand=True)
        left = roster_panel
        inventory_panel = Surface(self.root, fill=PANEL, border=LINE, padding=12, radius=10)
        inventory_panel.pack(fill="both", expand=True, padx=20, pady=(0, 6))
        right = inventory_panel.body
        summaries = tk.Frame(stats_panel, bg=PANEL, pady=0)
        summaries.pack(fill="x")
        summaries.columnconfigure(0, weight=1)
        self.team_labels, self.team_bars = {}, {}
        for column, team, color in [(0, "Blue", BLUE), (1, "Red", RED)]:
            surface = Surface(summaries, fill="#142137" if team == "Blue" else "#291e30",
                              border="#304968" if team == "Blue" else "#51354a", padding=6, radius=8)
            surface.grid(row=column, column=0, sticky="nsew", pady=(0, 4))
            box = surface.body
            self.label(box, team.upper() + " TEAM", 8, color, True).pack(side="left", padx=(0, 6))
            numbers = tk.Frame(box, bg=box.cget("bg"))
            numbers.pack(fill="x")
            rate = self.label(numbers, "N/A", 11, FG, True)
            rate.pack(side="left")
            coverage = self.label(numbers, "Waiting", 8, MUTED)
            coverage.pack(side="right")
            self.team_labels[team] = (rate, coverage)
            bar = tk.Canvas(box, height=5, bg=box.cget("bg"), highlightthickness=0)
            bar.pack(side="bottom", fill="x", pady=(3, 0))
            self.team_bars[team] = (bar, color)
            bar.bind("<Configure>", lambda event, name=team: self.draw_team_bar(name))
        self.leader = self.label(summaries, "Team comparison appears when both teams have available stats.",
                                 9, MUTED, anchor="w", wraplength=225, justify="left")
        self.leader.grid(row=2, column=0, sticky="ew", pady=(3, 0))
        self.label(summaries, "Average player win rate this act in Competitive. Not a match-win prediction.",
                   8, MUTED, anchor="w", wraplength=260, justify="left").grid(row=3, column=0, sticky="ew", pady=(3, 4))
        self.roster_heading = self.label(left, "MATCH ROSTER", 11, bold=True, anchor="w")
        self.roster_heading.pack(fill="x", pady=(0, 3))
        teams = tk.Frame(left, bg=PANEL)
        teams.pack(fill="x", pady=(0, 3))
        self.team_buttons = {}
        for name in ("All", "Blue", "Red"):
            button = self.button(teams, name, lambda name=name: self.filter_team(name))
            button.pack(side="left", expand=True, fill="x", padx=2)
            self.team_buttons[name] = button
        grid = tk.Frame(left, bg=PANEL)
        # Hidden data model retained for selection and accessibility tests.
        columns = ("team", "name", "agent", "level", "rank", "winRate", "games")
        self.tree = ttk.Treeview(grid, columns=columns, displaycolumns=("name", "winRate"), show="headings", selectmode="browse")
        for key, title, width in [("team", "TEAM", 48), ("name", "PLAYER", 150),
             ("agent", "AGENT", 74), ("level", "LEVEL", 48), ("rank", "RANK", 85),
             ("winRate", "WIN RATE", 74), ("games", "GAMES", 52)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=40, anchor="w" if key in ("name", "agent", "rank") else "center")
        self.tree.column("name", width=190, minwidth=140)
        self.tree.column("winRate", width=65, minwidth=60, stretch=False)
        self.tree.tag_configure("Blue", foreground="#c8dfff", background="#151f30")
        self.tree.tag_configure("Red", foreground="#f1ced9", background="#211d2c")
        scroll = ttk.Scrollbar(grid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.player_buttons_frame = tk.Frame(left, bg=BG)
        self.player_buttons_frame.pack(fill="both", expand=True)
        self.player_buttons = {}
        for col in range(5):
            self.player_buttons_frame.columnconfigure(col, weight=1, uniform="players")
        self.tree.bind("<<TreeviewSelect>>", self.select_player)
        self.label(left, "N/A = unavailable or no games. Hidden names and levels stay hidden.",
                   9, MUTED, anchor="w", wraplength=255).pack(fill="x", pady=(12, 0))
        self.player_title = self.label(right, "All equipped skins", 25, bold=True, anchor="w")
        self.player_title.pack(fill="x")
        self.player_subtitle = self.label(right, "Select a player to inspect their weapons.", 10, MUTED, anchor="w")
        self.player_subtitle.pack(fill="x", pady=(5, 4))
        self.hs_label = self.label(right, "HS%: select a player", 9, MUTED, anchor="w")
        self.hs_label.pack(fill="x", pady=(0, 8))
        controls = tk.Frame(right, bg=PANEL)
        controls.pack(fill="x", pady=(0, 10))
        self.combo = ttk.Combobox(controls, textvariable=self.weapon_filter,
                                 state="readonly", values=["All weapons"], width=16)
        self.combo.pack(side="left", padx=(0, 8))
        search = tk.Entry(controls, textvariable=self.search, bg=CARD, fg=FG, insertbackground=FG,
                          relief="flat", font=("Segoe UI", 10), width=16)
        search.pack(side="left", fill="x", expand=True, ipady=7)
        self.label(right, "WEAPONS  /  EQUIPPED COLLECTION", 9, MUTED, anchor="w").pack(fill="x", pady=(0, 10))
        canvas_box = tk.Frame(right, bg=PANEL)
        canvas_box.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(canvas_box, bg=PANEL, highlightthickness=0, yscrollincrement=24)
        bar = ttk.Scrollbar(canvas_box, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.cards = tk.Frame(self.canvas, bg=PANEL)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.cards, anchor="nw")
        self.cards.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize_inventory)
        self.root.bind("<MouseWheel>", self.scroll_equipment, add="+")
        self.render_loadout()

    def draw_team_bar(self, name):
        bar, color = self.team_bars[name]
        value = team_summary((self.snapshot or {}).get("players", []))[name]["average"] or 0
        width = max(bar.winfo_width(), 1)
        bar.delete("all")
        bar.create_rectangle(0, 0, width, 5, fill="#30364b", outline="")
        if value > 0:
            bar.create_rectangle(0, 0, width * value / 100, 5, fill=color, outline="")

    def apply_window_style(self):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            enabled = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(enabled), 4)
        except (AttributeError, OSError):
            pass

    def update_menu(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("LoadoutRoom - Updates")
        dialog.configure(bg=PANEL)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        box = tk.Frame(dialog, bg=PANEL, padx=24, pady=20)
        box.pack(fill="both", expand=True)
        self.label(box, "Updates · version " + updates.VERSION, 17, bold=True).pack(anchor="w")
        self.label(box, "Each installation requires your permission. Your previous copy is kept.",
                   10, MUTED, wraplength=440, justify="left").pack(anchor="w", pady=10)
        settings = updates.read_settings()
        self.label(box, "Publisher update-feed URL (HTTPS)", 10).pack(anchor="w")
        address = tk.StringVar(value=settings["feed"])
        tk.Entry(box, textvariable=address, width=60, bg=CARD, fg=FG, insertbackground=FG).pack(fill="x", pady=8)
        automatic = tk.BooleanVar(value=settings["check_on_start"] if settings["feed"] else True)
        tk.Checkbutton(box, text="Check at startup; ask before installing", variable=automatic,
            bg=PANEL, fg=FG, selectcolor=CARD, activebackground=PANEL, activeforeground=FG).pack(anchor="w")
        def save_check():
            try:
                updates.save_settings(address.get().strip(), automatic.get())
            except (ValueError, OSError) as error:
                messagebox.showerror("Updates", str(error), parent=dialog)
                return
            dialog.destroy()
            self.check_updates()
        self.button(box, "Save and check", save_check, True).pack(anchor="e", pady=(15, 0))
        if not settings["feed"]:
            self.label(box, "Automatic updates are not connected yet. A publisher release feed is required.",
                       10, MUTED, wraplength=440, justify="left").pack(anchor="w", pady=10)

    def check_updates(self, quiet=False):
        if self.update_busy:
            return
        feed = updates.read_settings()["feed"]
        if not feed:
            return
        self.update_busy = True
        def worker():
            try:
                release = updates.check_update(feed)
                self.events.put(("update_available", release, quiet))
            except Exception:
                self.events.put(("update_error", "Could not check the publisher update feed. Your app is unchanged.", quiet))
        threading.Thread(target=worker, daemon=True, name="Update check").start()

    def handle_update(self, event):
        self.update_busy = False
        if event[0] == "update_error":
            if not event[2]:
                messagebox.showerror("Updates", event[1], parent=self.root)
        elif event[0] == "update_available":
            release, quiet = event[1], event[2]
            if not release:
                if not quiet:
                    messagebox.showinfo("Updates", "You have the latest published version (" + updates.VERSION + ").", parent=self.root)
                return
            text = "Version " + release["version"] + " is available.\n\n" + release.get("notes", "")[:2000]
            text += "\n\nDownload, install and restart now? Your previous copy will be kept."
            if not messagebox.askyesno("Update permission", text, parent=self.root):
                return
            self.update_busy = True
            self.connection.config(text="Downloading and verifying the approved update...")
            def worker():
                try:
                    exe = updates.install_release(release)
                    self.events.put(("update_ready", str(exe)))
                except Exception as error:
                    self.events.put(("update_error", "Update failed. Your existing app is unchanged. " + str(error), False))
            threading.Thread(target=worker, daemon=True, name="Update install").start()
        elif event[0] == "update_ready":
            import subprocess
            try:
                exe = Path(event[1])
                updates.activate_release(exe, subprocess.Popen)
            except (OSError, ValueError):
                messagebox.showerror("Updates", "The new version could not start. Your previous app is still open.", parent=self.root)
                return
            self.close()

    def refresh(self):
        if self.sample:
            self.toggle_sample()
        else:
            self.connection.config(text="Refreshing live data...")
            self.collector.refresh()

    def toggle_sample(self):
        self.sample = not self.sample
        if self.sample:
            self.collector.paused.set()
            self.sample_button.config(text="Return to live")
            self.apply_snapshot(sample_snapshot())
            self.connection.config(text="SAMPLE PREVIEW - example names, stats and equipment. No live data shown.", fg=CORAL)
        else:
            self.collector.paused.clear()
            self.sample_button.config(text="Show sample")
            self.snapshot, self.selected = None, None
            self.update_player_buttons([])
            self.tree.delete(*self.tree.get_children())
            self.connection.config(text="Returning to live match...", fg=MUTED)
            for team in self.team_labels.values():
                team[0].config(text="N/A")
                team[1].config(text="Waiting for live data")
            for name in self.team_bars:
                self.draw_team_bar(name)
            self.leader.config(text="Waiting for both teams.", fg=MUTED)
            self.render_loadout()
            self.collector.refresh()

    def process_events(self):
        try:
            self.drain_events()
        finally:
            if not self.closed:
                self.root.after(100, self.process_events)

    def drain_events(self):
        if self.closed:
            return
        latest_snapshot = None
        deadline = time.perf_counter() + 0.006
        for _ in range(24):
            if time.perf_counter() >= deadline:
                break
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind.startswith("update_"):
                self.handle_update(event)
            elif kind == "headshots":
                self.hs_results[event[1]] = event[2]
                self.show_headshots()
            elif kind == "snapshot" and not self.sample:
                latest_snapshot = event[1]
            elif kind == "status" and not self.sample:
                self.connection.config(text=event[1], fg=MUTED)
            elif kind == "image":
                url, data = event[1], event[2]
                self.pending.discard(url)
                try:
                    image = ImageTk.PhotoImage(data=data, master=self.root) if data else None
                except (tk.TclError, OSError, ValueError):
                    image = None
                self.images[url] = image
                while len(self.images) > 96:
                    self.images.pop(next(iter(self.images)))
                for widget in self.waiting.pop(url, []):
                    if widget.winfo_exists():
                        widget.configure(image=image or "", text="" if image else "Artwork unavailable")
                        widget.image = image
        if latest_snapshot is not None:
            self.apply_snapshot(latest_snapshot)

    def apply_snapshot(self, snapshot):
        self.snapshot = snapshot
        players = snapshot.get("players", [])
        summary = team_summary(players)
        self.connection.config(text=snapshot.get("state", "") + (" | " + snapshot["map"] if snapshot.get("map") else ""),
                               fg=CORAL if snapshot.get("sample") else FG)
        for name in ("Blue", "Red"):
            team = summary[name]
            self.team_labels[name][0].config(text=percent(team["average"]))
            self.team_labels[name][1].config(text=str(team["available"]) + "/" + str(team["total"]) + " players with stats")
            self.draw_team_bar(name)
        leader = summary["leader"]
        if snapshot.get("partial"):
            title, color = "Loading roster and stats - comparison is provisional.", MUTED
        elif leader is None:
            title, color = "Not enough data to compare both teams.", MUTED
        elif leader == "Tie":
            title, color = "Both teams have the same average player win rate.", FG
        else:
            gap = abs(summary["Blue"]["average"] - summary["Red"]["average"])
            title = leader + " has the higher average player win rate (+" + format(gap, ".1f") + " percentage points)."
            color = BLUE if leader == "Blue" else RED
            if any(summary[t]["available"] < summary[t]["total"] for t in ("Blue", "Red")):
                title += " Partial data."
        self.leader.config(text=title, fg=color)
        self.roster_heading.config(text="MATCH ROSTER  /  " + str(len(players)) + " PLAYERS")
        visible = [p for p in players if self.team_filter == "All" or p.get("team") == self.team_filter]
        ids = {p["id"] for p in visible}
        for old in self.tree.get_children():
            if old not in ids:
                self.tree.delete(old)
        for p in visible:
            values=(p.get("team", ""), p.get("name", "") + "\n" + p.get("agent", "") + "  ·  Lv " + str(p.get("level") if p.get("level") is not None else "?"), p.get("agent", ""),
                        p.get("level") if p.get("level") is not None else "Hidden",
                        p.get("rank", "Unavailable"), percent(p.get("winRate")),
                        p.get("games") if p.get("games") is not None else "N/A")
            if self.tree.exists(p["id"]):
                if self.tree.item(p["id"], "values") != tuple(str(v) for v in values):
                    self.tree.item(p["id"], values=values, tags=(p.get("team", "Other"),))
            else:
                self.tree.insert("", "end", iid=p["id"], values=values, tags=(p.get("team", "Other"),))
        if not any(p["id"] == self.selected for p in players):
            self.selected = players[0]["id"] if players else None
        if self.selected in ids and self.tree.selection() != (self.selected,):
            self.tree.selection_set(self.selected)
        self.update_player_buttons(visible)
        self.render_loadout()
        self.updated.config(text=("Sample data" if snapshot.get("sample") else "Updated " +
            datetime.fromtimestamp(snapshot.get("time", 0)).strftime("%H:%M:%S")))

    def update_player_buttons(self, players):
        ids = {p["id"] for p in players}
        for subject in list(self.player_buttons):
            if subject not in ids:
                self.player_buttons.pop(subject).destroy()
        for index, player in enumerate(players):
            subject = player["id"]
            if subject not in self.player_buttons:
                self.player_buttons[subject] = tk.Button(self.player_buttons_frame,
                    command=lambda subject=subject: self.choose_player(subject),
                    relief="flat", bd=0, padx=5, pady=6, cursor="hand2",
                    font=("Segoe UI", 9), wraplength=140, justify="left")
            button = self.player_buttons[subject]
            text = player.get("name", "") + "\n" + player.get("agent", "") + " · " + percent(player.get("winRate")) + "\n" + player.get("rank", "Unavailable") + " | Peak " + player.get("peakRank", "Unavailable")
            color = agent_color(player)
            button.configure(text=text, fg=color, bg="#3c3554" if subject == self.selected else CARD,
                             activebackground="#3c3554", activeforeground=color)
            button.grid(row=index // 5, column=index % 5, sticky="nsew", padx=3, pady=3)

    def choose_player(self, subject):
        self.tree.selection_set(subject)
        self.select_player()

    def show_headshots(self):
        if self.sample:
            self.hs_label.config(text="HS%: sample preview — no history requests")
            return
        result = self.hs_results.get(self.selected)
        if result is None:
            self.hs_label.config(text="HS%: loading recent Competitive history..." if self.selected else "HS%: select a player")
        else:
            self.hs_label.config(text="HS%: " + percent(result.get("headshotRate")) + "  |  " + str(result.get("matches", 0)) + "/10 recent Competitive matches available (head hits / all hits)")
        if self.network_enabled and self.selected and self.hs_subject != self.selected:
            self.hs_subject = self.selected
            self.headshots.request(self.selected)

    def select_player(self, event=None):
        selected = self.tree.selection()
        if selected and selected[0] != self.selected:
            self.selected = selected[0]
            self.weapon_filter.set("All weapons")
            self.search.set("")
            self.update_player_buttons([p for p in self.snapshot.get("players", []) if self.team_filter == "All" or p.get("team") == self.team_filter])
            self.render_loadout()

    def image_label(self, card, url, standard=False):
        if self.sample:
            body_color = "#444b53" if standard else "#b7a5e8"
            metal_color = "#282e35" if standard else "#7b7498"
            edge_color = "#69727d" if standard else "#8b83ad"
            preview = tk.Canvas(card, height=75, bg=card.cget("bg"), highlightthickness=0)
            preview.pack(fill="x", pady=(8, 10))
            preview.create_line(35, 32, 220, 32, fill=edge_color, width=6, capstyle="round")
            preview.create_polygon(48, 29, 80, 24, 125, 24, 145, 32, 128, 40, 76, 40,
                                   fill=body_color, outline="")
            preview.create_polygon(79, 37, 99, 37, 95, 55, 82, 55, fill=metal_color, outline="")
            preview.create_polygon(35, 28, 48, 29, 53, 42, 32, 48, fill=metal_color, outline="")
            preview.create_text(145, 66, text="SAMPLE EQUIPMENT", fill=MUTED,
                                 font=("Segoe UI", 7))
            return preview
        art_box = tk.Frame(card, height=100, bg=card.cget("bg"))
        art_box.pack(fill="x", pady=6)
        art_box.pack_propagate(False)
        label = self.label(art_box, "Loading artwork..." if allowed_art(url) else "Artwork unavailable", 9, MUTED)
        label.pack(fill="both", expand=True)
        if not allowed_art(url):
            return
        if url in self.images:
            image = self.images[url]
            label.config(image=image or "", text="" if image else "Artwork unavailable")
            label.image = image
        else:
            self.waiting.setdefault(url, []).append(label)
            if url not in self.pending:
                self.pending.add(url)
                future = self.pool.submit(fetch_art, url)
                future.add_done_callback(lambda f, target=url: self.events.put(("image", target, f.result())))
        return label

    def filter_team(self, name):
        self.team_filter = name
        for team, button in self.team_buttons.items():
            button.configure(bg="#302332" if team == name else CARD)
        if self.snapshot:
            self.apply_snapshot(self.snapshot)

    def scroll_equipment(self, event):
        widget = event.widget
        while widget is not None:
            if widget == self.canvas:
                self.canvas.yview_scroll(-int(event.delta / 120), "units")
                return "break"
            widget = getattr(widget, "master", None)

    def resize_inventory(self, event):
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        self.schedule_render()

    def schedule_render(self):
        if not self.closed:
            if self.render_job is not None:
                self.root.after_cancel(self.render_job)
            self.render_job = self.root.after(120, self.render_loadout)

    def render_loadout(self):
        if self.render_job is not None:
            self.root.after_cancel(self.render_job)
            self.render_job = None
        if not hasattr(self, "cards"):
            return
        self.show_headshots()
        player = next((p for p in (self.snapshot or {}).get("players", []) if p["id"] == self.selected), None)
        columns = max(1, min(5, self.canvas.winfo_width() // 220))
        if player:
            self.player_title.config(text=player["name"], fg=agent_color(player))
            self.player_subtitle.config(text=player["agent"] + "  |  " + player["team"] + " team  |  " + str(player.get("rank", "Unavailable")) + "  |  Win rate " + percent(player.get("winRate")) + "  |  " + str(len(player.get("weapons", []))) + " weapons equipped" + "\nPeak (recorded): " + player.get("peakRank", "Unavailable") + "  |  Level " + str(player.get("level") if player.get("level") is not None else "Hidden") + "  |  RR " + str(player.get("rr") if player.get("rr") is not None else "N/A") + "  |  Games " + str(player.get("games") if player.get("games") is not None else "N/A"))
        equipment = [player["id"], player.get("weapons", [])] if player else None
        key = json.dumps([equipment, self.sample, self.search.get(), self.weapon_filter.get(), columns], sort_keys=True)
        if key == self.render_key:
            return
        self.render_key = key
        self.waiting.clear()
        for child in self.cards.winfo_children():
            child.destroy()
        player = next((p for p in (self.snapshot or {}).get("players", []) if p["id"] == self.selected), None)
        if not player:
            self.player_title.config(text="ALL EQUIPPED SKINS", fg=FG)
            self.player_subtitle.config(text="No player selected")
            self.label(self.cards, "Your match, all in one window.", 16, bold=True,
                       wraplength=320, justify="left").pack(anchor="w", pady=(40, 12))
            self.label(self.cards, "Open VALORANT and join a match. Names, levels, win rates and loadouts will appear here automatically.",
                       11, MUTED, wraplength=320, justify="left").pack(anchor="w")
            self.label(self.cards, "You can use Show sample to preview the layout.", 10, MUTED,
                       wraplength=320, justify="left").pack(anchor="w", pady=18)
            return
        self.player_title.config(text=player["name"], fg=agent_color(player))
        self.player_subtitle.config(text=player["agent"] + "  |  " + player["team"] + " team  |  " + str(player.get("rank", "Unavailable")) + "  |  Win rate " + percent(player.get("winRate")) + "  |  " + str(len(player.get("weapons", []))) + " weapons equipped" + "\nPeak (recorded): " + player.get("peakRank", "Unavailable") + "  |  Level " + str(player.get("level") if player.get("level") is not None else "Hidden") + "  |  RR " + str(player.get("rr") if player.get("rr") is not None else "N/A") + "  |  Games " + str(player.get("games") if player.get("games") is not None else "N/A"))
        weapons = player.get("weapons", [])
        choices = ["All weapons"] + sorted(set(w.get("weapon", "Unknown weapon") for w in weapons))
        self.combo.configure(values=choices)
        if self.weapon_filter.get() not in choices:
            self.weapon_filter.set("All weapons")
        search = self.search.get().strip().casefold()
        selected = [w for w in weapons if
                    (self.weapon_filter.get() == "All weapons" or w.get("weapon") == self.weapon_filter.get())
                    and search in (str(w.get("weapon", "")) + " " + str(w.get("skinDisplayName", ""))).casefold()]
        if not selected:
            self.label(self.cards, "No matching equipment, or loadout data is not available yet.",
                       11, MUTED, wraplength=320, justify="left").pack(anchor="w", pady=25)
        for col in range(5):
            self.cards.columnconfigure(col, weight=1 if col < columns else 0, uniform="equipment" if col < columns else "")
        for index, item in enumerate(selected):
            surface = Surface(self.cards, fill=CARD, border="#354159", padding=18, radius=15)
            surface.grid(row=index // columns, column=index % columns, sticky="nsew", pady=(0, 13), padx=(0, 10))
            card = surface.body
            self.label(card, str(item.get("weapon", "Unknown weapon")).upper(), 9, CORAL, True).pack(anchor="w")
            self.image_label(card, item.get("skinDisplayIcon"), standard=str(item.get("skinDisplayName", "")).casefold().startswith("standard "))
            self.label(card, item.get("skinDisplayName") or "Unknown skin", 12, bold=True,
                       wraplength=210, justify="left").pack(anchor="w", pady=(3, 0))
            if item.get("variantDisplayName"):
                self.label(card, item["variantDisplayName"], 9, MUTED, wraplength=310).pack(anchor="w")
            if item.get("metadataStatus") == "unknown_skin":
                self.label(card, "Unrecognized skin ID: " + str(item.get("skin") or "unavailable"),
                           8, MUTED, wraplength=310, justify="left").pack(anchor="w", pady=5)
            if item.get("buddy_displayIcon"):
                self.label(card, "Equipped gun buddy", 9, MUTED).pack(anchor="w", pady=(8, 0))
                self.image_label(card, item["buddy_displayIcon"])

    def close(self):
        self.closed = True
        self.collector.stop_event.set()
        self.headshots.stop_event.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def self_test():
    from src.catalog import merge_weapons, WARDEN_ID, WARDEN_SKINS, resolve_weapon
    payload = sample_snapshot()
    assert len(payload["players"]) == 10
    assert team_summary(payload["players"])["leader"] == "Blue"
    assert allowed_art("https://media.valorant-api.com/test.png")
    assert not allowed_art("http://example.com/image.png")
    for skin_id, name, image in WARDEN_SKINS:
        record = resolve_weapon(WARDEN_ID, {"Sockets": {
            "bcef87d6-209b-46c6-8b19-fbe40bd95abc": {"Item": {"ID": skin_id}}}}, merge_weapons([]))
        assert record["skinDisplayName"] == name
    # Validate Tk/Tcl and Pillow imports without a display or network requests.
    interpreter = tk.Tcl()
    assert interpreter.eval("info patchlevel")
    from PIL import features
    assert features.check("webp")
    image = Image.new("RGBA", (2, 2))
    data = io.BytesIO()
    image.save(data, "PNG")
    assert data.getvalue().startswith(b"\x89PNG")
    root = tk.Tk()
    root.withdraw()
    window = TrackerWindow(root, start_collector=False)
    window.toggle_sample()
    root.update_idletasks()
    assert len(window.tree.get_children()) == 10
    assert window.team_labels["Blue"][0].cget("text") != "N/A"
    assert "Blue has the higher" in window.leader.cget("text")
    window.tree.selection_set("sample-6")
    window.select_player()
    assert window.selected == "sample-6"
    assert window.player_title.cget("text") == "Example player 7"
    window.search.set("Warden")
    window.render_loadout()
    assert len(window.cards.winfo_children()) == 1
    assert not window.collector.is_alive()
    assert not window.pending
    window.close()
    print("PASS: native desktop imports, Tcl, PNG decoding, Warden skins, team averages, roster widgets, player selection, loadout search, offline sample mode")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        try:
            try:
                set_process_identity()
            except (AttributeError, OSError):
                pass
            root = tk.Tk()
            root.withdraw()
            try:
                set_window_identity(root, Path(__file__).parent)
            except OSError:
                pass
            app = TrackerWindow(root, start_collector="--demo" not in sys.argv)
            if "--demo" in sys.argv:
                app.toggle_sample()
            root.deiconify()
            root.mainloop()
        except Exception:
            import traceback
            try:
                (Path(__file__).parent.parent / "desktop-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            except OSError:
                pass
            try:
                messagebox.showerror("LoadoutRoom", "The desktop interface could not start. Extract the entire ZIP to a new folder and try again.")
            except Exception:
                pass
            raise
