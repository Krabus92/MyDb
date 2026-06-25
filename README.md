# MyDb

A small desktop database application for tracking **products** and their
**components** (a simple bill-of-materials).

Each product has:

- **code** — a unique identifier
- **name** — a human-readable name
- **quantity** — how much you have
- **unit** — either `gab.` (*gabali* / pieces) or `kg`

Each product can also have **components**: other codes nested under it, each
with its own quantity or weight. For example, to make one unit of product
`A-100` you might need `B-200` × 5 `gab.` and `C-300` × 2.3 `kg`.

## Tech

- **Python 3** — application language
- **Tkinter** — simple desktop GUI (ships with Python)
- **SQLite** — the database, stored in a single `mydb.sqlite3` file

## Running

```bash
python app.py
```

The first run creates `mydb.sqlite3` automatically.

## Project layout

| File        | Purpose                                          |
| ----------- | ------------------------------------------------ |
| `app.py`    | Tkinter GUI                                      |
| `db.py`     | SQLite data layer (tables + add/list helpers)    |
| `README.md` | This file                                        |

## Roadmap

- [x] Products: add and list
- [x] Components nested under a product
- [ ] Edit and delete entries
- [ ] Search / filter products
- [ ] Package as a standalone `.exe` (PyInstaller)
