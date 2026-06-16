"""Capa de datos del Tablero del hogar.

Usa SQLite con una conexión por hilo. Toda la persistencia pasa por aquí,
así que cambiar a otro motor (Postgres/Supabase) sólo requiere reescribir
este módulo.
"""

import os
import sqlite3
import threading
import uuid

DB_PATH = os.environ.get("HOGAR_DB", "hogar.db")

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MEAL_SLOTS = [("breakfast", "Desayuno"), ("lunch", "Almuerzo"), ("dinner", "Cena")]
CATEGORIES = ["Alimentos", "Limpieza", "Otros"]
LEVELS = {"ok": "Bien", "low": "Poco", "out": "Agotado"}

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
        CREATE TABLE IF NOT EXISTS tasks (
            id       TEXT PRIMARY KEY,
            name     TEXT    NOT NULL,
            assignee INTEGER NOT NULL,
            freq     TEXT    NOT NULL,
            done     INTEGER NOT NULL DEFAULT 0,
            created  TEXT    NOT NULL
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
    )
    # Nombres por defecto si aún no existen.
    if get_config("name_a") is None:
        set_config("name_a", "Persona 1")
    if get_config("name_b") is None:
        set_config("name_b", "Persona 2")
    c.commit()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


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


# ---------- tasks ----------
def get_tasks() -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM tasks ORDER BY done ASC, created DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def add_task(name: str, assignee: int, freq: str) -> None:
    c = _conn()
    c.execute(
        "INSERT INTO tasks (id, name, assignee, freq, done, created) "
        "VALUES (?, ?, ?, ?, 0, datetime('now'))",
        (_new_id(), name, assignee, freq),
    )
    c.commit()


def toggle_task(task_id: str) -> None:
    c = _conn()
    c.execute("UPDATE tasks SET done = 1 - done WHERE id = ?", (task_id,))
    c.commit()


def delete_task(task_id: str) -> None:
    c = _conn()
    c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    c.commit()


def reset_tasks() -> None:
    c = _conn()
    c.execute("UPDATE tasks SET done = 0")
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
    c.execute(
        "INSERT INTO supplies (id, name, level) VALUES (?, ?, 'ok')",
        (_new_id(), name),
    )
    c.commit()


def set_level(supply_id: str, level: str) -> None:
    c = _conn()
    c.execute("UPDATE supplies SET level = ? WHERE id = ?", (level, supply_id))
    c.commit()


def delete_supply(supply_id: str) -> None:
    c = _conn()
    c.execute("DELETE FROM supplies WHERE id = ?", (supply_id,))
    c.commit()
