# MyDb

A small desktop database application for tracking **products** and their
**components** (a simple bill-of-materials).

Each product has:

- **code** — a unique identifier
- **name** — a human-readable name
- **quantity** — how much you have
- **unit** — either `gab.` (*gabali* / pieces) or `kg`

Each product can also have **nested codes**: other positions referenced by their
code, each with its own quantity or weight. A nested code shows the name of the
position it points to automatically. For example, to make one unit of `A-100`
you might need `B-200` (Bolt) × 5 `gab.` and `C-300` (Resin) × 2.3 `kg`.

## How it works

The main window is a **list of positions**. Use **New position** or **Open** to
bring up that position's own **card** — a separate window holding all its details
and its nested codes. **Delete position** removes a position (and its nested
codes).

To nest a code, open a position's card and click **Add nested code**: a picker
window lists every other position, you click one and give it a quantity and
unit. A position can't be nested inside itself, so it never appears in its own
picker. (Save a new position first — nesting needs the position to exist.)

## Tech

- **Python 3** — application language
- **Tkinter** — simple desktop GUI (ships with Python)
- **SQLite** — the database, stored in a single `mydb.sqlite3` file

## Running

```bash
python app.py
```

The first run creates `mydb.sqlite3` automatically.

## Building a standalone `.exe`

To get a single program file that runs **without** Python installed (so you can
double-click it, or point a desktop shortcut at it), build it with
[PyInstaller](https://pyinstaller.org/):

```powershell
.\build_exe.ps1
```

This produces `dist\MyDb.exe`. Copy that file to any Windows PC and run it — no
Python needed. The app keeps its database (`mydb.sqlite3`) in the same folder as
the `.exe`.

## Project layout

| File        | Purpose                                          |
| ----------- | ------------------------------------------------ |
| `app.py`    | Tkinter GUI                                      |
| `db.py`     | SQLite data layer (tables + add/list helpers)    |
| `README.md` | This file                                        |

## Roadmap

- [x] Positions: create, list, open in a card, edit, delete
- [x] Nested codes that reference another position (name resolved automatically)
- [ ] Search / filter positions
- [x] Package as a standalone `.exe` (PyInstaller)
