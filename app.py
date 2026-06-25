"""MyDb — a Tkinter desktop UI over the SQLite data layer in :mod:`db`.

The main window lists positions. Creating a new position or opening an existing
one pops up that position's own *card* (a separate window) holding all of its
details and its nested codes.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import db


class MyDbApp(tk.Tk):
    """Main window: a list of positions plus New / Open / Delete actions."""

    def __init__(self) -> None:
        super().__init__()
        self.title("MyDb — positions")
        self.geometry("560x420")

        self.conn = db.get_connection()
        db.init_db(self.conn)

        self._build_ui()
        self.refresh_positions()

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Button(toolbar, text="New position", command=self.on_new).pack(side="left")
        ttk.Button(toolbar, text="Open", command=self.on_open).pack(side="left", padx=5)
        ttk.Button(
            toolbar, text="Delete position", command=self.on_delete
        ).pack(side="left")

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        # The main window is a catalog of products, not a stock count, so it
        # shows no quantity — that lives inside each position's card.
        columns = ("code", "name", "unit")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, width=120, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-1>", lambda _e: self.on_open())

    # ----- actions ------------------------------------------------------

    def on_new(self) -> None:
        PositionCard(self, product_id=None)

    def on_open(self) -> None:
        product_id = self._selected_id()
        if product_id is None:
            messagebox.showinfo("Select a position", "Pick a position to open.")
            return
        PositionCard(self, product_id=product_id)

    def on_delete(self) -> None:
        product_id = self._selected_id()
        if product_id is None:
            messagebox.showinfo("Select a position", "Pick a position to delete.")
            return
        row = db.get_product(self.conn, product_id)
        if row is None:
            return
        if messagebox.askyesno(
            "Delete position",
            f"Delete position {row['code']} — {row['name']}?\n"
            "Its nested codes will be removed too.",
        ):
            db.delete_product(self.conn, product_id)
            self.refresh_positions()

    # ----- helpers ------------------------------------------------------

    def refresh_positions(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for row in db.list_products(self.conn):
            self.tree.insert(
                "", tk.END, iid=str(row["id"]),
                values=(row["code"], row["name"], row["unit"]),
            )

    def _selected_id(self) -> int | None:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None


class PositionCard(tk.Toplevel):
    """A window holding one position's details and its nested codes."""

    def __init__(self, app: MyDbApp, product_id: int | None) -> None:
        super().__init__(app)
        self.app = app
        self.conn = app.conn
        self.product_id = product_id

        self.title("New position" if product_id is None else "Position")
        self.geometry("520x480")
        self.transient(app)

        self._build_details()
        self._build_components()

        if product_id is None:
            self._set_components_enabled(False)
        else:
            self._load()

    # ----- details (top) ------------------------------------------------

    def _build_details(self) -> None:
        frame = ttk.LabelFrame(self, text="Details")
        frame.pack(fill="x", padx=10, pady=(10, 5))

        self.code = self._field(frame, "Code", 0)
        self.name = self._field(frame, "Name", 1)
        self.quantity = self._field(frame, "Quantity", 2)

        ttk.Label(frame, text="Unit").grid(row=3, column=0, sticky="e", padx=5, pady=3)
        self.unit = ttk.Combobox(
            frame, values=list(db.VALID_UNITS), width=8, state="readonly"
        )
        self.unit.current(0)
        self.unit.grid(row=3, column=1, sticky="w", padx=5, pady=3)

        ttk.Button(frame, text="Save", command=self.on_save).grid(
            row=4, column=1, sticky="w", padx=5, pady=5
        )

    def on_save(self) -> None:
        code = self.code.get().strip()
        name = self.name.get().strip()
        if not code or not name:
            messagebox.showwarning("Missing data", "Code and name are required.")
            return
        try:
            quantity = float(self.quantity.get() or 0)
        except ValueError:
            messagebox.showwarning("Invalid quantity", "Quantity must be a number.")
            return
        unit = self.unit.get()
        try:
            if self.product_id is None:
                self.product_id = db.add_product(self.conn, code, name, quantity, unit)
                self._set_components_enabled(True)
                self.title("Position")
            else:
                db.update_product(self.conn, self.product_id, code, name, quantity, unit)
        except Exception as exc:  # e.g. duplicate code
            messagebox.showerror("Could not save", str(exc))
            return
        self.app.refresh_positions()
        self.refresh_components()

    def _load(self) -> None:
        row = db.get_product(self.conn, self.product_id)
        if row is None:
            return
        self._set(self.code, row["code"])
        self._set(self.name, row["name"])
        self._set(self.quantity, row["quantity"])
        self.unit.set(row["unit"])
        self.refresh_components()

    # ----- nested codes (bottom) ----------------------------------------

    def _build_components(self) -> None:
        self.comp_frame = ttk.LabelFrame(self, text="Nested codes")
        self.comp_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        columns = ("child_code", "child_name", "quantity", "unit")
        self.comp_tree = ttk.Treeview(
            self.comp_frame, columns=columns, show="headings", height=6
        )
        headings = ("Code", "Name", "Quantity", "Unit")
        for col, text in zip(columns, headings):
            self.comp_tree.heading(col, text=text)
            self.comp_tree.column(col, width=110, anchor="w")
        self.comp_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.comp_tree.bind("<Double-1>", lambda _e: self.on_edit_component())

        form = ttk.Frame(self.comp_frame)
        form.pack(fill="x", padx=5, pady=5)
        self.add_comp_btn = ttk.Button(
            form, text="Add nested code", command=self.on_add_component
        )
        self.add_comp_btn.pack(side="left", padx=5)
        self.edit_comp_btn = ttk.Button(
            form, text="Edit selected", command=self.on_edit_component
        )
        self.edit_comp_btn.pack(side="left", padx=(0, 5))
        self.del_comp_btn = ttk.Button(
            form, text="Delete selected", command=self.on_delete_component
        )
        self.del_comp_btn.pack(side="left")

        self.comp_hint = ttk.Label(
            self.comp_frame, text="Save the position first to add nested codes."
        )
        self.comp_hint.pack(padx=5, pady=(0, 5))

    def on_add_component(self) -> None:
        if self.product_id is None:
            return
        NestedCodePicker(self, self.conn, self.product_id)

    def on_edit_component(self) -> None:
        selection = self.comp_tree.selection()
        if not selection:
            messagebox.showinfo("Select a code", "Pick a nested code to edit.")
            return
        code, name, quantity, unit = self.comp_tree.item(selection[0], "values")
        NestedCodeEditor(self, self.conn, int(selection[0]), code, name, quantity, unit)

    def on_delete_component(self) -> None:
        selection = self.comp_tree.selection()
        if not selection:
            messagebox.showinfo("Select a code", "Pick a nested code to delete.")
            return
        db.delete_component(self.conn, int(selection[0]))
        self.refresh_components()

    def refresh_components(self) -> None:
        self.comp_tree.delete(*self.comp_tree.get_children())
        if self.product_id is None:
            return
        for row in db.list_components(self.conn, self.product_id):
            self.comp_tree.insert(
                "", tk.END, iid=str(row["id"]),
                values=(
                    row["child_code"],
                    row["child_name"] or "(unknown)",
                    row["quantity"],
                    row["unit"],
                ),
            )

    def _set_components_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (self.add_comp_btn, self.edit_comp_btn, self.del_comp_btn):
            widget.configure(state=state)
        if enabled:
            self.comp_hint.pack_forget()
        else:
            self.comp_hint.pack(padx=5, pady=(0, 5))

    # ----- small helpers ------------------------------------------------

    def _field(self, parent: tk.Widget, label: str, row: int) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=5, pady=3)
        entry = ttk.Entry(parent, width=30)
        entry.grid(row=row, column=1, sticky="w", padx=5, pady=3)
        return entry

    @staticmethod
    def _set(entry: ttk.Entry, value: object) -> None:
        entry.delete(0, tk.END)
        entry.insert(0, str(value))


class NestedCodePicker(tk.Toplevel):
    """Pick a position from a list to nest under the current position.

    The parent position is left out of the list, so a position can never be
    nested inside itself.
    """

    def __init__(self, card: PositionCard, conn, parent_product_id: int) -> None:
        super().__init__(card)
        self.card = card
        self.conn = conn
        self.parent_product_id = parent_product_id

        self.title("Choose a position to nest")
        self.geometry("440x420")
        self.transient(card)
        self.grab_set()  # modal: keep focus here until done

        ttk.Label(self, text="Pick the position to nest:").pack(
            anchor="w", padx=10, pady=(10, 0)
        )

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.tree = ttk.Treeview(frame, columns=("code", "name"), show="headings")
        self.tree.heading("code", text="Code")
        self.tree.heading("name", text="Name")
        self.tree.column("code", width=120, anchor="w")
        self.tree.column("name", width=220, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-1>", lambda _e: self.on_add())

        form = ttk.Frame(self)
        form.pack(fill="x", padx=10, pady=5)
        ttk.Label(form, text="Quantity").grid(row=0, column=0, padx=(0, 2))
        self.qty = ttk.Entry(form, width=10)
        self.qty.grid(row=0, column=1, padx=(0, 10))
        ttk.Label(
            form, text="Unit follows the chosen position.", foreground="gray"
        ).grid(row=0, column=2, sticky="w")

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(buttons, text="Add", command=self.on_add).pack(side="right", padx=5)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")

        self._load()

    def _load(self) -> None:
        for row in db.list_products(self.conn):
            if row["id"] == self.parent_product_id:
                continue  # a position cannot be nested inside itself
            self.tree.insert(
                "", tk.END, iid=str(row["id"]), values=(row["code"], row["name"])
            )

    def on_add(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(
                "Select a position", "Pick a position from the list.", parent=self
            )
            return
        chosen = db.get_product(self.conn, int(selection[0]))
        try:
            quantity = float(self.qty.get() or 0)
        except ValueError:
            messagebox.showwarning(
                "Invalid quantity", "Quantity must be a number.", parent=self
            )
            return
        try:
            db.add_component(
                self.conn, self.parent_product_id, chosen["code"], quantity,
            )
        except ValueError as exc:
            messagebox.showerror("Could not add nested code", str(exc), parent=self)
            return
        self.card.refresh_components()
        self.destroy()


class NestedCodeEditor(tk.Toplevel):
    """Edit the quantity and unit of one nested code already on a position.

    The nested code's referenced position (``child_code``) is fixed and shown
    for reference only; to point at a different position, delete and re-add.
    """

    def __init__(
        self,
        card: PositionCard,
        conn,
        component_id: int,
        child_code: str,
        child_name: str,
        quantity: object,
        unit: str,
    ) -> None:
        super().__init__(card)
        self.card = card
        self.conn = conn
        self.component_id = component_id

        self.title("Edit nested code")
        self.geometry("320x180")
        self.transient(card)
        self.grab_set()  # modal: keep focus here until done

        ttk.Label(self, text=f"{child_code} — {child_name}").pack(
            anchor="w", padx=12, pady=(12, 6)
        )

        form = ttk.Frame(self)
        form.pack(fill="x", padx=12, pady=5)
        ttk.Label(form, text="Quantity").grid(row=0, column=0, sticky="e", padx=(0, 6), pady=4)
        self.qty = ttk.Entry(form, width=14)
        self.qty.insert(0, str(quantity))
        self.qty.grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(form, text="Unit").grid(row=1, column=0, sticky="e", padx=(0, 6), pady=4)
        ttk.Label(form, text=f"{unit}  (set on the position itself)").grid(
            row=1, column=1, sticky="w", pady=4
        )

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=12, pady=(8, 12))
        ttk.Button(buttons, text="Save", command=self.on_save).pack(side="right", padx=5)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")

        self.qty.focus_set()

    def on_save(self) -> None:
        try:
            quantity = float(self.qty.get() or 0)
        except ValueError:
            messagebox.showwarning(
                "Invalid quantity", "Quantity must be a number.", parent=self
            )
            return
        db.update_component(self.conn, self.component_id, quantity)
        self.card.refresh_components()
        self.destroy()


if __name__ == "__main__":
    MyDbApp().mainloop()
