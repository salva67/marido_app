"""Capa de datos del Tablero del hogar.

Usa SQLite con una conexión por hilo. Toda la persistencia pasa por aquí,
así que cambiar a otro motor (Postgres/Supabase) sólo requiere reescribir
este módulo.

Las tareas tienen planificación semanal: cada tarea se agenda a uno o varios
días (campo `days`, CSV de índices 0-6) y el completado se trackea por día
de la semana (campo `done_days`). "Empezar nueva semana" limpia done_days.
"""

import os
import sqlite3
import threading
import uuid

DB_PATH = os.environ.get("HOGAR_DB", "hogar.db")

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DAY_SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MEAL_SLOTS = [("breakfast", "Desayuno"), ("lunch", "Almuerzo"), ("dinner", "Cena")]
CATEGORIES = ["Alimentos", "Limpieza", "Otros"]
LEVELS = {"ok": "Bien", "low": "Poco", "out": "Agotado"}

_TASKS_DDL = """
    CREATE TABLE tasks (
        id        TEXT PRIMARY KEY,
        name      TEXT    NOT NULL,
        assignee  INTEGER NOT NULL,
        days      TEXT    NOT NULL DEFAULT '',
        done_days TEXT    NOT NULL DEFAULT '',
        created   TEXT    NOT NULL
    );
"""

_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Una conexión por hilo (Streamlit usa varios)."""
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL;")
    return _local.conn


def init_db() -> None:
    c = _conn()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meals (
            day     INTEGER NOT NULL,
            slot    TEXT    NOT NULL,
            content TEXT    NOT NULL DEFAULT '',
            PRIMARY KEY (day, slot)
        );
        CREATE TABLE IF NOT EXISTS shopping (
            id      TEXT PRIMARY KEY,
            name    TEXT    NOT NULL,
            cat     TEXT    NOT NULL,
            done    INTEGER NOT NULL DEFAULT 0,
            created TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS supplies (
            id    TEXT PRIMARY KEY,
            name  TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'ok'
        );
        """
        + _TASKS_DDL.replace("CREATE TABLE tasks", "CREATE TABLE IF NOT EXISTS tasks")
    )
    _migrate()
    if get_config("name_a") is None:
        set_config("name_a", "Persona 1")
    if get_config("name_b") is None:
        set_config("name_b", "Persona 2")
    c.commit()


def _migrate() -> None:
    """Lleva una base con el esquema viejo de tareas (freq/done) al nuevo
    (days/done_days). Sin datos previos, no hace nada."""
    c = _conn()
    cols = [r["name"] for r in c.execute("PRAGMA table_info(tasks)").fetchall()]
    if cols and "days" not in cols:
        # Esquema viejo incompatible: lo reemplazamos por el nuevo.
        c.execute("DROP TABLE tasks")
        c.execute(_TASKS_DDL)
        c.commit()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _csv_to_ints(s: str) -> list[int]:
    return [int(x) for x in s.split(",") if x.strip() != ""] if s else []


def _ints_to_csv(values) -> str:
    return ",".join(str(x) for x in sorted(set(values)))


# ---------- config ----------
def get_config(key: str):
    row = _conn().execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_config(key: str, value: str) -> None:
    c = _conn()
    c.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    c.commit()


def get_names() -> list[str]:
    return [get_config("name_a") or "Persona 1", get_config("name_b") or "Persona 2"]


# ---------- meals ----------
def get_meals() -> dict:
    rows = _conn().execute("SELECT day, slot, content FROM meals").fetchall()
    data = {d: {slot: "" for slot, _ in MEAL_SLOTS} for d in range(len(DAYS))}
    for r in rows:
        if r["day"] in data:
            data[r["day"]][r["slot"]] = r["content"]
    return data


def set_meal(day: int, slot: str, content: str) -> None:
    c = _conn()
    c.execute(
        "INSERT INTO meals (day, slot, content) VALUES (?, ?, ?) "
        "ON CONFLICT(day, slot) DO UPDATE SET content = excluded.content",
        (day, slot, content),
    )
    c.commit()


def clear_meals() -> None:
    c = _conn()
    c.execute("DELETE FROM meals")
    c.commit()


# ---------- tasks (planificación semanal) ----------
def get_tasks() -> list[dict]:
    rows = _conn().execute("SELECT * FROM tasks ORDER BY created ASC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["days"] = _csv_to_ints(d.get("days") or "")
        d["done_days"] = _csv_to_ints(d.get("done_days") or "")
        out.append(d)
    return out


def add_task(name: str, assignee: int, days) -> None:
    c = _conn()
    c.execute(
        "INSERT INTO tasks (id, name, assignee, days, done_days, created) "
        "VALUES (?, ?, ?, ?, '', datetime('now'))",
        (_new_id(), name, assignee, _ints_to_csv(days)),
    )
    c.commit()


def toggle_task_day(task_id: str, day: int) -> None:
    """Marca/desmarca una tarea para un día puntual de la semana."""
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


def reset_week() -> None:
    """Desmarca todas las tareas para arrancar una semana nueva."""
    c = _conn()
    c.execute("UPDATE tasks SET done_days = ''")
    c.commit()


# ---------- shopping ----------
def get_shopping() -> list[dict]:
    rows = _conn().execute("SELECT * FROM shopping ORDER BY created ASC").fetchall()
    return [dict(r) for r in rows]


def add_shopping(name: str, cat: str) -> None:
    c = _conn()
    c.execute(
        "INSERT INTO shopping (id, name, cat, done, created) "
        "VALUES (?, ?, ?, 0, datetime('now'))",
        (_new_id(), name, cat),
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


def clear_bought() -> None:
    c = _conn()
    c.execute("DELETE FROM shopping WHERE done = 1")
    c.commit()


def shopping_has(name: str) -> bool:
    row = _conn().execute(
        "SELECT 1 FROM shopping WHERE LOWER(name) = LOWER(?) LIMIT 1", (name,)
    ).fetchone()
    return row is not None


# ---------- supplies ----------
def get_supplies() -> list[dict]:
    rows = _conn().execute("SELECT * FROM supplies ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def add_supply(name: str) -> None:
    c = _conn()
    c.execute("INSERT INTO supplies (id, name, level) VALUES (?, ?, 'ok')", (_new_id(), name))
    c.commit()


def set_level(supply_id: str, level: str) -> None:
    c = _conn()
    c.execute("UPDATE supplies SET level = ? WHERE id = ?", (level, supply_id))
    c.commit()


def delete_supply(supply_id: str) -> None:
    c = _conn()
    c.execute("DELETE FROM supplies WHERE id = ?", (supply_id,))
    c.commit()


# ---------- respaldo / exportación ----------
def export_all() -> dict:
    """Estado completo del tablero, listo para serializar a JSON."""
    return {
        "version": 1,
        "names": get_names(),
        "meals": get_meals(),       # {día: {slot: contenido}}
        "tasks": get_tasks(),       # con days/done_days como listas
        "shopping": get_shopping(),
        "supplies": get_supplies(),
    }


def import_all(data: dict) -> None:
    """Reemplaza todos los datos a partir de un respaldo previamente exportado.
    Es destructivo: borra lo actual y carga lo del archivo."""
    c = _conn()
    cur = c.cursor()
    cur.execute("DELETE FROM config")
    cur.execute("DELETE FROM meals")
    cur.execute("DELETE FROM tasks")
    cur.execute("DELETE FROM shopping")
    cur.execute("DELETE FROM supplies")

    names = data.get("names") or ["Persona 1", "Persona 2"]
    cur.execute("INSERT INTO config (key, value) VALUES ('name_a', ?)", (str(names[0]),))
    cur.execute("INSERT INTO config (key, value) VALUES ('name_b', ?)", (str(names[1]),))

    meals = data.get("meals") or {}
    for day_key, slots in meals.items():
        day = int(day_key)
        for slot, content in (slots or {}).items():
            if content:
                cur.execute(
                    "INSERT OR REPLACE INTO meals (day, slot, content) VALUES (?, ?, ?)",
                    (day, slot, str(content)),
                )

    for t in data.get("tasks") or []:
        cur.execute(
            "INSERT INTO tasks (id, name, assignee, days, done_days, created) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (
                t.get("id") or _new_id(),
                str(t.get("name", "")),
                int(t.get("assignee", 0)),
                _ints_to_csv(t.get("days") or []),
                _ints_to_csv(t.get("done_days") or []),
            ),
        )

    for s in data.get("shopping") or []:
        cur.execute(
            "INSERT INTO shopping (id, name, cat, done, created) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (s.get("id") or _new_id(), str(s.get("name", "")),
             str(s.get("cat", "Otros")), int(s.get("done", 0))),
        )

    for s in data.get("supplies") or []:
        cur.execute(
            "INSERT INTO supplies (id, name, level) VALUES (?, ?, ?)",
            (s.get("id") or _new_id(), str(s.get("name", "")), str(s.get("level", "ok"))),
        )

    c.commit()
