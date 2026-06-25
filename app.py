"""MyDb — a small Tkinter desktop UI over the SQLite data layer in :mod:`db`.

Top half lists products. Selecting a product shows its nested components in the
bottom half. Each half has a little form to add new rows.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import db


class MyDbApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MyDb — products & components")
        self.geometry("720x560")

        self.conn = db.get_connection()
        db.init_db(self.conn)

        self._build_products_section()
        self._build_components_section()
        self.refresh_products()

    # ----- products -----------------------------------------------------

    def _build_products_section(self) -> None:
        frame = ttk.LabelFrame(self, text="Products")
        frame.pack(fill="both", expand=True, padx=10, pady=(10, 5))

        columns = ("code", "name", "quantity", "unit")
        self.products_tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=8
        )
        for col in columns:
            self.products_tree.heading(col, text=col.capitalize())
            self.products_tree.column(col, width=120, anchor="w")
        self.products_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.products_tree.bind("<<TreeviewSelect>>", self._on_product_selected)

        form = ttk.Frame(frame)
        form.pack(fill="x", padx=5, pady=5)
        self.p_code = self._labelled_entry(form, "Code", 0)
        self.p_name = self._labelled_entry(form, "Name", 1)
        self.p_qty = self._labelled_entry(form, "Quantity", 2)
        self.p_unit = self._unit_combo(form, 3)
        ttk.Button(form, text="Add product", command=self.on_add_product).grid(
            row=0, column=8, padx=5
        )

    def on_add_product(self) -> None:
        code = self.p_code.get().strip()
        name = self.p_name.get().strip()
        if not code or not name:
            messagebox.showwarning("Missing data", "Code and name are required.")
            return
        try:
            quantity = float(self.p_qty.get() or 0)
        except ValueError:
            messagebox.showwarning("Invalid quantity", "Quantity must be a number.")
            return
        try:
            db.add_product(self.conn, code, name, quantity, self.p_unit.get())
        except Exception as exc:  # e.g. duplicate code
            messagebox.showerror("Could not add product", str(exc))
            return
        for entry in (self.p_code, self.p_name, self.p_qty):
            entry.delete(0, tk.END)
        self.refresh_products()

    def refresh_products(self) -> None:
        self.products_tree.delete(*self.products_tree.get_children())
        for row in db.list_products(self.conn):
            self.products_tree.insert(
                "", tk.END, iid=str(row["id"]),
                values=(row["code"], row["name"], row["quantity"], row["unit"]),
            )
        self.refresh_components()

    # ----- components ---------------------------------------------------

    def _build_components_section(self) -> None:
        frame = ttk.LabelFrame(self, text="Components of selected product")
        frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        columns = ("child_code", "quantity", "unit")
        self.components_tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=6
        )
        for col in columns:
            self.components_tree.heading(col, text=col.replace("_", " ").capitalize())
            self.components_tree.column(col, width=120, anchor="w")
        self.components_tree.pack(fill="both", expand=True, padx=5, pady=5)

        form = ttk.Frame(frame)
        form.pack(fill="x", padx=5, pady=5)
        self.c_code = self._labelled_entry(form, "Child code", 0)
        self.c_qty = self._labelled_entry(form, "Quantity", 1)
        self.c_unit = self._unit_combo(form, 2)
        ttk.Button(form, text="Add component", command=self.on_add_component).grid(
            row=0, column=6, padx=5
        )

    def on_add_component(self) -> None:
        product_id = self._selected_product_id()
        if product_id is None:
            messagebox.showinfo("Select a product", "Pick a product first.")
            return
        child_code = self.c_code.get().strip()
        if not child_code:
            messagebox.showwarning("Missing data", "Child code is required.")
            return
        try:
            quantity = float(self.c_qty.get() or 0)
        except ValueError:
            messagebox.showwarning("Invalid quantity", "Quantity must be a number.")
            return
        db.add_component(self.conn, product_id, child_code, quantity, self.c_unit.get())
        self.c_code.delete(0, tk.END)
        self.c_qty.delete(0, tk.END)
        self.refresh_components()

    def refresh_components(self) -> None:
        self.components_tree.delete(*self.components_tree.get_children())
        product_id = self._selected_product_id()
        if product_id is None:
            return
        for row in db.list_components(self.conn, product_id):
            self.components_tree.insert(
                "", tk.END,
                values=(row["child_code"], row["quantity"], row["unit"]),
            )

    def _on_product_selected(self, _event: object) -> None:
        self.refresh_components()

    # ----- small helpers ------------------------------------------------

    def _selected_product_id(self) -> int | None:
        selection = self.products_tree.selection()
        return int(selection[0]) if selection else None

    def _labelled_entry(self, parent: tk.Widget, label: str, col: int) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=0, column=col * 2, sticky="e", padx=(5, 2))
        entry = ttk.Entry(parent, width=12)
        entry.grid(row=0, column=col * 2 + 1, padx=(0, 5))
        return entry

    def _unit_combo(self, parent: tk.Widget, col: int) -> ttk.Combobox:
        ttk.Label(parent, text="Unit").grid(row=0, column=col * 2, sticky="e", padx=(5, 2))
        combo = ttk.Combobox(
            parent, values=list(db.VALID_UNITS), width=6, state="readonly"
        )
        combo.current(0)
        combo.grid(row=0, column=col * 2 + 1, padx=(0, 5))
        return combo


if __name__ == "__main__":
    MyDbApp().mainloop()
