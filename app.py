"""MyDb — a Tkinter desktop UI over the SQLite data layer in :mod:`db`.

The main window lists positions. Creating a new position or opening an existing
one pops up that position's own *card* (a separate window) holding all of its
details and its nested codes.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import db


def fix_baltic_char(char: str) -> str | None:
    """Recover a Latvian letter that Tk on Windows mis-decoded as Latin-1.

    With a Latvian (AltGr) keyboard, Tk 8.6 on Windows delivers a keystroke
    decoded through Latin-1 (cp1252) instead of Baltic (cp1257): the byte 0xEF
    meant for ``ļ`` arrives as ``ï``, and so on. Re-encoding the character to its
    byte via cp1252 and decoding it as cp1257 restores the intended letter.

    Returns the corrected letter, or ``None`` if ``char`` is plain ASCII or is
    not a Latin-1 character that needs fixing (so it should be left alone).
    """
    if not char or ord(char[0]) < 0x80:
        return None
    try:
        corrected = char.encode("cp1252").decode("cp1257")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None  # already a correct character outside Latin-1
    return corrected if corrected != char else None


def enable_latvian_input(widget: tk.Widget) -> None:
    """Bind ``widget`` so mis-decoded Latvian letters are corrected as you type."""

    def on_key(event: tk.Event) -> str | None:
        corrected = fix_baltic_char(event.char)
        if corrected is None:
            return None  # let Tk insert ASCII / handle special keys normally
        try:  # drop any active selection first (Text widget)
            if widget.tag_ranges("sel"):
                widget.delete("sel.first", "sel.last")
        except (AttributeError, tk.TclError):
            try:  # Entry widget
                if widget.selection_present():
                    widget.delete("sel.first", "sel.last")
            except (AttributeError, tk.TclError):
                pass
        widget.insert("insert", corrected)
        return "break"  # stop Tk from also inserting the wrong character

    widget.bind("<KeyPress>", on_key)


def ask_latvian_text(
    parent: tk.Widget, title: str, prompt: str, initial: str = ""
) -> str | None:
    """Modal one-line text prompt whose entry supports Latvian input.

    Returns the trimmed text, or ``None`` if cancelled or left blank.
    """
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.resizable(False, False)
    dialog.grab_set()

    ttk.Label(dialog, text=prompt).pack(anchor="w", padx=12, pady=(12, 4))
    entry = ttk.Entry(dialog, width=34)
    entry.insert(0, initial)
    entry.pack(fill="x", padx=12)
    enable_latvian_input(entry)

    result: dict[str, str | None] = {"value": None}

    def ok() -> None:
        result["value"] = entry.get().strip()
        dialog.destroy()

    buttons = ttk.Frame(dialog)
    buttons.pack(fill="x", padx=12, pady=12)
    ttk.Button(buttons, text="Ok", command=ok).pack(side="right", padx=5)
    ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")
    entry.bind("<Return>", lambda _e: ok())
    entry.focus_set()

    parent.wait_window(dialog)
    return result["value"] or None


class MyDbApp(tk.Tk):
    """Main window: a list of positions plus New / Open / Delete actions."""

    def __init__(self) -> None:
        super().__init__()
        self.title("MyDb — positions")
        self.geometry("780x440")

        self.conn = db.get_connection()
        db.init_db(self.conn)

        self.current_group_id: int | None = None  # None = "All products"

        self._build_ui()
        self.refresh_groups()
        self.refresh_positions()

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Button(toolbar, text="New position", command=self.on_new).pack(side="left")
        ttk.Button(toolbar, text="Open", command=self.on_open).pack(side="left", padx=5)
        ttk.Button(
            toolbar, text="Delete position", command=self.on_delete
        ).pack(side="left")
        ttk.Button(
            toolbar, text="New group", command=self.on_new_group
        ).pack(side="left", padx=5)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Left: group filter, with "All products" pinned at the top.
        groups_frame = ttk.LabelFrame(body, text="Groups")
        groups_frame.pack(side="left", fill="y", padx=(0, 8))
        self.groups_tree = ttk.Treeview(
            groups_frame, columns=("name",), show="headings",
            height=12, selectmode="browse",
        )
        self.groups_tree.heading("name", text="Group")
        self.groups_tree.column("name", width=150, anchor="w")
        self.groups_tree.pack(fill="y", expand=True, padx=5, pady=5)
        self.groups_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_group_select())
        self.groups_tree.bind("<Button-3>", self._on_group_right_click)

        # Right: a search box over the products in the selected group.
        frame = ttk.Frame(body)
        frame.pack(side="left", fill="both", expand=True)

        search_bar = ttk.Frame(frame)
        search_bar.pack(fill="x", pady=(0, 5))
        ttk.Label(search_bar, text="Search").pack(side="left")
        self.search = ttk.Entry(search_bar)
        self.search.pack(side="left", fill="x", expand=True, padx=5)
        enable_latvian_input(self.search)
        self.search.bind("<KeyRelease>", lambda _e: self.refresh_positions())
        ttk.Button(
            search_bar, text="Clear", command=self._clear_search
        ).pack(side="left")

        tree_area = ttk.Frame(frame)
        tree_area.pack(fill="both", expand=True)
        # The main window is a catalog of products, not a stock count, so it
        # shows no quantity — that lives inside each position's card.
        columns = ("code", "name", "unit")
        self.tree = ttk.Treeview(tree_area, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, width=120, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(tree_area, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-1>", lambda _e: self.on_open())
        self.tree.bind("<Button-3>", self._on_tree_right_click)

    def _clear_search(self) -> None:
        self.search.delete(0, tk.END)
        self.refresh_positions()

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

    def on_new_group(self) -> None:
        name = ask_latvian_text(self, "New group", "Group name:")
        if not name:
            return
        try:
            db.add_group(self.conn, name)
        except Exception as exc:  # e.g. duplicate name
            messagebox.showerror("Could not create group", str(exc), parent=self)
            return
        self.refresh_groups()

    def on_delete_group(self) -> None:
        group_id = self._selected_group_id()
        if group_id is None:
            return
        selection = self.groups_tree.selection()
        name = self.groups_tree.item(selection[0], "values")[0] if selection else ""
        if messagebox.askyesno(
            "Delete group",
            f"Delete group {name!r}? Its positions stay but become ungrouped.",
            parent=self,
        ):
            db.delete_group(self.conn, group_id)
            if self.current_group_id == group_id:
                self.current_group_id = None
            self.refresh_groups()
            self.refresh_positions()

    # ----- right-click menus --------------------------------------------

    def _on_tree_right_click(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
        has_sel = bool(self.tree.selection())
        state = "normal" if has_sel else "disabled"
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Open", command=self.on_open, state=state)
        menu.add_command(label="Delete position", command=self.on_delete, state=state)
        menu.add_separator()
        menu.add_command(label="New position", command=self.on_new)
        if has_sel:
            group_menu = tk.Menu(menu, tearoff=0)
            group_menu.add_command(
                label="(no group)", command=lambda: self._assign_group(None)
            )
            for g in db.list_groups(self.conn):
                group_menu.add_command(
                    label=g["name"], command=lambda gid=g["id"]: self._assign_group(gid)
                )
            menu.add_cascade(label="Move to group", menu=group_menu)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_group_right_click(self, event: tk.Event) -> None:
        row = self.groups_tree.identify_row(event.y)
        if row:
            self.groups_tree.selection_set(row)
        can_delete = bool(row) and row != "all"
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="New group", command=self.on_new_group)
        menu.add_command(
            label="Delete group", command=self.on_delete_group,
            state="normal" if can_delete else "disabled",
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _assign_group(self, group_id: int | None) -> None:
        product_id = self._selected_id()
        if product_id is None:
            return
        db.set_product_group(self.conn, product_id, group_id)
        self.refresh_positions()

    # ----- helpers ------------------------------------------------------

    def refresh_groups(self) -> None:
        self.groups_tree.delete(*self.groups_tree.get_children())
        self.groups_tree.insert("", tk.END, iid="all", values=("All products",))
        for g in db.list_groups(self.conn):
            self.groups_tree.insert("", tk.END, iid=str(g["id"]), values=(g["name"],))
        iid = "all" if self.current_group_id is None else str(self.current_group_id)
        if not self.groups_tree.exists(iid):
            iid, self.current_group_id = "all", None
        self.groups_tree.selection_set(iid)

    def refresh_positions(self) -> None:
        self.tree.delete(*self.tree.get_children())
        term = self.search.get().strip().lower()
        for row in db.list_products(self.conn, self.current_group_id):
            if term and term not in row["code"].lower() and term not in row["name"].lower():
                continue
            self.tree.insert(
                "", tk.END, iid=str(row["id"]),
                values=(row["code"], row["name"], row["unit"]),
            )

    def _on_group_select(self) -> None:
        self.current_group_id = self._selected_group_id()
        self.refresh_positions()

    def _selected_group_id(self) -> int | None:
        selection = self.groups_tree.selection()
        if not selection or selection[0] == "all":
            return None
        return int(selection[0])

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
        self.geometry("520x620")
        self.minsize(520, 620)  # auto-sizing (geometry("")) never shrinks below this
        self.transient(app)

        # Everything lives in a left "content" column; a computed-nutrition
        # panel is shown to its right when the checkbox is ticked.
        self.content = ttk.Frame(self)
        self.content.pack(side="left", fill="both", expand=True)
        self.show_nutrition_var = tk.BooleanVar(value=False)
        self.nutrition_panel = ttk.LabelFrame(
            self, text="Uzturvielas / 100 g (no sastāva)"
        )
        self._build_nutrition_panel()

        self._build_details()
        self._build_description()
        self._build_actions()
        self._build_components()

        if product_id is None:
            self._set_components_enabled(False)
        else:
            self._load()

    # ----- details (top) ------------------------------------------------

    def _build_details(self) -> None:
        frame = ttk.LabelFrame(self.content, text="Details")
        frame.pack(fill="x", padx=10, pady=(10, 5))

        self.code = self._field(frame, "Code", 0)
        self.name = self._field(frame, "Name", 1)
        self.quantity = self._field(frame, "Quantity", 2)
        enable_latvian_input(self.code)
        enable_latvian_input(self.name)
        # Quantity and weight feed the per-100 g basis, so update the computed
        # panel live as they are typed (when it is shown).
        self.quantity.bind("<KeyRelease>", lambda _e: self._on_basis_changed())

        ttk.Label(frame, text="Unit").grid(row=3, column=0, sticky="e", padx=5, pady=3)
        self.unit = ttk.Combobox(
            frame, values=list(db.VALID_UNITS), width=8, state="readonly"
        )
        self.unit.current(0)
        self.unit.grid(row=3, column=1, sticky="w", padx=5, pady=3)
        self.unit.bind(
            "<<ComboboxSelected>>",
            lambda _e: (self._sync_weight_row(), self._on_basis_changed()),
        )

        # Weight (kg) only applies to piece-counted ('gab.') positions; a 'kg'
        # position is 1 kg per unit. The row is shown only when unit == 'gab.'.
        self.weight_label = ttk.Label(frame, text="Weight (kg)")
        self.weight = ttk.Entry(frame, width=30)
        self.weight_label.grid(row=4, column=0, sticky="e", padx=5, pady=3)
        self.weight.grid(row=4, column=1, sticky="w", padx=5, pady=3)
        self.weight.bind("<KeyRelease>", lambda _e: self._on_basis_changed())

        ttk.Label(frame, text="Group").grid(row=5, column=0, sticky="e", padx=5, pady=3)
        self.group = ttk.Combobox(frame, width=27, state="readonly")
        self.group.grid(row=5, column=1, sticky="w", padx=5, pady=3)
        self._reload_groups()

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=1, sticky="w", padx=5, pady=5)
        ttk.Button(buttons, text="Save", command=self.on_save).pack(side="left")
        self.nutrition_btn = ttk.Button(
            buttons, text="uzturvielas", command=self.on_nutrition
        )
        self.nutrition_btn.pack(side="left", padx=5)
        ttk.Checkbutton(
            buttons, text="rādīt aprēķināto", variable=self.show_nutrition_var,
            command=self._toggle_nutrition_panel,
        ).pack(side="left")

    def _on_basis_changed(self) -> None:
        """A weight/quantity/unit edit changes the per-100 g basis; refresh the
        computed panel live if it is currently shown."""
        if self.show_nutrition_var.get():
            self._refresh_nutrition_panel()

    # ----- computed nutrition panel (right) -----------------------------

    def _build_nutrition_panel(self) -> None:
        self.nutrition_vars: dict[str, tk.StringVar] = {}
        rows = [
            ("fat", "Tauki"),
            ("saturated_fat", "Piesātinātās taukskābes"),
            ("carbs", "Ogļhidrāti"),
            ("sugar", "Cukurs"),
            ("protein", "Olbaltumvielas"),
            ("salt", "Sāls"),
            ("kcal", "kcal"),
            ("kj", "KJ"),
        ]
        for i, (key, label) in enumerate(rows):
            ttk.Label(self.nutrition_panel, text=label).grid(
                row=i, column=0, sticky="w", padx=8, pady=2
            )
            var = tk.StringVar(value="—")
            ttk.Label(
                self.nutrition_panel, textvariable=var, width=10, anchor="e"
            ).grid(row=i, column=1, sticky="e", padx=8, pady=2)
            self.nutrition_vars[key] = var

    def _toggle_nutrition_panel(self) -> None:
        if self.show_nutrition_var.get():
            self._refresh_nutrition_panel()
            self.nutrition_panel.pack(side="right", fill="y", padx=(0, 10), pady=10)
            # The computed roll-up replaces manual values, so editing them while
            # it is shown would conflict with the logic; block it.
            self.nutrition_btn.configure(state="disabled")
        else:
            self.nutrition_panel.pack_forget()
            self.nutrition_btn.configure(state="normal")
        # Let Tk size the window to exactly fit the current layout, so the panel
        # (long labels + numbers) is never clipped and we shrink back when hidden.
        self.update_idletasks()
        self.geometry("")

    def _refresh_nutrition_panel(self) -> None:
        """Show the per-100 g roll-up. For a recipe, divide the nested-code
        totals by the position's *live* declared mass (the weight/quantity as
        currently typed), so the panel reacts before you even save."""
        if self.product_id is None:
            for var in self.nutrition_vars.values():
                var.set("—")
            return
        totals = db.recipe_nutrient_grams(self.conn, self.product_id)
        if totals is None:
            # Raw position: just its stored per-100 g values.
            n = db.effective_nutrition(self.conn, self.product_id)
        else:
            basis = db.position_mass_grams(self._live_weight(), self._live_quantity())
            n = {k: (totals[k] / basis * 100.0 if basis > 0 else 0.0)
                 for k in db.NUTRIENTS}
        for key in db.NUTRIENTS:
            self.nutrition_vars[key].set(db.format_quantity(n[key]))
        self.nutrition_vars["kcal"].set(
            db.format_quantity(db.energy_kcal(n["fat"], n["carbs"], n["protein"]))
        )
        self.nutrition_vars["kj"].set(
            db.format_quantity(db.energy_kj(n["fat"], n["carbs"], n["protein"]))
        )

    def _live_weight(self) -> float:
        """Weight per unit from the form: the weight field for 'gab.', else 1."""
        if self.unit.get() != "gab.":
            return 1.0
        try:
            return float(self.weight.get() or 1)
        except ValueError:
            return 1.0

    def _live_quantity(self) -> float:
        try:
            return float(self.quantity.get() or 0)
        except ValueError:
            return 0.0

    def _reload_groups(self) -> None:
        """Fill the group dropdown with '(no group)' plus every existing group."""
        self._group_ids: dict[str, int | None] = {"(no group)": None}
        names = ["(no group)"]
        for g in db.list_groups(self.conn):
            self._group_ids[g["name"]] = g["id"]
            names.append(g["name"])
        self.group["values"] = names
        self.group.set("(no group)")

        self._sync_weight_row()

    def _sync_weight_row(self) -> None:
        """Show the weight field only for piece-counted ('gab.') positions."""
        if self.unit.get() == "gab.":
            self.weight_label.grid()
            self.weight.grid()
        else:
            self.weight_label.grid_remove()
            self.weight.grid_remove()

    def on_nutrition(self) -> None:
        if self.product_id is None:
            messagebox.showinfo(
                "Save first", "Save the position before adding nutrition.", parent=self
            )
            return
        if self.show_nutrition_var.get():
            messagebox.showinfo(
                "Computed nutrition shown",
                "Uncheck 'rādīt aprēķināto' to edit values manually. While the "
                "computed roll-up is shown, manual values would conflict with it.",
                parent=self,
            )
            return
        NutritionWindow(self, self.conn, self.product_id)

    # ----- description (middle) -----------------------------------------

    def _build_description(self) -> None:
        frame = ttk.LabelFrame(self.content, text="Description")
        frame.pack(fill="both", expand=False, padx=10, pady=5)
        self.description = tk.Text(frame, height=5, wrap="word")
        self.description.pack(fill="both", expand=True, padx=5, pady=5)
        enable_latvian_input(self.description)

    # ----- actions (bottom-right) ---------------------------------------

    def _build_actions(self) -> None:
        bar = ttk.Frame(self.content)
        bar.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        # Packed right-to-left: Cancel sits on the far right, Ok just left of it.
        ttk.Button(bar, text="Cancel", command=self.on_cancel).pack(side="right")
        ttk.Button(bar, text="Ok", command=self.on_ok).pack(side="right", padx=(0, 5))

    def on_ok(self) -> None:
        if not messagebox.askyesno(
            "Save and exit", "Save changes and close this position?", parent=self
        ):
            return
        if self.on_save():  # only close if the save actually succeeded
            self.destroy()

    def on_cancel(self) -> None:
        if messagebox.askyesno(
            "Exit without saving",
            "Close this position without saving your changes?",
            parent=self,
        ):
            self.destroy()

    def on_save(self) -> bool:
        """Save the position. Return True on success, False if it could not save."""
        code = self.code.get().strip()
        name = self.name.get().strip()
        if not code or not name:
            messagebox.showwarning(
                "Missing data", "Code and name are required.", parent=self
            )
            return False
        try:
            quantity = float(self.quantity.get() or 0)
        except ValueError:
            messagebox.showwarning(
                "Invalid quantity", "Quantity must be a number.", parent=self
            )
            return False
        unit = self.unit.get()
        if unit == "gab.":
            try:
                weight_kg = float(self.weight.get() or 0)
            except ValueError:
                messagebox.showwarning(
                    "Invalid weight", "Weight must be a number.", parent=self
                )
                return False
        else:
            weight_kg = 1.0  # a 'kg' position weighs 1 kg per unit
        description = self.description.get("1.0", "end-1c")
        group_id = self._group_ids.get(self.group.get())
        try:
            if self.product_id is None:
                self.product_id = db.add_product(
                    self.conn, code, name, quantity, unit, description,
                    weight_kg, group_id,
                )
                self._set_components_enabled(True)
                self.title("Position")
            else:
                db.update_product(
                    self.conn, self.product_id, code, name, quantity, unit,
                    description, weight_kg, group_id,
                )
        except Exception as exc:  # e.g. duplicate code
            messagebox.showerror("Could not save", str(exc), parent=self)
            return False
        # Remember whether this position's card opens with the computed panel.
        db.set_show_computed(self.conn, self.product_id, self.show_nutrition_var.get())
        self.app.refresh_positions()
        self.refresh_components()
        return True

    def _load(self) -> None:
        row = db.get_product(self.conn, self.product_id)
        if row is None:
            return
        self._set(self.code, row["code"])
        self._set(self.name, row["name"])
        self._set(self.quantity, db.format_quantity(row["quantity"]))
        self.unit.set(row["unit"])
        self._set(self.weight, db.format_quantity(row["weight_kg"]))
        self._sync_weight_row()
        self.description.delete("1.0", tk.END)
        self.description.insert("1.0", row["description"])
        group_name = next(
            (n for n, gid in self._group_ids.items() if gid == row["group_id"]),
            "(no group)",
        )
        self.group.set(group_name)
        self.refresh_components()
        # Reopen with the computed panel shown if it was when last saved.
        self.show_nutrition_var.set(bool(row["show_computed"]))
        self._toggle_nutrition_panel()

    # ----- nested codes (bottom) ----------------------------------------

    def _build_components(self) -> None:
        self.comp_frame = ttk.LabelFrame(self.content, text="Nested codes")
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
        self.comp_tree.bind("<Button-3>", self._on_comp_right_click)

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

    def _on_comp_right_click(self, event: tk.Event) -> None:
        row = self.comp_tree.identify_row(event.y)
        if row:
            self.comp_tree.selection_set(row)
        state = "normal" if self.comp_tree.selection() else "disabled"
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Edit selected", command=self.on_edit_component, state=state)
        menu.add_command(
            label="Delete selected", command=self.on_delete_component, state=state
        )
        menu.add_separator()
        menu.add_command(label="Add nested code", command=self.on_add_component)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

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
        if self.product_id is not None:
            for row in db.list_components(self.conn, self.product_id):
                self.comp_tree.insert(
                    "", tk.END, iid=str(row["id"]),
                    values=(
                        row["child_code"],
                        row["child_name"] or "(unknown)",
                        db.format_quantity(row["quantity"]),
                        row["unit"],
                    ),
                )
        # The roll-up depends on the nested codes, so keep the panel in sync.
        if self.show_nutrition_var.get():
            self._refresh_nutrition_panel()

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
        child_product_id = int(selection[0])
        try:
            quantity = float(self.qty.get() or 0)
        except ValueError:
            messagebox.showwarning(
                "Invalid quantity", "Quantity must be a number.", parent=self
            )
            return
        try:
            db.add_component(
                self.conn, self.parent_product_id, child_product_id, quantity,
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


class NutritionWindow(tk.Toplevel):
    """Edit a position's nutrition values per 100 g; kcal and kJ update live."""

    #: (column, Latvian label) for the six user-entered values.
    FIELDS = [
        ("fat", "Tauki"),
        ("saturated_fat", "Piesātinātās taukskābes"),
        ("carbs", "Ogļhidrāti"),
        ("sugar", "Cukurs"),
        ("protein", "Olbaltumvielas"),
        ("salt", "Sāls"),
    ]

    def __init__(self, card: PositionCard, conn, product_id: int) -> None:
        super().__init__(card)
        self.card = card
        self.conn = conn
        self.product_id = product_id

        self.title("Uzturvielas (uz 100 g)")
        self.geometry("360x360")
        self.transient(card)
        self.grab_set()

        row = db.get_product(conn, product_id)

        form = ttk.Frame(self)
        form.pack(fill="both", expand=True, padx=12, pady=12)
        form.columnconfigure(1, weight=1)

        self.entries: dict[str, ttk.Entry] = {}
        for i, (field, label) in enumerate(self.FIELDS):
            ttk.Label(form, text=label).grid(
                row=i, column=0, sticky="e", padx=(0, 8), pady=3
            )
            entry = ttk.Entry(form, width=14)
            entry.insert(0, db.format_quantity(row[field]))
            entry.grid(row=i, column=1, sticky="w", pady=3)
            entry.bind("<KeyRelease>", lambda _e: self._recompute())
            self.entries[field] = entry

        ttk.Separator(form, orient="horizontal").grid(
            row=len(self.FIELDS), column=0, columnspan=2, sticky="ew", pady=6
        )
        self.kcal_var = tk.StringVar()
        self.kj_var = tk.StringVar()
        ttk.Label(form, text="kcal").grid(
            row=len(self.FIELDS) + 1, column=0, sticky="e", padx=(0, 8), pady=3
        )
        ttk.Label(form, textvariable=self.kcal_var).grid(
            row=len(self.FIELDS) + 1, column=1, sticky="w", pady=3
        )
        ttk.Label(form, text="KJ").grid(
            row=len(self.FIELDS) + 2, column=0, sticky="e", padx=(0, 8), pady=3
        )
        ttk.Label(form, textvariable=self.kj_var).grid(
            row=len(self.FIELDS) + 2, column=1, sticky="w", pady=3
        )

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(buttons, text="Save", command=self.on_save).pack(side="right", padx=5)
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")

        self._recompute()

    def _values(self) -> dict[str, float]:
        """Read the six macro entries as floats (blank or invalid count as 0)."""
        values = {}
        for field, _ in self.FIELDS:
            try:
                values[field] = float(self.entries[field].get() or 0)
            except ValueError:
                values[field] = 0.0
        return values

    def _recompute(self) -> None:
        v = self._values()
        self.kcal_var.set(db.format_quantity(db.energy_kcal(v["fat"], v["carbs"], v["protein"])))
        self.kj_var.set(db.format_quantity(db.energy_kj(v["fat"], v["carbs"], v["protein"])))

    def on_save(self) -> None:
        v = self._values()
        db.update_nutrition(
            self.conn, self.product_id,
            v["fat"], v["saturated_fat"], v["carbs"], v["sugar"], v["protein"], v["salt"],
        )
        self.destroy()


if __name__ == "__main__":
    MyDbApp().mainloop()
