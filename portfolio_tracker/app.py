#!/usr/bin/env python3
import sys
import os
import gc
import faulthandler
import threading
from datetime import datetime
from typing import List, Dict, Optional

faulthandler.enable()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from portfolio_tracker.database import init_db, add_api, delete_api, get_all_apis, \
    get_trades, get_dashboard_summary, update_api
from portfolio_tracker.client import get_account_summary, OKXClient
from portfolio_tracker.trader import execute_trade



# ── Futuristic color palette ──────────────────────────────────────────
BG_PRIMARY = "#0a0a1a"
BG_CARD = "#14142e"
BG_SIDEBAR = "#0d0d24"
ACCENT = "#00d4ff"
ACCENT_HOVER = "#33ddff"
GREEN = "#00ff88"
RED = "#ff0055"
AMBER = "#ffaa00"
TEXT_PRIMARY = "#ffffff"
TEXT_SECONDARY = "#7a8ba8"
BORDER = "#1e1e44"
FONT_FAMILY = "DejaVu Sans"


class FuturisticCard(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=BG_CARD, border_color=BORDER,
                         border_width=1, corner_radius=16, **kwargs)


class TableWidget(ctk.CTkScrollableFrame):
    def __init__(self, master, columns, widths, height=200, row_height=30):
        super().__init__(master, fg_color="transparent", scrollbar_button_color="#1a1a3e",
                         scrollbar_button_hover_color=ACCENT)
        self.columns = columns
        self.widths = widths
        self.row_height = row_height
        self._rows = []
        self._selected_index = None
        self._on_select = None
        self._on_double = None
        self._on_right = None

        self._build_header()

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color="#1a1a3e", height=self.row_height, corner_radius=0)
        hdr.pack(fill="x", pady=(0, 1))
        hdr.pack_propagate(False)
        for col, w in zip(self.columns, self.widths):
            tk.Label(hdr, text=col, font=(FONT_FAMILY, 11, "bold"),
                     fg=ACCENT, bg="#1a1a3e", width=w//7).pack(side="left", expand=True)

    def clear(self):
        for frame, _ in self._rows:
            frame.destroy()
        self._rows = []
        self._selected_index = None

    def add_row(self, values):
        idx = len(self._rows)
        bg = "#14142e" if idx % 2 == 0 else "#12122a"
        row = ctk.CTkFrame(self, fg_color=bg, height=self.row_height, corner_radius=0)
        row.pack(fill="x", pady=0)
        row.pack_propagate(False)

        labels = []
        for val, w in zip(values, self.widths):
            lbl = tk.Label(row, text=str(val), font=(FONT_FAMILY, 11),
                           fg=TEXT_PRIMARY, bg=bg, padx=4)
            lbl.pack(side="left", expand=True, fill="x")
            self._bind_row_click(lbl, idx)
            labels.append(lbl)

        self._bind_row_click(row, idx)
        self._rows.append((row, labels))
        return row

    def _bind_row_click(self, widget, idx):
        widget.bind("<Button-1>", lambda e, i=idx: self._click(i))
        widget.bind("<Double-1>", lambda e, i=idx: self._double(i))
        widget.bind("<Button-3>", lambda e, i=idx: self._right(i))

    def _click(self, idx):
        self._select(idx)
        if self._on_select:
            self._on_select(idx)

    def _double(self, idx):
        self._select(idx)
        if self._on_double:
            self._on_double(idx)

    def _right(self, idx):
        self._select(idx)
        if self._on_right:
            self._on_right(idx)

    def _select(self, idx):
        if self._selected_index is not None and self._selected_index < len(self._rows):
            old_bg = "#14142e" if self._selected_index % 2 == 0 else "#12122a"
            self._rows[self._selected_index][0].configure(fg_color=old_bg)
        self._selected_index = idx
        if idx < len(self._rows):
            self._rows[idx][0].configure(fg_color="#1e1e4e")

    def get_selected_values(self):
        if self._selected_index is None or self._selected_index >= len(self._rows):
            return None
        _, labels = self._rows[self._selected_index]
        return [l.cget("text") for l in labels]


def _make_btn(master, text, command, fg_color, text_color=TEXT_PRIMARY,
              hover_color=None, font_size=13, bold=False, height=40,
              corner_radius=8, border_color=None, border_width=0):
    """Safe button replacement using CTkFrame (avoids CTkButton segfault in ctk 5.2.2)"""
    frame = ctk.CTkFrame(master, fg_color=fg_color, corner_radius=corner_radius,
                         height=height, cursor="hand2")
    if border_color:
        frame.configure(border_color=border_color, border_width=border_width)
    if height:
        frame.grid_propagate(False)
    kw = ("bold",) if bold else ()
    lbl = ctk.CTkLabel(frame, text=text, font=(FONT_FAMILY, font_size) + kw,
                       text_color=text_color)
    lbl.pack(expand=True, fill="both")
    hc = hover_color if hover_color else fg_color
    def on_enter(e): frame.configure(fg_color=hc)
    def on_leave(e): frame.configure(fg_color=fg_color)
    frame.bind("<Enter>", on_enter)
    frame.bind("<Leave>", on_leave)
    def handler(e, cb=command): cb()
    for w in [frame, lbl]:
        w.bind("<Button-1>", handler)
    return frame


class NavButton(ctk.CTkButton):
    def __init__(self, master, text, icon, **kwargs):
        super().__init__(
            master,
            text=f"  {icon}  {text}",
            anchor="w",
            height=48,
            corner_radius=12,
            fg_color="transparent",
            text_color=TEXT_SECONDARY,
            hover_color="#1a1a3e",
            font=(FONT_FAMILY, 14),
            **kwargs,
        )


# ═══════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════
class OKXPortfolioApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("OKX Portfolio Tracker")
        self.geometry("1400x850")
        self.minsize(1100, 700)
        self.configure(fg_color=BG_PRIMARY)

        init_db()

        self.current_view = None
        self.views = {}
        self.build_ui()
        self.show_view("dashboard")

    def build_ui(self):
        self.grid_columnconfigure(0, weight=0, minsize=220)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(
            self, fg_color=BG_SIDEBAR, corner_radius=0,
            border_width=0, width=220,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(5, weight=1)
        self.sidebar.grid_columnconfigure(0, weight=1)

        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent", height=80)
        logo_frame.grid(row=0, column=0, padx=20, pady=(30, 20), sticky="ew")
        logo_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            logo_frame, text="OKX", font=(FONT_FAMILY, 28, "bold"),
            text_color=ACCENT,
        ).pack()
        ctk.CTkLabel(
            logo_frame, text="Portfolio Tracker", font=(FONT_FAMILY, 11),
            text_color=TEXT_SECONDARY,
        ).pack()

        sep = ctk.CTkFrame(self.sidebar, fg_color=BORDER, height=1)
        sep.grid(row=1, column=0, padx=20, pady=5, sticky="ew")

        nav_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav_frame.grid(row=2, column=0, padx=12, pady=10, sticky="ew")
        nav_frame.grid_columnconfigure(0, weight=1)

        nav_items = [
            ("dashboard", "📊", "Dashboard"),
            ("apis", "🔑", "APIs"),
            ("trading", "📈", "Trading"),
            ("history", "📜", "Histórico"),
        ]
        self.nav_buttons = {}
        for i, (key, icon, label) in enumerate(nav_items):
            btn = NavButton(nav_frame, text=label, icon=icon,
                            command=lambda k=key: self.show_view(k))
            btn.grid(row=i, column=0, pady=3, sticky="ew")
            self.nav_buttons[key] = btn

        self.content = ctk.CTkFrame(self, fg_color=BG_PRIMARY, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    def show_view(self, view_name: str):
        for k, btn in self.nav_buttons.items():
            if k == view_name:
                btn.configure(text_color=TEXT_PRIMARY, fg_color="#1a1a3e")
            else:
                btn.configure(text_color=TEXT_SECONDARY, fg_color="transparent")

        if self.current_view and self.current_view in self.views:
            old = self.views[self.current_view]
            if hasattr(old, "on_hide"):
                old.on_hide()
            old.pack_forget()

        if view_name in self.views:
            v = self.views[view_name]
            v.pack(fill="both", expand=True, padx=30, pady=25)
            if hasattr(v, "on_show"):
                v.on_show()
            self.current_view = view_name
            return

        self.current_view = view_name

        if view_name == "dashboard":
            v = DashboardView(self.content, self)
        elif view_name == "apis":
            v = APIsView(self.content, self)
        elif view_name == "trading":
            v = TradingView(self.content, self)
        elif view_name == "history":
            v = HistoryView(self.content, self)
        self.views[view_name] = v
        if hasattr(v, "on_show"):
            v.on_show()


# ═══════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════════
class DashboardView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._alive = True
        self._timer_id = None
        self._hidden = True
        self.pack(fill="both", expand=True, padx=30, pady=25)
        self.grid_columnconfigure(0, weight=1)
        self.build_header()
        self.build_cards()
        self.build_table()
        self.bind("<Destroy>", self._on_destroy, add="+")

    def on_hide(self):
        self._hidden = True
        if self._timer_id:
            try:
                self.after_cancel(self._timer_id)
            except (tk.TclError, RuntimeError):
                pass
            self._timer_id = None

    def on_show(self):
        self._hidden = False
        self._alive = True
        self.after(100, self._delayed_refresh)

    def _delayed_refresh(self):
        if self._hidden or not self._alive:
            return
        self.refresh_data()

    def _on_destroy(self, event):
        if event.widget is self:
            self._alive = False
            if self._timer_id:
                try:
                    self.after_cancel(self._timer_id)
                except (tk.TclError, RuntimeError):
                    pass
                self._timer_id = None

    def build_header(self):
        ctk.CTkLabel(
            self, text="Dashboard",
            font=(FONT_FAMILY, 26, "bold"), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", pady=(0, 20))

    def build_cards(self):
        self.card_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.card_frame.grid(row=1, column=0, sticky="ew", pady=(0, 25))
        for i in range(4):
            self.card_frame.grid_columnconfigure(i, weight=1, uniform="cards")

        cards_data = [
            ("💰", "Total Carteiras", "0", ACCENT),
            ("📈", "Trades Abertos", "0", AMBER),
            ("💵", "PnL Total", "$0.00", GREEN),
            ("🏦", "Comissões", "$0.00", ACCENT),
        ]
        self.card_labels = {}
        for i, (icon, title, value, color) in enumerate(cards_data):
            card = FuturisticCard(self.card_frame)
            card.grid(row=0, column=i, padx=6, sticky="nsew")
            ctk.CTkLabel(card, text=icon, font=(FONT_FAMILY, 28), text_color=color).pack(anchor="w", padx=18, pady=(18, 2))
            ctk.CTkLabel(card, text=title, font=(FONT_FAMILY, 12), text_color=TEXT_SECONDARY).pack(anchor="w", padx=18)
            val_lbl = ctk.CTkLabel(card, text=value, font=(FONT_FAMILY, 22, "bold"), text_color=TEXT_PRIMARY)
            val_lbl.pack(anchor="w", padx=18, pady=(4, 18))
            self.card_labels[title] = val_lbl

    def build_table(self):
        table_frame = FuturisticCard(self)
        table_frame.grid(row=2, column=0, sticky="nsew")
        self.grid_rowconfigure(2, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(1, weight=0)
        table_frame.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            table_frame, text="Carteiras", font=(FONT_FAMILY, 16, "bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")

        columns = ("Nome", "Tipo", "Comissão", "Equity (USD)", "Posições", "PnL Não Realizado", "Conta")
        widths = [130, 70, 80, 120, 90, 150, 120]
        self.table = TableWidget(table_frame, columns, widths, height=200)
        self.table.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="nsew")

        ctk.CTkLabel(
            table_frame, text="Saldo por Par", font=(FONT_FAMILY, 16, "bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=2, column=0, padx=20, pady=(12, 8), sticky="w")

        bal_columns = ("API", "Par", "Saldo", "Disponível", "USD Equity")
        bal_widths = [130, 100, 100, 100, 120]
        self.balance_table = TableWidget(table_frame, bal_columns, bal_widths, height=200)
        self.balance_table.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="nsew")

    def refresh_data(self):
        if not self._alive or self._hidden:
            return
        try:
            apis = get_all_apis()
            summary = get_dashboard_summary()

            self.table.clear()
            self.balance_table.clear()

            total_equity = 0
            total_pnl = 0

            for api in apis:
                try:
                    data = get_account_summary(api)
                    eq = data["total_equity"]
                    pnl = data["unrealized_pnl"]
                    total_equity += eq
                    total_pnl += pnl
                    unified_str = "Unificada" if data.get("unified") else "Clássica"
                    self.table.add_row((
                        api["name"],
                        api["account_type"].upper(),
                        f"{api['commission_rate']:.1f}%",
                        f"${eq:,.2f}",
                        str(data["position_count"]),
                        f"${pnl:+,.2f}",
                        unified_str,
                    ))
                    for b in data.get("balances", []):
                        ccy = b["currency"]
                        eq_usd = b.get("usd_eq", 0)
                        avail = b.get("available", 0)
                        total_bal = b.get("equity", 0)
                        self.balance_table.add_row((
                            api["name"],
                            ccy,
                            f"{total_bal:.6f}",
                            f"{avail:.6f}",
                            f"${eq_usd:,.2f}",
                        ))
                except Exception as e:
                    self.table.add_row((
                        api["name"], api["account_type"].upper(),
                        f"{api['commission_rate']:.1f}%",
                        f"⚠️ {e}", "-", "-", "-",
                    ))

            self.card_labels["Total Carteiras"].configure(text=str(len(apis)))
            self.card_labels["Trades Abertos"].configure(text=str(summary["open_trades"]))

            pnl_color = GREEN if summary["total_pnl"] >= 0 else RED
            self.card_labels["PnL Total"].configure(
                text=f"${summary['total_pnl']:+,.2f}", text_color=pnl_color)
            self.card_labels["Comissões"].configure(
                text=f"${summary['total_commission']:+,.2f}")
        except Exception:
            pass

        if not self._hidden:
            self._timer_id = self.after(30000, self.refresh_data)


# ═══════════════════════════════════════════════════════════════════════
#  APIs VIEW
# ═══════════════════════════════════════════════════════════════════════
class APIsView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.pack(fill="both", expand=True, padx=30, pady=25)
        self.grid_columnconfigure(0, weight=1)
        self.build_header()
        self.build_form()
        self.build_table()

    def build_header(self):
        ctk.CTkLabel(
            self, text="Gerenciar APIs",
            font=(FONT_FAMILY, 26, "bold"), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", pady=(0, 20))

    def build_form(self):
        form = FuturisticCard(self)
        form.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        form.grid_columnconfigure(1, weight=1)

        self.entries = {}
        row = 0

        for label in ("Nome", "API Key", "Secret Key", "Passphrase"):
            ctk.CTkLabel(form, text=label, font=(FONT_FAMILY, 12),
                         text_color=TEXT_SECONDARY).grid(row=row, column=0, padx=(16, 4), pady=(12, 2), sticky="w")
            entry = ctk.CTkEntry(
                form, placeholder_text=f"Digite {label.lower()}",
                fg_color=BG_PRIMARY, border_color=BORDER, font=(FONT_FAMILY, 12),
            )
            if label == "Passphrase":
                entry.configure(show="*")
            entry.grid(row=row, column=1, columnspan=2, padx=(4, 16), pady=(12, 2), sticky="ew")
            self.entries[label] = entry
            row += 1

        ctk.CTkLabel(form, text="Comissão %", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).grid(row=row, column=0, padx=(16, 4), pady=(12, 2), sticky="w")
        self.entries["Comissão %"] = ctk.CTkEntry(
            form, placeholder_text="0.0",
            fg_color=BG_PRIMARY, border_color=BORDER, font=(FONT_FAMILY, 12),
        )
        self.entries["Comissão %"].grid(row=row, column=1, columnspan=2, padx=(4, 16), pady=(12, 2), sticky="ew")
        row += 1

        mode_frame = ctk.CTkFrame(form, fg_color="transparent")
        mode_frame.grid(row=row, column=0, columnspan=3, pady=(4, 8), sticky="ew")
        self._simulated = ctk.BooleanVar(value=False)
        self._demo_btn = _make_btn(mode_frame, "🔵 Conta Real", self._toggle_real,
                                   fg_color=ACCENT, text_color="#000000", hover_color=ACCENT_HOVER,
                                   font_size=13, bold=True, height=34, corner_radius=8)
        self._demo_btn.pack(side="left", padx=(16, 6))
        self._real_btn = _make_btn(mode_frame, "Conta Demo", self._toggle_demo,
                                   fg_color="#333355", text_color=TEXT_SECONDARY, hover_color="#444466",
                                   font_size=13, height=34, corner_radius=8)
        self._real_btn.pack(side="left", padx=(6, 16))
        row += 1

        _make_btn(form, "+ Adicionar API", self.add_api,
                  fg_color=ACCENT, text_color="#000000", hover_color=ACCENT_HOVER,
                  font_size=13, bold=True, height=40, corner_radius=10,
        ).grid(row=row, column=0, columnspan=3, padx=16, pady=(8, 16), sticky="ew")

    def build_table(self):
        table_frame = FuturisticCard(self)
        table_frame.grid(row=2, column=0, sticky="nsew")
        self.grid_rowconfigure(2, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            table_frame, text="APIs Cadastradas",
            font=(FONT_FAMILY, 16, "bold"), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")

        columns = ("ID", "Nome", "Tipo", "Comissão", "Simulada", "Criada em")
        widths = [50, 180, 80, 80, 80, 150]
        self.table = TableWidget(table_frame, columns, widths, height=220)
        self.table.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")

        self.table._on_select = self.on_row_click
        self.table._on_double = self.on_double_click
        self.table._on_right = self.on_right_click

        btn_frame = ctk.CTkFrame(table_frame, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=16, pady=(8, 16), sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        editar_frame = ctk.CTkFrame(btn_frame, fg_color="transparent", corner_radius=8, height=40,
                                     cursor="hand2", border_color=ACCENT, border_width=1)
        editar_frame.grid(row=0, column=0, padx=(0, 6), sticky="nsew")
        editar_frame.grid_propagate(False)
        ctk.CTkLabel(editar_frame, text="✏ Editar", font=(FONT_FAMILY, 12),
                      text_color=ACCENT).pack(expand=True, fill="both")
        for w in [editar_frame] + editar_frame.winfo_children():
            w.bind("<Button-1>", lambda e: self.edit_selected())
            w.bind("<Enter>", lambda e: editar_frame.configure(fg_color="#1a1a3e"))
            w.bind("<Leave>", lambda e: editar_frame.configure(fg_color="transparent"))

        excluir_frame = ctk.CTkFrame(btn_frame, fg_color="#cc2255", corner_radius=8, height=40, cursor="hand2")
        excluir_frame.grid(row=0, column=1, padx=(6, 0), sticky="nsew")
        excluir_frame.grid_propagate(False)
        ctk.CTkLabel(excluir_frame, text="🗑 Excluir", font=(FONT_FAMILY, 12, "bold"),
                      text_color=TEXT_PRIMARY).pack(expand=True, fill="both")
        for w in [excluir_frame] + excluir_frame.winfo_children():
            w.bind("<Button-1>", lambda e: self.delete_selected())
            w.bind("<Enter>", lambda e: excluir_frame.configure(fg_color="#ee3366"))
            w.bind("<Leave>", lambda e: excluir_frame.configure(fg_color="#cc2255"))

        self.refresh_table()

    def refresh_table(self):
        self.table.clear()
        apis = get_all_apis()
        for api in apis:
            self.table.add_row((
                str(api["id"]),
                api["name"],
                api["account_type"].upper(),
                f"{api['commission_rate']:.1f}%",
                "Sim" if api["simulated"] else "Não",
                api["created_at"][:19],
            ))

    def on_row_click(self, idx):
        pass

    def on_right_click(self, idx):
        vals = self.table.get_selected_values()
        if not vals:
            return
        menu = tk.Menu(self, tearoff=0, bg=BG_CARD, fg=TEXT_PRIMARY,
                       activebackground=ACCENT, activeforeground="#000000",
                       font=(FONT_FAMILY, 12))
        menu.add_command(label=f"✏ Editar '{vals[1]}'", command=self.edit_selected)
        menu.add_separator()
        menu.add_command(label=f"🗑 Excluir '{vals[1]}'", command=self.delete_selected)
        try:
            menu.post(self.winfo_pointerx(), self.winfo_pointery())
        except Exception:
            pass

    def get_selected_api_id(self):
        vals = self.table.get_selected_values()
        if not vals:
            messagebox.showwarning("Atenção", "Clique em uma API na tabela primeiro")
            return None
        return int(vals[0]), vals[1]

    def delete_selected(self):
        result = self.get_selected_api_id()
        if result is None:
            return
        api_id, name = result
        if messagebox.askyesno("Excluir", f"Excluir API '{name}'?"):
            delete_api(api_id)
            self.refresh_table()

    def edit_selected(self):
        result = self.get_selected_api_id()
        if result is None:
            return
        api_id, old_name = result

        api_data = None
        for a in get_all_apis():
            if a["id"] == api_id:
                api_data = a
                break
        if not api_data:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Editar API")
        dialog.geometry("420x360")
        dialog.configure(fg_color=BG_PRIMARY)
        dialog.transient(self)

        ctk.CTkLabel(dialog, text="Editar API", font=(FONT_FAMILY, 18, "bold"),
                     text_color=TEXT_PRIMARY).pack(pady=(20, 16))

        ctk.CTkLabel(dialog, text="Nome:", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).pack(anchor="w", padx=30)
        name_entry = ctk.CTkEntry(dialog, font=(FONT_FAMILY, 13),
                                  fg_color=BG_PRIMARY, border_color=BORDER)
        name_entry.pack(fill="x", padx=30, pady=(4, 8))
        name_entry.insert(0, old_name)

        ctk.CTkLabel(dialog, text="Passphrase:", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).pack(anchor="w", padx=30)
        pass_entry = ctk.CTkEntry(dialog, font=(FONT_FAMILY, 13),
                                  fg_color=BG_PRIMARY, border_color=BORDER, show="*")
        pass_entry.pack(fill="x", padx=30, pady=(4, 8))
        pass_entry.insert(0, api_data.get("passphrase", ""))

        ctk.CTkLabel(dialog, text="Comissão %:", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).pack(anchor="w", padx=30)
        comm_entry = ctk.CTkEntry(dialog, font=(FONT_FAMILY, 13),
                                  fg_color=BG_PRIMARY, border_color=BORDER)
        comm_entry.pack(fill="x", padx=30, pady=(4, 16))
        comm_entry.insert(0, f"{api_data['commission_rate']:.1f}")

        def save():
            new_name = name_entry.get().strip()
            new_pass = pass_entry.get().strip()
            try:
                new_comm = float(comm_entry.get().strip())
            except ValueError:
                new_comm = 0.0
            if new_name:
                update_api(api_id, name=new_name, passphrase=new_pass, commission_rate=new_comm)
                self.refresh_table()
            dialog.destroy()

        dialog.wait_visibility()
        dialog.grab_set()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=(0, 20))
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        _make_btn(btn_frame, "Cancelar", dialog.destroy,
                  fg_color="#333355", text_color=TEXT_PRIMARY, hover_color="#444466",
                  font_size=13, height=38, corner_radius=8,
        ).grid(row=0, column=0, padx=(0, 6), sticky="ew")

        _make_btn(btn_frame, "Salvar", save,
                  fg_color=ACCENT, text_color="#000000", hover_color=ACCENT_HOVER,
                  font_size=13, bold=True, height=38, corner_radius=8,
        ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

    def _set_mode_buttons(self, real: bool = True):
        if real:
            self._demo_btn.configure(fg_color=ACCENT)
            self._demo_btn.winfo_children()[0].configure(text="🔵 Conta Real", text_color="#000000")
            self._real_btn.configure(fg_color="#333355")
            self._real_btn.winfo_children()[0].configure(text="Conta Demo", text_color=TEXT_SECONDARY)
        else:
            self._demo_btn.configure(fg_color="#333355")
            self._demo_btn.winfo_children()[0].configure(text="Conta Real", text_color=TEXT_SECONDARY)
            self._real_btn.configure(fg_color=AMBER)
            self._real_btn.winfo_children()[0].configure(text="🟠 Conta Demo", text_color="#000000")

    def _toggle_real(self):
        self._simulated.set(False)
        self._set_mode_buttons(real=True)

    def _toggle_demo(self):
        self._simulated.set(True)
        self._set_mode_buttons(real=False)

    def on_double_click(self, idx):
        self.edit_selected()

    def add_api(self):
        name = self.entries["Nome"].get().strip()
        api_key = self.entries["API Key"].get().strip()
        secret = self.entries["Secret Key"].get().strip()
        passphrase = self.entries["Passphrase"].get().strip()
        if not all([name, api_key, secret]):
            messagebox.showwarning("Atenção", "Preencha Nome, API Key e Secret Key!")
            return
        try:
            comm = float(self.entries["Comissão %"].get() or 0)
        except ValueError:
            comm = 0.0
        simulated = self._simulated.get()
        try:
            client = OKXClient(api_key, secret, passphrase, simulated=simulated)
            account_type = client.detect_account_type()
        except Exception:
            account_type = "spot"
        add_api(name, api_key, secret, passphrase, account_type, comm, simulated=simulated)
        for e in self.entries.values():
            e.delete(0, "end")
        self._simulated.set(False)
        self._set_mode_buttons(real=True)
        self.refresh_table()
        messagebox.showinfo("Sucesso", f"API '{name}' adicionada! (Tipo: {account_type.upper()})")


# ═══════════════════════════════════════════════════════════════════════
#  TRADING VIEW
# ═══════════════════════════════════════════════════════════════════════
class TradingView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._alive = True
        self.pack(fill="both", expand=True, padx=30, pady=25)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.build_header()
        self.build_controls()
        self.build_log()
        self.bind("<Destroy>", lambda e: setattr(self, '_alive', False) if e.widget is self else None, add="+")

    def build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="Painel de Trading",
            font=(FONT_FAMILY, 26, "bold"), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        self.balance_frame = ctk.CTkFrame(header, fg_color="#14142e", corner_radius=10)
        self.balance_frame.grid(row=0, column=1, sticky="e", padx=(20, 0))
        self.balance_label = ctk.CTkLabel(self.balance_frame, text="💰 Saldo: --",
                                          font=(FONT_FAMILY, 14, "bold"), text_color=GREEN)
        self.balance_label.pack(padx=16, pady=6)

        self._update_balance()

    def build_controls(self):
        controls = FuturisticCard(self)
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        controls.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        COMMON_PAIRS = [
            "BTC-USD-SWAP", "ETH-USD-SWAP", "SOL-USD-SWAP", "XRP-USD-SWAP",
            "ADA-USD-SWAP", "DOGE-USD-SWAP", "AVAX-USD-SWAP", "DOT-USD-SWAP",
            "LINK-USD-SWAP", "MATIC-USD-SWAP",
        ]
        ctk.CTkLabel(controls, text="Instrumento", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).grid(row=0, column=0, padx=12, pady=(16, 2), sticky="w")
        self.inst_var = ctk.StringVar(value="BTC-USD")
        self.inst_entry = ctk.CTkComboBox(controls, values=COMMON_PAIRS, variable=self.inst_var,
                                          fg_color=BG_PRIMARY, border_color=BORDER,
                                          button_color=ACCENT, dropdown_fg_color=BG_CARD,
                                          font=(FONT_FAMILY, 12))
        self.inst_entry.grid(row=1, column=0, padx=12, pady=(0, 16), sticky="ew")

        ctk.CTkLabel(controls, text="Direção", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).grid(row=0, column=1, padx=12, pady=(16, 2), sticky="w")
        self.direction_var = ctk.StringVar(value="long")
        dir_frame = ctk.CTkFrame(controls, fg_color="transparent")
        dir_frame.grid(row=1, column=1, padx=12, pady=(0, 16), sticky="ew")

        self.long_btn = ctk.CTkFrame(dir_frame, fg_color=GREEN, corner_radius=8,
                                     height=32, width=80, cursor="hand2")
        self.long_btn.pack(side="left", padx=(0, 4))
        self.long_btn.pack_propagate(False)
        self.long_lbl = ctk.CTkLabel(self.long_btn, text="LONG",
                                     font=(FONT_FAMILY, 12, "bold"), text_color="#000000")
        self.long_lbl.pack(expand=True, fill="both")
        for w in [self.long_btn, self.long_lbl]:
            w.bind("<Button-1>", lambda e: self.set_direction("long"))

        self.short_btn = ctk.CTkFrame(dir_frame, fg_color="#333355", corner_radius=8,
                                      height=32, width=80, cursor="hand2")
        self.short_btn.pack(side="left", padx=(4, 0))
        self.short_btn.pack_propagate(False)
        self.short_lbl = ctk.CTkLabel(self.short_btn, text="SHORT",
                                      font=(FONT_FAMILY, 12, "bold"), text_color=TEXT_PRIMARY)
        self.short_lbl.pack(expand=True, fill="both")
        for w in [self.short_btn, self.short_lbl]:
            w.bind("<Button-1>", lambda e: self.set_direction("short"))

        ctk.CTkLabel(controls, text="Valor Entrada ($)", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).grid(row=0, column=2, padx=12, pady=(16, 2), sticky="w")
        self.amount_entry = ctk.CTkEntry(controls, placeholder_text="100.00",
                                         fg_color=BG_PRIMARY, border_color=BORDER, font=(FONT_FAMILY, 12))
        self.amount_entry.grid(row=1, column=2, padx=12, pady=(0, 16), sticky="ew")

        ctk.CTkLabel(controls, text="Alavancagem", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).grid(row=0, column=3, padx=12, pady=(16, 2), sticky="w")
        self.leverage_var = ctk.StringVar(value="1x")
        ctk.CTkComboBox(controls, values=[f"{x}x" for x in range(1, 26)],
                        variable=self.leverage_var,
                        fg_color=BG_PRIMARY, border_color=BORDER, button_color=ACCENT,
                        dropdown_fg_color=BG_CARD, font=(FONT_FAMILY, 12),
        ).grid(row=1, column=3, padx=12, pady=(0, 16), sticky="ew")

        ctk.CTkLabel(controls, text="Tipo Ordem", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).grid(row=0, column=4, padx=12, pady=(16, 2), sticky="w")
        self.order_type_var = ctk.StringVar(value="market")
        ctk.CTkComboBox(controls, values=["market", "limit"], variable=self.order_type_var,
                        fg_color=BG_PRIMARY, border_color=BORDER, button_color=ACCENT,
                        dropdown_fg_color=BG_CARD, font=(FONT_FAMILY, 12),
        ).grid(row=1, column=4, padx=12, pady=(0, 16), sticky="ew")

        ctk.CTkLabel(controls, text="Alvo", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).grid(row=0, column=5, padx=12, pady=(16, 2), sticky="w")
        self.target_var = ctk.StringVar(value="Todas")
        self.target_combo = ctk.CTkComboBox(controls, values=self.get_api_names(),
                                            variable=self.target_var,
                                            fg_color=BG_PRIMARY, border_color=BORDER,
                                            button_color=ACCENT, dropdown_fg_color=BG_CARD,
                                            font=(FONT_FAMILY, 12))
        self.target_combo.grid(row=1, column=5, padx=12, pady=(0, 16), sticky="ew")
        self.after(100, self._fill_targets)

        tp_sl_frame = ctk.CTkFrame(controls, fg_color="transparent")
        tp_sl_frame.grid(row=2, column=0, columnspan=6, pady=(0, 8), sticky="ew")
        for i in range(6):
            tp_sl_frame.grid_columnconfigure(i, weight=1)

        ctk.CTkLabel(tp_sl_frame, text="Take Profit ($)", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).grid(row=0, column=0, padx=12, pady=(4, 2), sticky="w")
        self.tp_entry = ctk.CTkEntry(tp_sl_frame, placeholder_text="85000.00",
                                     fg_color=BG_PRIMARY, border_color=BORDER, font=(FONT_FAMILY, 12))
        self.tp_entry.grid(row=1, column=0, padx=12, pady=(0, 4), sticky="ew")

        ctk.CTkLabel(tp_sl_frame, text="Stop Loss ($)", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).grid(row=0, column=1, padx=12, pady=(4, 2), sticky="w")
        self.sl_entry = ctk.CTkEntry(tp_sl_frame, placeholder_text="75000.00",
                                     fg_color=BG_PRIMARY, border_color=BORDER, font=(FONT_FAMILY, 12))
        self.sl_entry.grid(row=1, column=1, padx=12, pady=(0, 4), sticky="ew")

        ctk.CTkLabel(tp_sl_frame, text="", font=(FONT_FAMILY, 12),
                     text_color=TEXT_SECONDARY).grid(row=0, column=2, padx=12, pady=(4, 2), sticky="w")
        ctk.CTkLabel(tp_sl_frame, text="Inverso", font=(FONT_FAMILY, 13, "bold"),
                     text_color=ACCENT).grid(row=1, column=2, padx=12, pady=(0, 4), sticky="ew")

        action_frame = ctk.CTkFrame(controls, fg_color="transparent")
        action_frame.grid(row=3, column=0, columnspan=6, pady=(8, 16), sticky="ew")
        for i in range(4):
            action_frame.grid_columnconfigure(i, weight=1)

        self._exec_frame = ctk.CTkFrame(action_frame, fg_color=ACCENT, corner_radius=12,
                                        height=50, cursor="hand2")
        self._exec_frame.grid_propagate(False)
        self._exec_label = ctk.CTkLabel(self._exec_frame, text="⚡ EXECUTAR",
                                        font=(FONT_FAMILY, 16, "bold"), text_color="#000000")
        self._exec_label.pack(expand=True, fill="both")
        for w in [self._exec_frame, self._exec_label]:
            w.bind("<Button-1>", lambda e: self.execute())
            w.bind("<Enter>", lambda e: self._exec_frame.configure(fg_color=ACCENT_HOVER))
            w.bind("<Leave>", lambda e: self._exec_frame.configure(fg_color=ACCENT))
        self._exec_frame.grid(row=0, column=0, padx=(12, 6), sticky="ew")

        self.close_btn = _make_btn(action_frame, "🔒 Fechar Tudo", self.close_all_positions,
                                   fg_color="#ff0055", text_color="#ffffff", hover_color="#ff3366",
                                   font_size=13, bold=True, corner_radius=12, height=50)
        self.close_btn.grid(row=0, column=1, padx=(6, 6), sticky="ew")

        self.tpsl_btn = _make_btn(action_frame, "🎯 Editar TP/SL", self.edit_tp_sl,
                                  fg_color="#ffaa00", text_color="#000000", hover_color="#ffcc33",
                                  font_size=13, bold=True, corner_radius=12, height=50)
        self.tpsl_btn.grid(row=0, column=2, padx=(6, 6), sticky="ew")

        self.refresh_btn = _make_btn(action_frame, "🔄 Atualizar APIs", self.refresh_targets,
                                     fg_color="transparent", text_color=ACCENT, hover_color="#1a1a3e",
                                     font_size=13, corner_radius=12, border_color=ACCENT, border_width=1)
        self.refresh_btn.grid(row=0, column=3, padx=(6, 12), sticky="ew")

    def _fill_targets(self):
        self.target_combo.configure(values=self.get_api_names())

    def get_api_names(self):
        apis = get_all_apis()
        return ["Todas"] + [a["name"] for a in apis]

    def refresh_targets(self):
        self.target_combo.configure(values=self.get_api_names())
        self.target_combo.set("Todas")

    def set_direction(self, direction: str):
        self.direction_var.set(direction)
        if direction == "long":
            self.long_btn.configure(fg_color=GREEN)
            self.long_lbl.configure(text_color="#000000")
            self.short_btn.configure(fg_color="#333355")
            self.short_lbl.configure(text_color=TEXT_PRIMARY)
        else:
            self.short_btn.configure(fg_color=RED)
            self.short_lbl.configure(text_color="#ffffff")
            self.long_btn.configure(fg_color="#333355")
            self.long_lbl.configure(text_color=TEXT_PRIMARY)

    def _update_balance(self):
        try:
            apis = get_all_apis()
            if not apis:
                return
            api = apis[0]
            from portfolio_tracker.client import get_account_summary
            data = get_account_summary(api)
            eq = data.get("total_equity", 0)
            pnl = data.get("unrealized_pnl", 0)
            color = GREEN if pnl >= 0 else RED
            self.balance_label.configure(
                text=f"💰 ${eq:,.2f}  |  PnL: ${pnl:+,.2f}",
                text_color=color,
            )
        except Exception:
            pass

    def build_log(self):
        log_frame = FuturisticCard(self)
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            log_frame, text="Log de Execução",
            font=(FONT_FAMILY, 16, "bold"), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")

        self.log_text = ctk.CTkTextbox(log_frame, fg_color=BG_PRIMARY,
                                       border_color=BORDER, border_width=1,
                                       corner_radius=8, font=("Consolas", 12),
                                       text_color=TEXT_SECONDARY)
        self.log_text.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        self.log("Sistema pronto. Configure o instrumento e execute.")

    def log(self, msg: str, color: str = TEXT_SECONDARY):
        if not self._alive:
            return
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert("end", f"[{ts}] {msg}\n")
            self.log_text.see("end")
        except (tk.TclError, RuntimeError):
            pass

    def execute(self):
        inst_id = self.inst_var.get().strip().upper()
        if "-" not in inst_id:
            for s in ["USDT", "USD", "BTC", "ETH"]:
                if inst_id.endswith(s) and len(inst_id) > len(s):
                    base = inst_id[:-len(s)]
                    inst_id = f"{base}-{s}"
                    if s == "USD":
                        inst_id += "-SWAP"
                    break
        if "-" not in inst_id:
            messagebox.showwarning("Atenção", "Instrumento inválido (ex: BTC-USD-SWAP)")
            return

        direction = self.direction_var.get()
        target = self.target_var.get()

        try:
            entry_amount = float(self.amount_entry.get().strip())
            if entry_amount <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Atenção", "Digite um valor de entrada válido (ex: 100.00)")
            return

        leverage = int(self.leverage_var.get().replace("x", ""))
        td_mode = "inverse"

        tp_price = None
        sl_price = None
        try:
            tp_val = self.tp_entry.get().strip()
            if tp_val:
                tp_price = float(tp_val)
                if tp_price <= 0:
                    tp_price = None
        except ValueError:
            pass
        try:
            sl_val = self.sl_entry.get().strip()
            if sl_val:
                sl_price = float(sl_val)
                if sl_price <= 0:
                    sl_price = None
        except ValueError:
            pass

        apis = get_all_apis()
        if not apis:
            messagebox.showwarning("Atenção", "Nenhuma API cadastrada")
            return

        if target != "Todas":
            apis = [a for a in apis if a["name"] == target]
            if not apis:
                messagebox.showwarning("Atenção", f"API '{target}' não encontrada")
                return

        log_msg = f"🚀 {direction.upper()} {inst_id} | ${entry_amount:.2f} x{leverage} | Inverso"
        if tp_price:
            log_msg += f" | TP: ${tp_price:.2f}"
        if sl_price:
            log_msg += f" | SL: ${sl_price:.2f}"
        self._exec_label.configure(text="⏳ Executando...")
        self._exec_frame.configure(cursor="watch")
        self.log(log_msg, ACCENT)

        alive_ref = self

        def run():
            results = []
            for api in apis:
                try:
                    result = execute_trade(api, inst_id, direction, entry_amount,
                                           leverage=leverage, tp_price=tp_price, sl_price=sl_price,
                                           td_mode=td_mode)
                    results.append((api["name"], result))
                except Exception as e:
                    results.append((api["name"], {"success": False, "error": str(e)}))
            if alive_ref._alive:
                try:
                    self.after(0, lambda: self.show_results(results, inst_id, direction))
                except (tk.TclError, RuntimeError):
                    pass

        threading.Thread(target=run, daemon=True).start()

    def show_results(self, results, inst_id, direction):
        if not self._alive:
            return
        try:
            for name, result in results:
                if result["success"]:
                    self.log(
                        f"✅ {name}: {direction.upper()} {inst_id} | "
                        f"Preço: ${result['entry_price']:.2f} | "
                        f"Size: {result['size']:.6f} | "
                        f"Lever: {result.get('leverage', 1)}x | "
                        f"Order: {result['order_id']}",
                        GREEN,
                    )
                else:
                    self.log(f"❌ {name}: {result.get('error', 'Erro')}", RED)

            ok_count = sum(1 for _, r in results if r["success"])
            self.log(f"📊 Resultado: {ok_count}/{len(results)} ordens executadas", AMBER)
            self._exec_label.configure(text="⚡ EXECUTAR")
            self._exec_frame.configure(cursor="hand2")
        except (tk.TclError, RuntimeError):
            pass

    def _get_trader_for_apis(self):
        apis = get_all_apis()
        target = self.target_var.get()
        if target != "Todas":
            apis = [a for a in apis if a["name"] == target]
        return apis

    def close_all_positions(self):
        apis = self._get_trader_for_apis()
        if not apis:
            messagebox.showwarning("Atenção", "Nenhuma API selecionada")
            return

        if not messagebox.askyesno("Confirmar", "Fechar TODAS as posições e cancelar TODAS as ordens pendentes?"):
            return

        self.log("🔒 Fechando posições e cancelando ordens...", AMBER)
        alive_ref = self

        def run():
            from portfolio_tracker.trader import Trader
            for api in apis:
                try:
                    trader = Trader(api["api_key"], api["secret_key"],
                                    api["passphrase"], api.get("simulated", False))

                    # 1. Cancel pending regular orders
                    pending = trader.get_pending_orders()
                    if pending:
                        cancel_list = [{"instId": o["instId"], "ordId": o["ordId"]} for o in pending]
                        r = trader.cancel_orders(cancel_list)
                        if alive_ref._alive:
                            self.after(0, lambda n=api["name"], c=r.get("code"):
                                self.log(f"  {n}: {len(cancel_list)} ordem(ns) cancelada(s) {'✅' if c=='0' else '❌'}",
                                         GREEN if c=='0' else RED))

                    # 2. Cancel algo orders (TP/SL)
                    algos = trader.get_algo_orders()
                    if algos:
                        cancel_algos = [{"algoId": a["algoId"], "instId": a["instId"]} for a in algos]
                        r = trader.cancel_algo_orders(cancel_algos)
                        if alive_ref._alive:
                            self.after(0, lambda n=api["name"], c=r.get("code"):
                                self.log(f"  {n}: {len(cancel_algos)} TP/SL cancelado(s) {'✅' if c=='0' else '❌'}",
                                         GREEN if c=='0' else RED))

                    # 3. Close open positions
                    positions = trader.get_positions()
                    if positions:
                        for pos in positions:
                            inst_id = pos["instId"]
                            result = trader.close_position(inst_id)
                            if alive_ref._alive:
                                code = result.get("code")
                                msg = result.get("msg", "")
                                data_list = result.get("data", [])
                                s_msg = data_list[0].get("sMsg", "") if data_list else ""
                                self.after(0, lambda n=api["name"], i=inst_id, c=code, m=s_msg or msg:
                                    self.log(f"  {n} {i}: {'✅' if c=='0' else '❌'} {m}",
                                             GREEN if c=='0' else RED))
                    else:
                        if alive_ref._alive:
                            self.after(0, lambda n=api["name"]:
                                self.log(f"  {n}: Nenhuma posição aberta", TEXT_SECONDARY))
                except Exception as e:
                    if alive_ref._alive:
                        self.after(0, lambda n=api["name"], e=e:
                            self.log(f"  {n}: Erro: {e}", RED))
            if alive_ref._alive:
                self.after(0, lambda: self.log("🔒 Fechamento concluído", AMBER))

        threading.Thread(target=run, daemon=True).start()

    def edit_tp_sl(self):
        inst_id = self.inst_var.get().strip().upper()
        if "-" not in inst_id:
            messagebox.showwarning("Atenção", "Instrumento inválido (ex: BTC-USD-SWAP)")
            return

        tp_val = self.tp_entry.get().strip()
        sl_val = self.sl_entry.get().strip()
        if not tp_val and not sl_val:
            messagebox.showwarning("Atenção", "Defina ao menos TP ou SL")
            return

        tp_price = float(tp_val) if tp_val else 0
        sl_price = float(sl_val) if sl_val else 0

        apis = self._get_trader_for_apis()
        if not apis:
            messagebox.showwarning("Atenção", "Nenhuma API selecionada")
            return

        if not messagebox.askyesno("Confirmar", f"Atualizar TP/SL em {inst_id}?\nTP: ${tp_price:.2f}  SL: ${sl_price:.2f}"):
            return

        self.log(f"🎯 Atualizando TP/SL {inst_id}...", AMBER)
        alive_ref = self

        def run():
            from portfolio_tracker.trader import Trader
            direction = self.direction_var.get()
            close_side = "sell" if direction == "long" else "buy"

            for api in apis:
                try:
                    trader = Trader(api["api_key"], api["secret_key"],
                                    api["passphrase"], api.get("simulated", False))

                    algos = trader.get_algo_orders(inst_id=inst_id)
                    cancel_list = []
                    current_sz = ""
                    for algo in algos:
                        if algo.get("instId") == inst_id and algo.get("algoId"):
                            cancel_list.append({"algoId": algo["algoId"], "instId": inst_id})
                            if not current_sz:
                                current_sz = algo.get("sz", "")

                    if cancel_list:
                        trader.cancel_algo_orders(cancel_list)

                    if not current_sz:
                        positions = trader.get_positions()
                        for pos in positions:
                            if pos["instId"] == inst_id:
                                current_sz = pos.get("availPos", pos.get("pos", ""))

                    if current_sz and float(current_sz) > 0:
                        tp_px = str(round(tp_price, 2)) if tp_price > 0 else ""
                        sl_px = str(round(sl_price, 2)) if sl_price > 0 else ""
                        result = trader.set_tp_sl(inst_id, close_side, current_sz,
                                                   tp_px=tp_px, sl_px=sl_px)
                        code = result.get("code")
                        s_msg = ""
                        if result.get("data"):
                            s_msg = result["data"][0].get("sMsg", "")
                        if alive_ref._alive:
                            self.after(0, lambda n=api["name"], c=code, m=s_msg:
                                self.log(f"  {n}: {'✅' if c=='0' else '❌'} TP/SL atualizado {m}",
                                         GREEN if c=='0' else RED))
                    else:
                        if alive_ref._alive:
                            self.after(0, lambda n=api["name"]:
                                self.log(f"  {n}: Nenhuma posição encontrada para {inst_id}", RED))
                except Exception as e:
                    if alive_ref._alive:
                        self.after(0, lambda n=api["name"], e=e:
                            self.log(f"  {n}: Erro: {e}", RED))
            if alive_ref._alive:
                self.after(0, lambda: self.log("🎯 TP/SL atualizado", AMBER))

        threading.Thread(target=run, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════
#  HISTORY VIEW
# ═══════════════════════════════════════════════════════════════════════
class HistoryView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.pack(fill="both", expand=True, padx=30, pady=25)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.build_header()
        self.build_filters()
        self.build_table()

    def build_header(self):
        ctk.CTkLabel(
            self, text="Histórico de Trades",
            font=(FONT_FAMILY, 26, "bold"), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", pady=(0, 20))

    def build_filters(self):
        filter_frame = FuturisticCard(self)
        filter_frame.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        filter_frame.grid_columnconfigure((0, 1, 2), weight=0)
        filter_frame.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(filter_frame, text="Filtrar por API:",
                     font=(FONT_FAMILY, 12), text_color=TEXT_SECONDARY
                     ).grid(row=0, column=0, padx=(20, 8), pady=16, sticky="w")

        self.filter_var = ctk.StringVar(value="Todas")
        self.filter_combo = ctk.CTkComboBox(
            filter_frame, values=self.get_filter_options(),
            variable=self.filter_var, fg_color=BG_PRIMARY, border_color=BORDER,
            button_color=ACCENT, dropdown_fg_color=BG_CARD, font=(FONT_FAMILY, 12), width=180,
        )
        self.filter_combo.grid(row=0, column=1, padx=8, pady=16, sticky="w")

        ctk.CTkLabel(filter_frame, text="Status:",
                     font=(FONT_FAMILY, 12), text_color=TEXT_SECONDARY
                     ).grid(row=0, column=2, padx=(20, 8), pady=16, sticky="w")
        self.status_var = ctk.StringVar(value="Todos")
        self.status_combo = ctk.CTkComboBox(
            filter_frame, values=["Todos", "open", "closed"],
            variable=self.status_var, fg_color=BG_PRIMARY, border_color=BORDER,
            button_color=ACCENT, dropdown_fg_color=BG_CARD, font=(FONT_FAMILY, 12), width=120,
        )
        self.status_combo.grid(row=0, column=3, padx=8, pady=16, sticky="w")

        _make_btn(filter_frame, "🔍 Filtrar", self.refresh_table,
                  fg_color=ACCENT, text_color="#000000", hover_color=ACCENT_HOVER,
                  font_size=13, bold=True, corner_radius=8, height=36,
        ).grid(row=0, column=4, padx=(20, 20), pady=16, sticky="e")

    def get_filter_options(self):
        apis = get_all_apis()
        return ["Todas"] + [a["name"] for a in apis]

    def build_table(self):
        table_frame = FuturisticCard(self)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            table_frame, text="Trades", font=(FONT_FAMILY, 16, "bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")

        summary_frame = ctk.CTkFrame(table_frame, fg_color="transparent")
        summary_frame.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="ew")
        self.total_pnl_lbl = ctk.CTkLabel(summary_frame, text="PnL Total: $0.00",
                                          font=(FONT_FAMILY, 14, "bold"), text_color=GREEN)
        self.total_pnl_lbl.pack(side="left", padx=(0, 20))
        self.total_comm_lbl = ctk.CTkLabel(summary_frame, text="Comissões: $0.00",
                                           font=(FONT_FAMILY, 14, "bold"), text_color=ACCENT)
        self.total_comm_lbl.pack(side="left")

        columns = ("ID", "API", "Instrumento", "Direção", "Size", "Entrada",
                   "Saída", "PnL", "PnL%", "Comissão", "Status", "Data")
        widths = [40, 100, 100, 70, 80, 90, 90, 90, 70, 90, 70, 140]
        self.table = TableWidget(table_frame, columns, widths, height=400)
        self.table.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="nsew")

        self.after(100, self.refresh_table)

    def refresh_table(self):
        self.table.clear()

        filter_name = self.filter_var.get()
        filter_status = self.status_var.get()

        apis = get_all_apis()
        api_ids = None
        if filter_name != "Todas":
            api_ids = [a["id"] for a in apis if a["name"] == filter_name]

        if api_ids is not None and not api_ids:
            return

        if filter_status == "Todos":
            trades = []
            for api in apis:
                if api_ids is None or api["id"] in api_ids:
                    trades.extend(get_trades(api_id=api["id"]))
            trades.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        else:
            trades = []
            for api in apis:
                if api_ids is None or api["id"] in api_ids:
                    trades.extend(get_trades(api_id=api["id"], status=filter_status))
            trades.sort(key=lambda t: t.get("created_at", ""), reverse=True)

        total_pnl = 0
        total_comm = 0
        for t in trades:
            total_pnl += t.get("pnl") or 0
            total_comm += t.get("commission_charged") or 0
            pnl = t.get("pnl")
            pnl_pct = t.get("pnl_percent")
            pnl_str = f"${pnl:+,.2f}" if pnl is not None else "-"
            pct_str = f"{pnl_pct:+.2f}%" if pnl_pct is not None else "-"
            comm_str = f"${t.get('commission_charged', 0):,.2f}"

            self.table.add_row((
                str(t["id"]), t["api_name"], t["inst_id"],
                t["pos_side"].upper(),
                f"{t['size']:.6f}",
                f"${t['entry_price']:.2f}" if t["entry_price"] else "-",
                f"${t['exit_price']:.2f}" if t["exit_price"] else "-",
                pnl_str, pct_str, comm_str,
                t["status"].upper(),
                (t.get("created_at") or "")[:19],
            ))

        pnl_color = GREEN if total_pnl >= 0 else RED
        self.total_pnl_lbl.configure(text=f"PnL Total: ${total_pnl:+,.2f}", text_color=pnl_color)
        self.total_comm_lbl.configure(text=f"Comissões: ${total_comm:+,.2f}")


# ═══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════
def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = OKXPortfolioApp()
    try:
        app.mainloop()
    finally:
        try:
            app.destroy()
        except Exception:
            pass
    gc.collect()


if __name__ == "__main__":
    main()
