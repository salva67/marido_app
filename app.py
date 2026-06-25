"""Tablero del hogar — app Streamlit multi-hogar (archivo único, PostgreSQL).

Datos permanentes en Postgres/Supabase. La conexión se toma de los Secrets
(DATABASE_URL). Todo (datos + interfaz) vive en este único archivo.
"""

import datetime
import io
import json
import os
import random
import threading
import uuid

import pandas as pd
import psycopg
import streamlit as st
from psycopg.rows import dict_row

# ===================== CAPA DE DATOS (PostgreSQL) =====================
DATABASE_URL = os.environ.get("DATABASE_URL", "")

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DAY_SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MEAL_SLOTS = [("breakfast", "Desayuno"), ("lunch", "Almuerzo"), ("dinner", "Cena")]
CATEGORIES = ["Alimentos", "Limpieza", "Otros"]
LEVELS = {"ok": "Bien", "low": "Poco", "out": "Agotado"}
EXPENSE_CATS = ["Supermercado", "Servicios", "Hogar", "Salud", "Ocio", "Otros"]

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_local = threading.local()


def configure(url: str) -> None:
    """Setea la cadena de conexión (la llama la app desde st.secrets)."""
    global DATABASE_URL
    DATABASE_URL = url
    c = getattr(_local, "conn", None)
    if c is not None:
        try:
            c.close()
        except Exception:
            pass
        _local.conn = None


def _conn() -> psycopg.Connection:
    """Conexión por hilo, con reconexión automática si se cayó."""
    c = getattr(_local, "conn", None)
    if c is not None and not c.closed:
        return c
    if not DATABASE_URL:
        raise RuntimeError("Falta DATABASE_URL (configurá la conexión a Postgres).")
    _local.conn = psycopg.connect(
        DATABASE_URL, autocommit=True, row_factory=dict_row, connect_timeout=10
    )
    return _local.conn


def _run(sql: str, params: tuple = (), fetch: str | None = None):
    try:
        cur = _conn().execute(sql, params)
    except psycopg.OperationalError:
        # La conexión pudo haberse cerrado (idle/scale-to-zero): reconectar una vez.
        _local.conn = None
        cur = _conn().execute(sql, params)
    if fetch == "one":
        return cur.fetchone()
    if fetch == "all":
        return cur.fetchall()
    return None


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _csv_to_ints(s: str) -> list[int]:
    return [int(x) for x in s.split(",") if x.strip() != ""] if s else []


def _ints_to_csv(values) -> str:
    return ",".join(str(x) for x in sorted(set(values)))


def init_db() -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS homes (
            code TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT 'Mi hogar',
            created TIMESTAMP NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS config (
            home TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY (home, key))""",
        """CREATE TABLE IF NOT EXISTS meals (
            home TEXT NOT NULL, day INTEGER NOT NULL, slot TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '', PRIMARY KEY (home, day, slot))""",
        """CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, home TEXT NOT NULL, name TEXT NOT NULL,
            assignee INTEGER NOT NULL, days TEXT NOT NULL DEFAULT '',
            done_days TEXT NOT NULL DEFAULT '', created TIMESTAMP NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS shopping (
            id TEXT PRIMARY KEY, home TEXT NOT NULL, name TEXT NOT NULL,
            cat TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
            created TIMESTAMP NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS supplies (
            id TEXT PRIMARY KEY, home TEXT NOT NULL, name TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'ok')""",
        """CREATE TABLE IF NOT EXISTS expenses (
            id TEXT PRIMARY KEY, home TEXT NOT NULL, description TEXT NOT NULL,
            amount DOUBLE PRECISION NOT NULL, payer INTEGER NOT NULL,
            category TEXT NOT NULL, shared INTEGER NOT NULL DEFAULT 1,
            date TEXT NOT NULL, created TIMESTAMP NOT NULL DEFAULT NOW())""",
        "CREATE INDEX IF NOT EXISTS idx_tasks_home ON tasks(home)",
        "CREATE INDEX IF NOT EXISTS idx_shop_home ON shopping(home)",
        "CREATE INDEX IF NOT EXISTS idx_supp_home ON supplies(home)",
        "CREATE INDEX IF NOT EXISTS idx_exp_home ON expenses(home)",
    ]
    with _conn().cursor() as cur:
        for s in stmts:
            cur.execute(s)


# ---------- hogares ----------
def _gen_code(n: int = 6) -> str:
    import random
    return "".join(random.choice(_ALPHABET) for _ in range(n))


def home_exists(code: str) -> bool:
    if not code:
        return False
    return _run("SELECT 1 FROM homes WHERE code = %s", (code,), fetch="one") is not None


def create_home(name: str = "") -> str:
    code = _gen_code()
    while home_exists(code):
        code = _gen_code()
    _run("INSERT INTO homes (code, name) VALUES (%s, %s)", (code, name.strip() or "Mi hogar"))
    _run("INSERT INTO config (home, key, value) VALUES (%s, 'name_a', 'Persona 1')", (code,))
    _run("INSERT INTO config (home, key, value) VALUES (%s, 'name_b', 'Persona 2')", (code,))
    return code


def get_home_name(code: str) -> str:
    row = _run("SELECT name FROM homes WHERE code = %s", (code,), fetch="one")
    return row["name"] if row else "Mi hogar"


def set_home_name(code: str, name: str) -> None:
    _run("UPDATE homes SET name = %s WHERE code = %s", (name.strip() or "Mi hogar", code))


# ---------- config ----------
def get_config(home: str, key: str):
    row = _run("SELECT value FROM config WHERE home = %s AND key = %s", (home, key), fetch="one")
    return row["value"] if row else None


def set_config(home: str, key: str, value: str) -> None:
    _run("INSERT INTO config (home, key, value) VALUES (%s, %s, %s) "
         "ON CONFLICT (home, key) DO UPDATE SET value = EXCLUDED.value", (home, key, value))


def get_names(home: str) -> list[str]:
    return [get_config(home, "name_a") or "Persona 1",
            get_config(home, "name_b") or "Persona 2"]


# ---------- meals ----------
def get_meals(home: str) -> dict:
    rows = _run("SELECT day, slot, content FROM meals WHERE home = %s", (home,), fetch="all") or []
    data = {d: {slot: "" for slot, _ in MEAL_SLOTS} for d in range(len(DAYS))}
    for r in rows:
        if r["day"] in data:
            data[r["day"]][r["slot"]] = r["content"]
    return data


def set_meal(home: str, day: int, slot: str, content: str) -> None:
    _run("INSERT INTO meals (home, day, slot, content) VALUES (%s, %s, %s, %s) "
         "ON CONFLICT (home, day, slot) DO UPDATE SET content = EXCLUDED.content",
         (home, day, slot, content))


def clear_meals(home: str) -> None:
    _run("DELETE FROM meals WHERE home = %s", (home,))


# ---------- tasks ----------
def get_tasks(home: str) -> list[dict]:
    rows = _run("SELECT * FROM tasks WHERE home = %s ORDER BY created ASC", (home,), fetch="all") or []
    out = []
    for r in rows:
        d = dict(r)
        d["days"] = _csv_to_ints(d.get("days") or "")
        d["done_days"] = _csv_to_ints(d.get("done_days") or "")
        out.append(d)
    return out


def add_task(home: str, name: str, assignee: int, days) -> None:
    _run("INSERT INTO tasks (id, home, name, assignee, days, done_days) "
         "VALUES (%s, %s, %s, %s, %s, '')",
         (_new_id(), home, name, assignee, _ints_to_csv(days)))


def toggle_task_day(task_id: str, day: int) -> None:
    row = _run("SELECT done_days FROM tasks WHERE id = %s", (task_id,), fetch="one")
    if not row:
        return
    done = set(_csv_to_ints(row["done_days"] or ""))
    done.discard(day) if day in done else done.add(day)
    _run("UPDATE tasks SET done_days = %s WHERE id = %s", (_ints_to_csv(done), task_id))


def delete_task(task_id: str) -> None:
    _run("DELETE FROM tasks WHERE id = %s", (task_id,))


def reset_week(home: str) -> None:
    _run("UPDATE tasks SET done_days = '' WHERE home = %s", (home,))


# ---------- shopping ----------
def get_shopping(home: str) -> list[dict]:
    return _run("SELECT * FROM shopping WHERE home = %s ORDER BY created ASC", (home,), fetch="all") or []


def add_shopping(home: str, name: str, cat: str) -> None:
    _run("INSERT INTO shopping (id, home, name, cat, done) VALUES (%s, %s, %s, %s, 0)",
         (_new_id(), home, name, cat))


def toggle_shopping(item_id: str) -> None:
    _run("UPDATE shopping SET done = 1 - done WHERE id = %s", (item_id,))


def delete_shopping(item_id: str) -> None:
    _run("DELETE FROM shopping WHERE id = %s", (item_id,))


def clear_bought(home: str) -> None:
    _run("DELETE FROM shopping WHERE home = %s AND done = 1", (home,))


def shopping_has(home: str, name: str) -> bool:
    return _run("SELECT 1 FROM shopping WHERE home = %s AND LOWER(name) = LOWER(%s) LIMIT 1",
                (home, name), fetch="one") is not None


# ---------- supplies ----------
def get_supplies(home: str) -> list[dict]:
    return _run("SELECT * FROM supplies WHERE home = %s ORDER BY LOWER(name)", (home,), fetch="all") or []


def add_supply(home: str, name: str) -> None:
    _run("INSERT INTO supplies (id, home, name, level) VALUES (%s, %s, %s, 'ok')",
         (_new_id(), home, name))


def set_level(supply_id: str, level: str) -> None:
    _run("UPDATE supplies SET level = %s WHERE id = %s", (level, supply_id))


def delete_supply(supply_id: str) -> None:
    _run("DELETE FROM supplies WHERE id = %s", (supply_id,))


# ---------- expenses ----------
def get_expenses(home: str) -> list[dict]:
    return _run("SELECT * FROM expenses WHERE home = %s ORDER BY date DESC, created DESC",
                (home,), fetch="all") or []


def add_expense(home: str, description: str, amount: float, payer: int,
                category: str, shared: bool, date: str) -> None:
    _run("INSERT INTO expenses (id, home, description, amount, payer, category, shared, date) "
         "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
         (_new_id(), home, description, float(amount), int(payer), category,
          1 if shared else 0, date))


def delete_expense(expense_id: str) -> None:
    _run("DELETE FROM expenses WHERE id = %s", (expense_id,))


# ---------- respaldo ----------
def export_all(home: str) -> dict:
    return {
        "version": 3,
        "home_name": get_home_name(home),
        "names": get_names(home),
        "meals": get_meals(home),
        "tasks": get_tasks(home),
        "shopping": get_shopping(home),
        "supplies": get_supplies(home),
        "expenses": get_expenses(home),
    }


def import_all(home: str, data: dict) -> None:
    for tbl in ("meals", "tasks", "shopping", "supplies", "expenses"):
        _run(f"DELETE FROM {tbl} WHERE home = %s", (home,))
    if data.get("home_name"):
        set_home_name(home, str(data["home_name"]))
    names = data.get("names") or ["Persona 1", "Persona 2"]
    set_config(home, "name_a", str(names[0]))
    set_config(home, "name_b", str(names[1]))
    for day_key, slots in (data.get("meals") or {}).items():
        for slot, content in (slots or {}).items():
            if content:
                set_meal(home, int(day_key), slot, str(content))
    for t in data.get("tasks") or []:
        _run("INSERT INTO tasks (id, home, name, assignee, days, done_days) "
             "VALUES (%s, %s, %s, %s, %s, %s)",
             (_new_id(), home, str(t.get("name", "")), int(t.get("assignee", 0)),
              _ints_to_csv(t.get("days") or []), _ints_to_csv(t.get("done_days") or [])))
    for s in data.get("shopping") or []:
        _run("INSERT INTO shopping (id, home, name, cat, done) VALUES (%s, %s, %s, %s, %s)",
             (_new_id(), home, str(s.get("name", "")), str(s.get("cat", "Otros")), int(s.get("done", 0))))
    for s in data.get("supplies") or []:
        _run("INSERT INTO supplies (id, home, name, level) VALUES (%s, %s, %s, %s)",
             (_new_id(), home, str(s.get("name", "")), str(s.get("level", "ok"))))
    for e in data.get("expenses") or []:
        _run("INSERT INTO expenses (id, home, description, amount, payer, category, shared, date) "
             "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
             (_new_id(), home, str(e.get("description", "")), float(e.get("amount", 0)),
              int(e.get("payer", 0)), str(e.get("category", "Otros")),
              int(e.get("shared", 1)), str(e.get("date", ""))))


# ===================== APLICACIÓN =====================
st.set_page_config(
    page_title="Tablero del hogar",
    page_icon="🏡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# --- Conexión a la base permanente (Postgres / Supabase) ---
try:
    _db_url = st.secrets.get("DATABASE_URL", "")
except Exception:
    _db_url = ""
_db_url = _db_url or os.environ.get("DATABASE_URL", "")
if not _db_url:
    st.error("⚠️ Falta configurar la conexión a la base de datos. "
             "Agregá DATABASE_URL en los Secrets de la app (ver README).")
    st.stop()
configure(_db_url)
try:
    init_db()
except Exception as _e:
    st.error("No pude conectar a la base de datos.\n\nDetalle técnico: " + str(_e)[:400])
    st.info("Si usás **Supabase**: la cadena tiene que ser la del **Session pooler** "
            "(host con `pooler.supabase.com`, puerto **5432**), no la conexión directa, "
            "y la contraseña debe ser la correcta.")
    st.stop()


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

        gastos = [{"Fecha": e["date"], "Descripción": e["description"],
                   "Monto": e["amount"], "Categoría": e["category"],
                   "Pagó": nombres[e["payer"]],
                   "Compartido": "Sí" if e["shared"] else "No"}
                  for e in data.get("expenses", [])]
        pd.DataFrame(gastos or [{"Fecha": "", "Descripción": "", "Monto": "",
                                 "Categoría": "", "Pagó": "", "Compartido": ""}]
                     ).to_excel(xl, sheet_name="Gastos", index=False)
    return buf.getvalue()


def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def build_ics(home: str) -> str:
    """Genera un calendario .ics con las tareas y comidas de la semana en curso,
    listo para importar en Google Calendar (u otro calendario)."""
    tasks = get_tasks(home)
    meals = get_meals(home)
    nombres = get_names(home)
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//Tablero del hogar//ES", "CALSCALE:GREGORIAN"]

    # Tareas: eventos de día completo en el día asignado de la semana actual.
    for t in tasks:
        quien = "Ambos" if t["assignee"] == -1 else nombres[t["assignee"]]
        for d in t["days"]:
            day = monday + datetime.timedelta(days=d)
            ymd = day.strftime("%Y%m%d")
            nxt = (day + datetime.timedelta(days=1)).strftime("%Y%m%d")
            lines += [
                "BEGIN:VEVENT",
                f"UID:task-{t['id']}-{d}-{home}@hogar",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{ymd}",
                f"DTEND;VALUE=DATE:{nxt}",
                f"SUMMARY:{_ics_escape('🧹 ' + t['name'] + ' (' + quien + ')')}",
                "END:VEVENT",
            ]

    # Comidas: eventos con horario.
    horarios = {"breakfast": ("0800", "0830", "Desayuno"),
                "lunch": ("1300", "1400", "Almuerzo"),
                "dinner": ("2100", "2200", "Cena")}
    for d in range(7):
        day = monday + datetime.timedelta(days=d)
        ymd = day.strftime("%Y%m%d")
        for slot, (h1, h2, lbl) in horarios.items():
            content = meals[d][slot]
            if content:
                lines += [
                    "BEGIN:VEVENT",
                    f"UID:meal-{d}-{slot}-{home}@hogar",
                    f"DTSTAMP:{stamp}",
                    f"DTSTART:{ymd}T{h1}00",
                    f"DTEND:{ymd}T{h2}00",
                    f"SUMMARY:{_ics_escape('🍽️ ' + lbl + ': ' + content)}",
                    "END:VEVENT",
                ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


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

tab_meals, tab_tasks, tab_exp, tab_shop, tab_supp = st.tabs(
    ["🍽️ Comidas", "🧹 Tareas", "💰 Gastos", "🛒 Compras", "📦 Insumos"]
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


# ================================================================ GASTOS
_MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def money(x: float) -> str:
    return f"${x:,.2f}"


def month_label(ym: str) -> str:
    try:
        y, m = ym.split("-")
        return f"{_MESES[int(m)].capitalize()} {y}"
    except Exception:
        return ym


with tab_exp:
    st.subheader("Cuentas y gastos")
    st.markdown('<p class="muted">Registrá quién pagó qué. Abajo ves el balance, '
                "los gráficos por categoría y la evolución mes a mes.</p>",
                unsafe_allow_html=True)

    with st.form("add_expense", clear_on_submit=True):
        e_desc = st.text_input("Descripción", placeholder="Súper, luz, farmacia…")
        c1, c2 = st.columns(2)
        e_amount = c1.number_input("Monto", min_value=0.0, step=100.0, format="%.2f")
        e_date = c2.date_input("Fecha", value=datetime.date.today())
        c3, c4 = st.columns(2)
        e_payer = c3.selectbox("¿Quién pagó?", options=[0, 1], format_func=lambda i: names[i])
        e_cat = c4.selectbox("Categoría", EXPENSE_CATS)
        e_shared = st.checkbox("Gasto compartido (se divide entre los dos)", value=True)
        if st.form_submit_button("Agregar gasto", type="primary", use_container_width=True):
            if e_desc.strip() and e_amount > 0:
                add_expense(home, e_desc.strip(), e_amount, e_payer, e_cat,
                               e_shared, e_date.isoformat())
                st.rerun()
            else:
                st.warning("Completá descripción y un monto mayor a 0.")

    expenses = get_expenses(home)
    if not expenses:
        st.info("Todavía no hay gastos cargados. Agregá el primero arriba.")
    else:
        df = pd.DataFrame(expenses)
        df["mes"] = df["date"].str.slice(0, 7)

        # --- filtro de mes ---
        meses = sorted(df["mes"].unique(), reverse=True)
        hoy_mes = datetime.date.today().strftime("%Y-%m")
        opciones = ["Todos"] + meses
        idx_def = opciones.index(hoy_mes) if hoy_mes in opciones else 0
        sel = st.selectbox("Período", opciones,
                           index=idx_def, format_func=lambda x: "Todos los meses" if x == "Todos" else month_label(x))
        view = df if sel == "Todos" else df[df["mes"] == sel]

        # --- métricas y balance ---
        total = view["amount"].sum()
        comp = view[view["shared"] == 1]
        paid_a = comp[comp["payer"] == 0]["amount"].sum()
        paid_b = comp[comp["payer"] == 1]["amount"].sum()
        share = (paid_a + paid_b) / 2
        diff = paid_a - share

        m1, m2 = st.columns(2)
        m1.metric(f"Total {'' if sel=='Todos' else month_label(sel).lower()}".strip(), money(total))
        if abs(diff) < 0.01:
            m2.metric("Balance", "Están a mano 👍")
        elif diff > 0:
            m2.metric("Balance", money(diff), delta=f"{names[1]} le debe a {names[0]}", delta_color="off")
        else:
            m2.metric("Balance", money(-diff), delta=f"{names[0]} le debe a {names[1]}", delta_color="off")

        st.caption(f"Compartido — {names[0]} puso {money(paid_a)} · {names[1]} puso {money(paid_b)}")

        # --- gráfico por categoría ---
        st.markdown("##### Gasto por categoría")
        by_cat = view.groupby("category")["amount"].sum().sort_values(ascending=False)
        st.bar_chart(by_cat, color="#4A6B52", horizontal=True)

        # --- evolución mensual (siempre sobre todo el historial) ---
        st.markdown("##### Evolución por mes")
        by_month = df.groupby("mes")["amount"].sum().sort_index()
        by_month.index = [month_label(m) for m in by_month.index]
        st.bar_chart(by_month, color="#C0744F")

        # --- lista de gastos del período ---
        st.markdown("##### Detalle")
        for e in view.to_dict("records"):
            col_info, col_amt, col_del = st.columns([6, 3, 1])
            etiqueta = "" if e["shared"] else " · personal"
            col_info.markdown(f"**{e['description']}**  \n"
                              f"<span class='muted'>{e['date']} · {e['category']} · pagó {names[e['payer']]}{etiqueta}</span>",
                              unsafe_allow_html=True)
            col_amt.markdown(f"**{money(e['amount'])}**")
            if col_del.button("🗑", key=f"delexp_{e['id']}", help="Eliminar gasto"):
                delete_expense(e["id"])
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
with st.expander("📅  Google Calendar — llevá tu semana al calendario"):
    st.markdown('<p class="muted">Descargá la semana en curso (tareas y comidas) como archivo '
                "<code>.ics</code> e importalo a Google Calendar. La sincronización automática "
                "vendrá más adelante.</p>", unsafe_allow_html=True)
    st.download_button(
        "⬇️ Descargar semana (.ics)",
        data=build_ics(home),
        file_name=f"semana-{home}.ics",
        mime="text/calendar",
        use_container_width=True,
    )
    st.markdown("**Cómo importarlo en Google Calendar:**")
    st.markdown(
        "1. Abrí Google Calendar en la computadora.\n"
        "2. Engranaje ⚙️ → **Configuración** → **Importar y exportar**.\n"
        "3. Seleccioná el archivo `.ics` que descargaste y elegí en qué calendario cargarlo.\n"
        "4. **Importar**. Las tareas y comidas de esta semana aparecen como eventos."
    )

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
