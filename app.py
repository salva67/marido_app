"""Tablero del hogar — app Streamlit multi-hogar.

Cada grupo tiene su propio "hogar" identificado por un código corto. No hay
login: quien tenga el código (o el enlace con ?home=CODIGO) entra a ese espacio.
Toda la persistencia vive en db.py.
"""

import datetime
import io
import json

import pandas as pd
import streamlit as st

import db

st.set_page_config(
    page_title="Tablero del hogar",
    page_icon="🏡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

db.init_db()


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
                "Día": db.DAYS[d],
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
                "Días": ", ".join(db.DAY_SHORT[x] for x in t["days"]),
                "Hechas esta semana": ", ".join(db.DAY_SHORT[x] for x in t["done_days"]) or "—",
            })
        pd.DataFrame(tareas or [{"Tarea": "", "Responsable": "", "Días": "", "Hechas esta semana": ""}]
                     ).to_excel(xl, sheet_name="Tareas", index=False)

        compras = [{"Producto": s["name"], "Categoría": s["cat"],
                    "Comprado": "Sí" if s["done"] else "No"} for s in data["shopping"]]
        pd.DataFrame(compras or [{"Producto": "", "Categoría": "", "Comprado": ""}]
                     ).to_excel(xl, sheet_name="Compras", index=False)

        insumos = [{"Insumo": s["name"], "Nivel": db.LEVELS.get(s["level"], s["level"])}
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
            code = db.create_home(nm)
            st.session_state["home"] = code
            st.query_params["home"] = code
            st.rerun()

    with tab_join:
        st.markdown('<p class="muted">Pedí el código a quien creó el hogar (6 caracteres).</p>',
                    unsafe_allow_html=True)
        code_in = st.text_input("Código del hogar", max_chars=6, placeholder="Ej: ZEKZJ2")
        if st.button("Entrar", type="primary", use_container_width=True):
            code = code_in.strip().upper()
            if db.home_exists(code):
                st.session_state["home"] = code
                st.query_params["home"] = code
                st.rerun()
            else:
                st.error("No existe un hogar con ese código. Revisalo o creá uno nuevo.")


def resolve_home() -> str | None:
    qp_home = st.query_params.get("home")
    if qp_home and db.home_exists(qp_home):
        st.session_state["home"] = qp_home
        return qp_home
    return st.session_state.get("home")


home = resolve_home()
if not home:
    render_gate()
    st.stop()

names = db.get_names(home)
home_name = db.get_home_name(home)

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
        db.set_home_name(home, new_home_name)
        db.set_config(home, "name_a", new_a.strip() or "Persona 1")
        db.set_config(home, "name_b", new_b.strip() or "Persona 2")
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

    meals = db.get_meals(home)
    df = pd.DataFrame(
        {label: [meals[d][slot] for d in range(len(db.DAYS))] for slot, label in db.MEAL_SLOTS},
        index=db.DAYS,
    )
    df.index.name = "Día"
    edited = st.data_editor(
        df, use_container_width=True, key="meals_editor",
        column_config={label: st.column_config.TextColumn(label, width="medium")
                       for _, label in db.MEAL_SLOTS},
    )
    changed = False
    for d in range(len(db.DAYS)):
        for slot, label in db.MEAL_SLOTS:
            new_val = str(edited.iloc[d][label] or "")
            if new_val != meals[d][slot]:
                db.set_meal(home, d, slot, new_val)
                changed = True
    if changed:
        st.toast("Comidas guardadas", icon="✅")

    st.caption(f"Hoy es {db.DAYS[today_index()].lower()}.")
    if st.button("Limpiar semana"):
        db.clear_meals(home)
        st.rerun()


# ================================================================ TAREAS
with tab_tasks:
    st.subheader("Limpieza y tareas")
    st.markdown('<p class="muted">Cada tarea se agenda a los días que quieras. '
                "Arriba ves lo de hoy; abajo, la semana completa.</p>", unsafe_allow_html=True)

    tasks = db.get_tasks(home)
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

        st.markdown(f"#### Hoy te toca ({db.DAYS[ti].lower()})")
        if not today_all:
            st.success("Nada agendado para hoy. 🎉")
        else:
            for t in today_all:
                done = ti in t["done_days"]
                lbl = f"~~{t['name']}~~ · {who_label(t['assignee'])}" if done else f"{t['name']} · {who_label(t['assignee'])}"
                if st.checkbox(lbl, value=done, key=f"today_{t['id']}") != done:
                    db.toggle_task_day(t["id"], ti)
                    st.rerun()

        st.markdown("#### Planificación semanal")
        for d in range(7):
            day_tasks = [t for t in tasks if d in t["days"]]
            st.markdown(f"**{'🟢 ' if d == ti else ''}{db.DAYS[d]}{' · hoy' if d == ti else ''}**")
            if not day_tasks:
                st.caption("Libre")
                continue
            for t in day_tasks:
                done = d in t["done_days"]
                lbl = f"~~{t['name']}~~ · {who_label(t['assignee'])}" if done else f"{t['name']} · {who_label(t['assignee'])}"
                col_chk, col_del = st.columns([10, 1])
                if col_chk.checkbox(lbl, value=done, key=f"week_{t['id']}_{d}") != done:
                    db.toggle_task_day(t["id"], d)
                    st.rerun()
                if d == min(t["days"]):
                    if col_del.button("🗑", key=f"deltask_{t['id']}", help="Eliminar tarea"):
                        db.delete_task(t["id"])
                        st.rerun()

        st.divider()
        if st.button("🔄 Empezar nueva semana", help="Desmarca todas las tareas sin borrarlas"):
            db.reset_week(home)
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
                                     format_func=lambda d: db.DAYS[d],
                                     help="Elegí uno o varios días, o marcá «Todos los días».",
                                     disabled=every_day)
            if st.form_submit_button("Agregar tarea", type="primary", use_container_width=True):
                chosen = list(range(7)) if every_day else day_sel
                if not t_name.strip():
                    st.warning("Escribí el nombre de la tarea.")
                elif not chosen:
                    st.warning("Elegí al menos un día (o marcá «Todos los días»).")
                else:
                    db.add_task(home, t_name.strip(), who, chosen)
                    st.rerun()


# ================================================================ COMPRAS
with tab_shop:
    st.subheader("Lista de compras")
    st.markdown('<p class="muted">Sumá lo que falte y marcá lo que ya pusiste en el carrito.</p>',
                unsafe_allow_html=True)

    with st.form("add_shop", clear_on_submit=True):
        c1, c2 = st.columns([4, 2])
        s_name = c1.text_input("Producto", placeholder="Leche…", label_visibility="collapsed")
        s_cat = c2.selectbox("Categoría", db.CATEGORIES, label_visibility="collapsed")
        if st.form_submit_button("Agregar producto", type="primary", use_container_width=True):
            if s_name.strip():
                db.add_shopping(home, s_name.strip(), s_cat)
                st.rerun()

    shopping = db.get_shopping(home)
    if not shopping:
        st.info("La lista está vacía.")
    else:
        for cat in db.CATEGORIES:
            items = [s for s in shopping if s["cat"] == cat]
            if not items:
                continue
            st.markdown(f"**{cat}**")
            for s in items:
                col_chk, col_del = st.columns([9, 1])
                label = f"~~{s['name']}~~" if s["done"] else s["name"]
                if col_chk.checkbox(label, value=bool(s["done"]), key=f"shop_{s['id']}") != bool(s["done"]):
                    db.toggle_shopping(s["id"])
                    st.rerun()
                if col_del.button("🗑", key=f"delshop_{s['id']}", help="Eliminar"):
                    db.delete_shopping(s["id"])
                    st.rerun()

        if any(s["done"] for s in shopping):
            if st.button("Quitar comprados"):
                db.clear_bought(home)
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
                db.add_supply(home, sup_name.strip())
                st.rerun()

    supplies = db.get_supplies(home)
    if not supplies:
        st.info("Sin insumos cargados todavía.")
    else:
        level_keys = list(db.LEVELS.keys())
        for s in supplies:
            col_name, col_lvl, col_del = st.columns([4, 4, 1])
            col_name.markdown(f"**{s['name']}**")
            current = level_keys.index(s["level"]) if s["level"] in level_keys else 0
            choice = col_lvl.radio("Nivel", options=level_keys, index=current,
                                   format_func=lambda k: db.LEVELS[k], horizontal=True,
                                   key=f"lvl_{s['id']}", label_visibility="collapsed")
            if choice != s["level"]:
                db.set_level(s["id"], choice)
                st.rerun()
            if col_del.button("🗑", key=f"delsup_{s['id']}", help="Eliminar"):
                db.delete_supply(s["id"])
                st.rerun()

            if s["level"] in ("low", "out"):
                if db.shopping_has(home, s["name"]):
                    col_name.caption("✓ Ya está en la lista de compras")
                else:
                    if col_name.button("+ Agregar a compras", key=f"toshop_{s['id']}"):
                        db.add_shopping(home, s["name"], "Alimentos")
                        st.toast(f"{s['name']} → lista de compras", icon="🛒")
                        st.rerun()


# ================================================================ RESPALDO
st.divider()
with st.expander("💾  Respaldo y descargas — guardá una copia de todo"):
    st.markdown('<p class="muted">En Streamlit Cloud los datos pueden borrarse cuando la app se '
                "reinicia. Descargá un respaldo cada tanto; si perdés los datos, lo volvés a cargar acá. "
                "El respaldo es sólo de este hogar.</p>", unsafe_allow_html=True)
    data = db.export_all(home)
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
                db.import_all(home, json.load(up))
                st.success("Datos restaurados.")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo leer el respaldo: {e}")

st.markdown('<p class="muted" style="text-align:center;margin-top:20px">'
            "Hecho para organizar el hogar. Los datos se guardan automáticamente.</p>",
            unsafe_allow_html=True)
