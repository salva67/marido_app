"""Tablero del hogar — app Streamlit multi-hogar (archivo único).

Toda la lógica (datos + interfaz) vive en este único archivo, así no hay
que mantener dos archivos sincronizados. Cada grupo tiene su propio "hogar"
identificado por un código corto; no hay login.
"""

import datetime
import io
import json
import os
import random
import sqlite3
import threading
import uuid

import pandas as pd
import streamlit as st

# ===================== CAPA DE DATOS =====================
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
    # Migrar ANTES de crear los índices: una base vieja puede tener tablas sin la
    # columna `home`, y el índice fallaría. _migrate las recrea con el esquema nuevo.
    _migrate()
    c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_home ON tasks(home);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shop_home ON shopping(home);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_supp_home ON supplies(home);")
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


# ===================== APLICACIÓN =====================
st.set_page_config(
    page_title="Tablero del hogar",
    page_icon="🏡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

init_db()


def build_excel(data: dict) -> bytes:
    """Arma un .xlsx con una hoja por sección."""
    nombres = data["names"]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        meals = data["meals"]
        comidas = []
        for d in range(7):
            day = meals.get(d) or meals.get(str(d)) or {}
            comidas.append({
                "Día": DAYS[d],
                "Desayuno": day.get("breakfast", ""),
                "Almuerzo": day.get("lunch", ""),
                "Cena": day.get("dinner", ""),
            })
        pd.DataFrame(comidas).to_excel(xl, sheet_name="Comidas", index=False)

        tareas = []
        for t in data["tasks"]:
            quien = "Ambos" if t["assignee"] == -1 else nombres[t["assignee"]]
            tareas.append({
                "Tarea": t["name"],
                "Responsable": quien,
                "Días": ", ".join(DAY_SHORT[x] for x in t["days"]),
                "Hechas esta semana": ", ".join(DAY_SHORT[x] for x in t["done_days"]) or "—",
            })
        pd.DataFrame(tareas or [{"Tarea": "", "Responsable": "", "Días": "", "Hechas esta semana": ""}]
                     ).to_excel(xl, sheet_name="Tareas", index=False)

        compras = [{"Producto": s["name"], "Categoría": s["cat"],
                    "Comprado": "Sí" if s["done"] else "No"} for s in data["shopping"]]
        pd.DataFrame(compras or [{"Producto": "", "Categoría": "", "Comprado": ""}]
                     ).to_excel(xl, sheet_name="Compras", index=False)

        insumos = [{"Insumo": s["name"], "Nivel": LEVELS.get(s["level"], s["level"])}
                   for s in data["supplies"]]
        pd.DataFrame(insumos or [{"Insumo": "", "Nivel": ""}]
                     ).to_excel(xl, sheet_name="Insumos", index=False)
    return buf.getvalue()


# ---------------------------------------------------------------- estilos
st.markdown(
    """
    <style>
      .stApp { background:#FBFAF6; }
      .block-container { max-width: 780px; padding-top: 1.4rem; }
      .home-head {
        background:#37503F; color:#F3F1E9; padding:22px 24px;
        border-radius:18px; margin-bottom:18px;
      }
      .home-head .eyebrow {
        font-size:12px; letter-spacing:.14em; text-transform:uppercase;
        color:#A9C3AD; font-weight:600;
      }
      .home-head h1 {
        font-family:Georgia,'Times New Roman',serif; font-weight:500;
        font-size:30px; margin:4px 0 8px; color:#F3F1E9;
      }
      .home-head .couple { font-size:14px; color:#CBDBCD; }
      .home-head .dot {
        display:inline-block; width:9px; height:9px; border-radius:50%;
        margin-right:5px; vertical-align:middle;
      }
      .stTabs [data-baseweb="tab-list"] { gap:6px; }
      .stTabs [data-baseweb="tab"] {
        background:#fff; border:1px solid #E7E4DA; border-radius:12px;
        padding:8px 16px; font-weight:600;
      }
      .stTabs [aria-selected="true"] {
        background:#4A6B52 !important; color:#fff !important; border-color:#4A6B52;
      }
      .stButton button[kind="primary"] { background:#4A6B52; border:none; }
      .stButton button[kind="primary"]:hover { background:#37503F; }
      h2, h3 { font-family:Georgia,serif !important; font-weight:500 !important; }
      .muted { color:#83887E; font-size:13.5px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- gate de hogar
def render_gate() -> None:
    st.markdown(
        """
        <div class="home-head">
          <div class="eyebrow">Tablero del hogar</div>
          <h1>Organizá tu casa en pareja o familia</h1>
          <div class="couple">Comidas · tareas · compras · insumos — todo en un lugar.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("Entrá a tu hogar")
    tab_new, tab_join = st.tabs(["✨ Crear un hogar nuevo", "🔑 Entrar con código"])

    with tab_new:
        st.markdown('<p class="muted">Creá un espacio para tu casa y compartí el código '
                    "con quienes vivan con vos.</p>", unsafe_allow_html=True)
        nm = st.text_input("Nombre del hogar (opcional)", placeholder="Casa de los López")
        if st.button("Crear hogar", type="primary", use_container_width=True):
            code = create_home(nm)
            st.session_state["home"] = code
            st.query_params["home"] = code
            st.rerun()

    with tab_join:
        st.markdown('<p class="muted">Pedí el código a quien creó el hogar (6 caracteres).</p>',
                    unsafe_allow_html=True)
        code_in = st.text_input("Código del hogar", max_chars=6, placeholder="Ej: ZEKZJ2")
        if st.button("Entrar", type="primary", use_container_width=True):
            code = code_in.strip().upper()
            if home_exists(code):
                st.session_state["home"] = code
                st.query_params["home"] = code
                st.rerun()
            else:
                st.error("No existe un hogar con ese código. Revisalo o creá uno nuevo.")


def resolve_home() -> str | None:
    qp_home = st.query_params.get("home")
    if qp_home and home_exists(qp_home):
        st.session_state["home"] = qp_home
        return qp_home
    return st.session_state.get("home")


home = resolve_home()
if not home:
    render_gate()
    st.stop()

names = get_names(home)
home_name = get_home_name(home)

# ---------------------------------------------------------------- header
st.markdown(
    f"""
    <div class="home-head">
      <div class="eyebrow">Nuestro hogar · código {home}</div>
      <h1>{home_name}</h1>
      <div class="couple">
        <span class="dot" style="background:#A9C3AD"></span>{names[0]}
        &nbsp;·&nbsp;
        <span class="dot" style="background:#C0744F"></span>{names[1]}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("⚙️  Hogar, nombres y cómo invitar"):
    st.markdown(f"**Código de tu hogar:** `{home}`")
    st.markdown('<p class="muted">Compartí este código (o copiá el enlace de tu navegador, '
                "que ya lo incluye) para que otras personas entren a este mismo hogar. "
                "Cualquiera con el código puede ver y editar los datos.</p>",
                unsafe_allow_html=True)
    st.code(f"?home={home}", language=None)

    st.markdown("---")
    new_home_name = st.text_input("Nombre del hogar", value=home_name, max_chars=40)
    col_a, col_b = st.columns(2)
    new_a = col_a.text_input("Persona 1", value=names[0], max_chars=24)
    new_b = col_b.text_input("Persona 2", value=names[1], max_chars=24)
    if st.button("Guardar", type="primary"):
        set_home_name(home, new_home_name)
        set_config(home, "name_a", new_a.strip() or "Persona 1")
        set_config(home, "name_b", new_b.strip() or "Persona 2")
        st.rerun()

    st.markdown("---")
    if st.button("🚪 Salir / cambiar de hogar"):
        st.session_state.pop("home", None)
        st.query_params.clear()
        st.rerun()

tab_meals, tab_tasks, tab_shop, tab_supp = st.tabs(
    ["🍽️ Comidas", "🧹 Tareas", "🛒 Compras", "📦 Insumos"]
)


def today_index() -> int:
    return datetime.date.today().weekday()  # lunes = 0


def who_label(assignee: int) -> str:
    return "Ambos" if assignee == -1 else names[assignee]


# ================================================================ COMIDAS
with tab_meals:
    st.subheader("Comidas de la semana")
    st.markdown('<p class="muted">Editá cada casillero. Los cambios se guardan al confirmar la celda.</p>',
                unsafe_allow_html=True)

    meals = get_meals(home)
    df = pd.DataFrame(
        {label: [meals[d][slot] for d in range(len(DAYS))] for slot, label in MEAL_SLOTS},
        index=DAYS,
    )
    df.index.name = "Día"
    edited = st.data_editor(
        df, use_container_width=True, key="meals_editor",
        column_config={label: st.column_config.TextColumn(label, width="medium")
                       for _, label in MEAL_SLOTS},
    )
    changed = False
    for d in range(len(DAYS)):
        for slot, label in MEAL_SLOTS:
            new_val = str(edited.iloc[d][label] or "")
            if new_val != meals[d][slot]:
                set_meal(home, d, slot, new_val)
                changed = True
    if changed:
        st.toast("Comidas guardadas", icon="✅")

    st.caption(f"Hoy es {DAYS[today_index()].lower()}.")
    if st.button("Limpiar semana"):
        clear_meals(home)
        st.rerun()


# ================================================================ TAREAS
with tab_tasks:
    st.subheader("Limpieza y tareas")
    st.markdown('<p class="muted">Cada tarea se agenda a los días que quieras. '
                "Arriba ves lo de hoy; abajo, la semana completa.</p>", unsafe_allow_html=True)

    tasks = get_tasks(home)
    ti = today_index()

    if tasks:
        today_all = [t for t in tasks if ti in t["days"]]
        today_done = [t for t in today_all if ti in t["done_days"]]
        week_slots = sum(len(t["days"]) for t in tasks)
        week_done = sum(len(set(t["done_days"]) & set(t["days"])) for t in tasks)

        m1, m2, m3 = st.columns(3)
        pend_hoy = len(today_all) - len(today_done)
        m1.metric("Hoy", f"{len(today_done)}/{len(today_all)}" if today_all else "—",
                  delta=(f"{pend_hoy} pendientes" if pend_hoy else "todo listo") if today_all else "sin tareas",
                  delta_color="off")
        m2.metric("Semana", f"{week_done}/{week_slots}")
        load_a = sum(len(t["days"]) for t in tasks if t["assignee"] in (0, -1))
        load_b = sum(len(t["days"]) for t in tasks if t["assignee"] in (1, -1))
        m3.metric("Reparto", f"{load_a} · {load_b}", help=f"{names[0]} · {names[1]} (tareas/semana)")

        st.markdown(f"#### Hoy te toca ({DAYS[ti].lower()})")
        if not today_all:
            st.success("Nada agendado para hoy. 🎉")
        else:
            for t in today_all:
                done = ti in t["done_days"]
                lbl = f"~~{t['name']}~~ · {who_label(t['assignee'])}" if done else f"{t['name']} · {who_label(t['assignee'])}"
                if st.checkbox(lbl, value=done, key=f"today_{t['id']}") != done:
                    toggle_task_day(t["id"], ti)
                    st.rerun()

        st.markdown("#### Planificación semanal")
        for d in range(7):
            day_tasks = [t for t in tasks if d in t["days"]]
            st.markdown(f"**{'🟢 ' if d == ti else ''}{DAYS[d]}{' · hoy' if d == ti else ''}**")
            if not day_tasks:
                st.caption("Libre")
                continue
            for t in day_tasks:
                done = d in t["done_days"]
                lbl = f"~~{t['name']}~~ · {who_label(t['assignee'])}" if done else f"{t['name']} · {who_label(t['assignee'])}"
                col_chk, col_del = st.columns([10, 1])
                if col_chk.checkbox(lbl, value=done, key=f"week_{t['id']}_{d}") != done:
                    toggle_task_day(t["id"], d)
                    st.rerun()
                if d == min(t["days"]):
                    if col_del.button("🗑", key=f"deltask_{t['id']}", help="Eliminar tarea"):
                        delete_task(t["id"])
                        st.rerun()

        st.divider()
        if st.button("🔄 Empezar nueva semana", help="Desmarca todas las tareas sin borrarlas"):
            reset_week(home)
            st.rerun()
    else:
        st.info("Todavía no hay tareas. Agregá la primera abajo y elegí en qué días toca.")

    with st.expander("➕ Agregar tarea", expanded=not tasks):
        with st.form("add_task", clear_on_submit=True):
            t_name = st.text_input("Tarea", placeholder="Sacar la basura…")
            cA, cB = st.columns(2)
            who = cA.selectbox("¿Quién la hace?", options=[0, 1, -1], format_func=who_label)
            every_day = cB.checkbox("Todos los días")
            day_sel = st.multiselect("¿Qué días?", options=list(range(7)),
                                     format_func=lambda d: DAYS[d],
                                     help="Elegí uno o varios días, o marcá «Todos los días».",
                                     disabled=every_day)
            if st.form_submit_button("Agregar tarea", type="primary", use_container_width=True):
                chosen = list(range(7)) if every_day else day_sel
                if not t_name.strip():
                    st.warning("Escribí el nombre de la tarea.")
                elif not chosen:
                    st.warning("Elegí al menos un día (o marcá «Todos los días»).")
                else:
                    add_task(home, t_name.strip(), who, chosen)
                    st.rerun()


# ================================================================ COMPRAS
with tab_shop:
    st.subheader("Lista de compras")
    st.markdown('<p class="muted">Sumá lo que falte y marcá lo que ya pusiste en el carrito.</p>',
                unsafe_allow_html=True)

    with st.form("add_shop", clear_on_submit=True):
        c1, c2 = st.columns([4, 2])
        s_name = c1.text_input("Producto", placeholder="Leche…", label_visibility="collapsed")
        s_cat = c2.selectbox("Categoría", CATEGORIES, label_visibility="collapsed")
        if st.form_submit_button("Agregar producto", type="primary", use_container_width=True):
            if s_name.strip():
                add_shopping(home, s_name.strip(), s_cat)
                st.rerun()

    shopping = get_shopping(home)
    if not shopping:
        st.info("La lista está vacía.")
    else:
        for cat in CATEGORIES:
            items = [s for s in shopping if s["cat"] == cat]
            if not items:
                continue
            st.markdown(f"**{cat}**")
            for s in items:
                col_chk, col_del = st.columns([9, 1])
                label = f"~~{s['name']}~~" if s["done"] else s["name"]
                if col_chk.checkbox(label, value=bool(s["done"]), key=f"shop_{s['id']}") != bool(s["done"]):
                    toggle_shopping(s["id"])
                    st.rerun()
                if col_del.button("🗑", key=f"delshop_{s['id']}", help="Eliminar"):
                    delete_shopping(s["id"])
                    st.rerun()

        if any(s["done"] for s in shopping):
            if st.button("Quitar comprados"):
                clear_bought(home)
                st.rerun()

        pendientes = [s for s in shopping if not s["done"]]
        if pendientes:
            txt = "LISTA DE COMPRAS\n\n" + "\n".join(f"[ ] {s['name']}  ({s['cat']})" for s in pendientes)
            st.download_button("⬇️ Descargar lista para el super (.txt)",
                               data=txt, file_name="lista-compras.txt", mime="text/plain")


# ================================================================ INSUMOS
with tab_supp:
    st.subheader("Inventario de insumos")
    st.markdown('<p class="muted">Marcá el nivel de cada cosa. Lo que esté en poco o agotado lo mandás a compras.</p>',
                unsafe_allow_html=True)

    with st.form("add_supply", clear_on_submit=True):
        c1, c2 = st.columns([5, 2])
        sup_name = c1.text_input("Insumo", placeholder="Arroz, papel, detergente…", label_visibility="collapsed")
        if c2.form_submit_button("Agregar insumo", type="primary", use_container_width=True):
            if sup_name.strip():
                add_supply(home, sup_name.strip())
                st.rerun()

    supplies = get_supplies(home)
    if not supplies:
        st.info("Sin insumos cargados todavía.")
    else:
        level_keys = list(LEVELS.keys())
        for s in supplies:
            col_name, col_lvl, col_del = st.columns([4, 4, 1])
            col_name.markdown(f"**{s['name']}**")
            current = level_keys.index(s["level"]) if s["level"] in level_keys else 0
            choice = col_lvl.radio("Nivel", options=level_keys, index=current,
                                   format_func=lambda k: LEVELS[k], horizontal=True,
                                   key=f"lvl_{s['id']}", label_visibility="collapsed")
            if choice != s["level"]:
                set_level(s["id"], choice)
                st.rerun()
            if col_del.button("🗑", key=f"delsup_{s['id']}", help="Eliminar"):
                delete_supply(s["id"])
                st.rerun()

            if s["level"] in ("low", "out"):
                if shopping_has(home, s["name"]):
                    col_name.caption("✓ Ya está en la lista de compras")
                else:
                    if col_name.button("+ Agregar a compras", key=f"toshop_{s['id']}"):
                        add_shopping(home, s["name"], "Alimentos")
                        st.toast(f"{s['name']} → lista de compras", icon="🛒")
                        st.rerun()


# ================================================================ RESPALDO
st.divider()
with st.expander("💾  Respaldo y descargas — guardá una copia de todo"):
    st.markdown('<p class="muted">En Streamlit Cloud los datos pueden borrarse cuando la app se '
                "reinicia. Descargá un respaldo cada tanto; si perdés los datos, lo volvés a cargar acá. "
                "El respaldo es sólo de este hogar.</p>", unsafe_allow_html=True)
    data = export_all(home)
    col1, col2 = st.columns(2)
    col1.download_button("⬇️ Descargar todo (Excel)", data=build_excel(data),
                         file_name=f"tablero-{home}.xlsx",
                         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         use_container_width=True)
    col2.download_button("⬇️ Descargar respaldo (.json)",
                         data=json.dumps(data, ensure_ascii=False, indent=2),
                         file_name=f"respaldo-{home}.json", mime="application/json",
                         use_container_width=True)
    st.markdown("---")
    st.caption("¿Se reinició la app? Subí tu último respaldo `.json` para recuperar este hogar:")
    up = st.file_uploader("Restaurar respaldo", type="json", label_visibility="collapsed")
    if up is not None:
        st.warning("Restaurar reemplaza todos los datos actuales de este hogar por los del archivo.")
        if st.button("Restaurar ahora", type="primary"):
            try:
                import_all(home, json.load(up))
                st.success("Datos restaurados.")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo leer el respaldo: {e}")

st.markdown('<p class="muted" style="text-align:center;margin-top:20px">'
            "Hecho para organizar el hogar. Los datos se guardan automáticamente.</p>",
            unsafe_allow_html=True)
