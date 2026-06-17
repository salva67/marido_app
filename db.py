"""Capa de datos del Tablero del hogar (multi-hogar).

Cada dato pertenece a un "hogar" identificado por un código corto. No hay
login: quien tenga el código entra a ese hogar (como un enlace compartido).
Toda la persistencia pasa por aquí, así que migrar a Postgres/Supabase sólo
requiere reescribir este módulo.
"""

import os
import random
import sqlite3
import threading
import uuid

DB_PATH = os.environ.get("HOGAR_DB", "hogar.db")

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DAY_SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MEAL_SLOTS = [("breakfast", "Desayuno"), ("lunch", "Almuerzo"), ("dinner", "Cena")]
CATEGORIES = ["Alimentos", "Limpieza", "Otros"]
LEVELS = {"ok": "Bien", "low": "Poco", "out": "Agotado"}

# Alfabeto sin caracteres ambiguos (O/0, I/1) para códigos fáciles de dictar.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# DDL de cada tabla, con la columna `home` para aislar por hogar.
_DDL = {
    "homes": """
        CREATE TABLE homes (
            code    TEXT PRIMARY KEY,
            name    TEXT NOT NULL DEFAULT 'Mi hogar',
            created TEXT NOT NULL
        );""",
    "config": """
        CREATE TABLE config (
            home  TEXT NOT NULL,
            key   TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (home, key)
        );""",
    "meals": """
        CREATE TABLE meals (
            home    TEXT    NOT NULL,
            day     INTEGER NOT NULL,
            slot    TEXT    NOT NULL,
            content TEXT    NOT NULL DEFAULT '',
            PRIMARY KEY (home, day, slot)
        );""",
    "tasks": """
        CREATE TABLE tasks (
            id        TEXT PRIMARY KEY,
            home      TEXT    NOT NULL,
            name      TEXT    NOT NULL,
            assignee  INTEGER NOT NULL,
            days      TEXT    NOT NULL DEFAULT '',
            done_days TEXT    NOT NULL DEFAULT '',
            created   TEXT    NOT NULL
        );""",
    "shopping": """
        CREATE TABLE shopping (
            id      TEXT PRIMARY KEY,
            home    TEXT    NOT NULL,
            name    TEXT    NOT NULL,
            cat     TEXT    NOT NULL,
            done    INTEGER NOT NULL DEFAULT 0,
            created TEXT    NOT NULL
        );""",
    "supplies": """
        CREATE TABLE supplies (
            id    TEXT PRIMARY KEY,
            home  TEXT NOT NULL,
            name  TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'ok'
        );""",
}

_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL;")
    return _local.conn


def init_db() -> None:
    c = _conn()
    for name, ddl in _DDL.items():
        c.execute(ddl.replace(f"CREATE TABLE {name}", f"CREATE TABLE IF NOT EXISTS {name}"))
    c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_home ON tasks(home);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shop_home ON shopping(home);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_supp_home ON supplies(home);")
    _migrate()
    c.commit()


def _migrate() -> None:
    """Si una tabla quedó del esquema viejo (sin columna `home`), la recrea.
    Evita choques de esquema; sin datos previos, no hace nada."""
    c = _conn()
    for name, ddl in _DDL.items():
        if name == "homes":
            continue
        cols = [r["name"] for r in c.execute(f"PRAGMA table_info({name})").fetchall()]
        if cols and "home" not in cols:
            c.execute(f"DROP TABLE {name}")
            c.execute(ddl)
    c.commit()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _csv_to_ints(s: str) -> list[int]:
    return [int(x) for x in s.split(",") if x.strip() != ""] if s else []


def _ints_to_csv(values) -> str:
    return ",".join(str(x) for x in sorted(set(values)))


# ---------- hogares ----------
def _gen_code(n: int = 6) -> str:
    return "".join(random.choice(_ALPHABET) for _ in range(n))


def home_exists(code: str) -> bool:
    if not code:
        return False
    row = _conn().execute("SELECT 1 FROM homes WHERE code = ?", (code,)).fetchone()
    return row is not None


def create_home(name: str = "") -> str:
    """Crea un hogar nuevo con código único y devuelve el código."""
    c = _conn()
    code = _gen_code()
    while home_exists(code):
        code = _gen_code()
    c.execute(
        "INSERT INTO homes (code, name, created) VALUES (?, ?, datetime('now'))",
        (code, name.strip() or "Mi hogar"),
    )
    c.execute("INSERT INTO config (home, key, value) VALUES (?, 'name_a', 'Persona 1')", (code,))
    c.execute("INSERT INTO config (home, key, value) VALUES (?, 'name_b', 'Persona 2')", (code,))
    c.commit()
    return code


def get_home_name(code: str) -> str:
    row = _conn().execute("SELECT name FROM homes WHERE code = ?", (code,)).fetchone()
    return row["name"] if row else "Mi hogar"


def set_home_name(code: str, name: str) -> None:
    c = _conn()
    c.execute("UPDATE homes SET name = ? WHERE code = ?", (name.strip() or "Mi hogar", code))
    c.commit()


# ---------- config (nombres de las personas) ----------
def get_config(home: str, key: str):
    row = _conn().execute(
        "SELECT value FROM config WHERE home = ? AND key = ?", (home, key)
    ).fetchone()
    return row["value"] if row else None


def set_config(home: str, key: str, value: str) -> None:
    c = _conn()
    c.execute(
        "INSERT INTO config (home, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(home, key) DO UPDATE SET value = excluded.value",
        (home, key, value),
    )
    c.commit()


def get_names(home: str) -> list[str]:
    return [get_config(home, "name_a") or "Persona 1",
            get_config(home, "name_b") or "Persona 2"]


# ---------- meals ----------
def get_meals(home: str) -> dict:
    rows = _conn().execute(
        "SELECT day, slot, content FROM meals WHERE home = ?", (home,)
    ).fetchall()
    data = {d: {slot: "" for slot, _ in MEAL_SLOTS} for d in range(len(DAYS))}
    for r in rows:
        if r["day"] in data:
            data[r["day"]][r["slot"]] = r["content"]
    return data


def set_meal(home: str, day: int, slot: str, content: str) -> None:
    c = _conn()
    c.execute(
        "INSERT INTO meals (home, day, slot, content) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(home, day, slot) DO UPDATE SET content = excluded.content",
        (home, day, slot, content),
    )
    c.commit()


def clear_meals(home: str) -> None:
    c = _conn()
    c.execute("DELETE FROM meals WHERE home = ?", (home,))
    c.commit()


# ---------- tasks (planificación semanal) ----------
def get_tasks(home: str) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM tasks WHERE home = ? ORDER BY created ASC", (home,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["days"] = _csv_to_ints(d.get("days") or "")
        d["done_days"] = _csv_to_ints(d.get("done_days") or "")
        out.append(d)
    return out


def add_task(home: str, name: str, assignee: int, days) -> None:
    c = _conn()
    c.execute(
        "INSERT INTO tasks (id, home, name, assignee, days, done_days, created) "
        "VALUES (?, ?, ?, ?, ?, '', datetime('now'))",
        (_new_id(), home, name, assignee, _ints_to_csv(days)),
    )
    c.commit()


def toggle_task_day(task_id: str, day: int) -> None:
    c = _conn()
    row = c.execute("SELECT done_days FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        return
    done = set(_csv_to_ints(row["done_days"] or ""))
    done.discard(day) if day in done else done.add(day)
    c.execute("UPDATE tasks SET done_days = ? WHERE id = ?", (_ints_to_csv(done), task_id))
    c.commit()


def delete_task(task_id: str) -> None:
    c = _conn()
    c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    c.commit()


def reset_week(home: str) -> None:
    c = _conn()
    c.execute("UPDATE tasks SET done_days = '' WHERE home = ?", (home,))
    c.commit()


# ---------- shopping ----------
def get_shopping(home: str) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM shopping WHERE home = ? ORDER BY created ASC", (home,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_shopping(home: str, name: str, cat: str) -> None:
    c = _conn()
    c.execute(
        "INSERT INTO shopping (id, home, name, cat, done, created) "
        "VALUES (?, ?, ?, ?, 0, datetime('now'))",
        (_new_id(), home, name, cat),
    )
    c.commit()


def toggle_shopping(item_id: str) -> None:
    c = _conn()
    c.execute("UPDATE shopping SET done = 1 - done WHERE id = ?", (item_id,))
    c.commit()


def delete_shopping(item_id: str) -> None:
    c = _conn()
    c.execute("DELETE FROM shopping WHERE id = ?", (item_id,))
    c.commit()


def clear_bought(home: str) -> None:
    c = _conn()
    c.execute("DELETE FROM shopping WHERE home = ? AND done = 1", (home,))
    c.commit()


def shopping_has(home: str, name: str) -> bool:
    row = _conn().execute(
        "SELECT 1 FROM shopping WHERE home = ? AND LOWER(name) = LOWER(?) LIMIT 1",
        (home, name),
    ).fetchone()
    return row is not None


# ---------- supplies ----------
def get_supplies(home: str) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM supplies WHERE home = ? ORDER BY name COLLATE NOCASE", (home,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_supply(home: str, name: str) -> None:
    c = _conn()
    c.execute("INSERT INTO supplies (id, home, name, level) VALUES (?, ?, ?, 'ok')",
              (_new_id(), home, name))
    c.commit()


def set_level(supply_id: str, level: str) -> None:
    c = _conn()
    c.execute("UPDATE supplies SET level = ? WHERE id = ?", (level, supply_id))
    c.commit()


def delete_supply(supply_id: str) -> None:
    c = _conn()
    c.execute("DELETE FROM supplies WHERE id = ?", (supply_id,))
    c.commit()


# ---------- respaldo / exportación (por hogar) ----------
def export_all(home: str) -> dict:
    return {
        "version": 2,
        "home_name": get_home_name(home),
        "names": get_names(home),
        "meals": get_meals(home),
        "tasks": get_tasks(home),
        "shopping": get_shopping(home),
        "supplies": get_supplies(home),
    }


def import_all(home: str, data: dict) -> None:
    """Reemplaza los datos del hogar indicado con los del respaldo."""
    c = _conn()
    cur = c.cursor()
    cur.execute("DELETE FROM meals WHERE home = ?", (home,))
    cur.execute("DELETE FROM tasks WHERE home = ?", (home,))
    cur.execute("DELETE FROM shopping WHERE home = ?", (home,))
    cur.execute("DELETE FROM supplies WHERE home = ?", (home,))

    if data.get("home_name"):
        set_home_name(home, str(data["home_name"]))
    names = data.get("names") or ["Persona 1", "Persona 2"]
    set_config(home, "name_a", str(names[0]))
    set_config(home, "name_b", str(names[1]))

    for day_key, slots in (data.get("meals") or {}).items():
        day = int(day_key)
        for slot, content in (slots or {}).items():
            if content:
                cur.execute(
                    "INSERT OR REPLACE INTO meals (home, day, slot, content) VALUES (?, ?, ?, ?)",
                    (home, day, slot, str(content)),
                )
    for t in data.get("tasks") or []:
        cur.execute(
            "INSERT INTO tasks (id, home, name, assignee, days, done_days, created) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (_new_id(), home, str(t.get("name", "")), int(t.get("assignee", 0)),
             _ints_to_csv(t.get("days") or []), _ints_to_csv(t.get("done_days") or [])),
        )
    for s in data.get("shopping") or []:
        cur.execute(
            "INSERT INTO shopping (id, home, name, cat, done, created) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (_new_id(), home, str(s.get("name", "")), str(s.get("cat", "Otros")),
             int(s.get("done", 0))),
        )
    for s in data.get("supplies") or []:
        cur.execute(
            "INSERT INTO supplies (id, home, name, level) VALUES (?, ?, ?, ?)",
            (_new_id(), home, str(s.get("name", "")), str(s.get("level", "ok"))),
        )
    c.commit()
