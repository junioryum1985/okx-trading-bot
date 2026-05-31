#!/usr/bin/env python3
"""Diagnóstico de Falha de Segmentação"""
import faulthandler
import sys
import os

faulthandler.enable()  # mostra o stack C no crash
sys.stderr = open("/tmp/faulthandler.log", "w", buffering=1)

print("=== Teste 1: tkinter mínimo ===", flush=True)
import tkinter as tk
root = tk.Tk()
root.geometry("300x200")
root.title("test 1")
root.destroy()
print("OK", flush=True)

print("=== Teste 2: customtkinter básico ===", flush=True)
import customtkinter as ctk
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
app = ctk.CTk()
app.geometry("300x200")
app.title("test 2")
print("CTk criado", flush=True)
app.update()
print("update OK", flush=True)
app.destroy()
print("destroy OK", flush=True)
print("OK", flush=True)

print("=== Teste 3: ttk.Treeview dentro de CTkFrame ===", flush=True)
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
app = ctk.CTk()
app.geometry("400x300")
frame = ctk.CTkFrame(app, fg_color="#14142e")
frame.pack(fill="both", expand=True)
tree = ttk.Treeview(frame, columns=("A", "B"), show="headings", height=5)
tree.heading("A", text="Col A")
tree.heading("B", text="Col B")
tree.pack(fill="both", expand=True)
tree.insert("", "end", values=("1", "2"))
scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
tree.configure(yscrollcommand=scroll.set)
scroll.pack(side="right", fill="y")
app.update()
print("Treeview criado e populado", flush=True)
app.destroy()
print("destroy OK", flush=True)
print("OK", flush=True)

print("=== Teste 4: right-click menu tk.Menu em CTk ===", flush=True)
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
app = ctk.CTk()
app.geometry("400x300")
frame = ctk.CTkFrame(app)
frame.pack(fill="both", expand=True)
def on_right_click(event):
    menu = tk.Menu(frame, tearoff=0)
    menu.add_command(label="Test", command=lambda: None)
    menu.post(event.x_root, event.y_root)
app.bind("<Button-3>", on_right_click)
app.update()
print("Menu tk criado e postado", flush=True)
app.destroy()
print("destroy OK", flush=True)
print("OK", flush=True)

print("=== Teste 5: carregamento do módulo portfolio_tracker ===", flush=True)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "."))
from portfolio_tracker.database import init_db, get_all_apis, get_dashboard_summary
init_db()
print("DB init OK", flush=True)
apis = get_all_apis()
print(f"APIs: {len(apis)}", flush=True)
summary = get_dashboard_summary()
print(f"Summary: {summary}", flush=True)
print("OK", flush=True)

print("\n✅ Todos os testes passaram sem falha de segmentação!", flush=True)
