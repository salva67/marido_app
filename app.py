"""Tablero del hogar — app Streamlit para gestionar la rutina en pareja.

Secciones: comidas de la semana, limpieza y tareas, lista de compras
e inventario de insumos. Toda la persistencia vive en db.py (SQLite).
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
    """Arma un .xlsx con una hoja por sección (Comidas, Tareas, Compras, Insumos)."""
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
      :root { --sage:#4A6B52; --sage-deep:#37503F; --clay:#C0744F; }
      .stApp { background:#FBFAF6; }
      .block-container { max-width: 780px; padding-top: 1.4rem; }
      /* encabezado */
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
      /* pestañas */
      .stTabs [data-baseweb="tab-list"] { gap:6px; }
      .stTabs [data-baseweb="tab"] {
        background:#fff; border:1px solid #E7E4DA; border-radius:12px;
        padding:8px 16px; font-weight:600;
      }
      .stTabs [aria-selected="true"] {
        background:#4A6B52 !important; color:#fff !important; border-color:#4A6B52;
      }
      /* botones primarios */
      .stButton button[kind="primary"] {
        background:#4A6B52; border:none;
      }
      .stButton button[kind="primary"]:hover { background:#37503F; }
      h2, h3 { font-family:Georgia,serif !important; font-weight:500 !important; }
      .muted { color:#83887E; font-size:13.5px; }
    </style>
    """,
    unsafe_allow_html=True,
)

names = db.get_names()

# ---------------------------------------------------------------- header
st.markdown(
    f"""
    <div class="home-head">
      <div class="eyebrow">Nuestro hogar</div>
      <h1>Tablero de la semana</h1>
      <div class="couple">
        <span class="dot" style="background:#A9C3AD"></span>{names[0]}
        &nbsp;·&nbsp;
        <span class="dot" style="background:#C0744F"></span>{names[1]}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("⚙️  Editar nombres"):
    col_a, col_b = st.columns(2)
    new_a = col_a.text_input("Persona 1", value=names[0], max_chars=24)
    new_b = col_b.text_input("Persona 2", value=names[1], max_chars=24)
    if st.button("Guardar nombres", type="primary"):
        db.set_config("name_a", new_a.strip() or "Persona 1")
        db.set_config("name_b", new_b.strip() or "Persona 2")
        st.rerun()

tab_meals, tab_tasks, tab_shop, tab_supp = st.tabs(
    ["🍽️ Comidas", "🧹 Tareas", "🛒 Compras", "📦 Insumos"]
)


# ================================================================ COMIDAS
def today_index() -> int:
    return datetime.date.today().weekday()  # lunes = 0


with tab_meals:
    st.subheader("Comidas de la semana")
    st.markdown(
        '<p class="muted">Editá cada casillero. Los cambios se guardan al confirmar la celda.</p>',
        unsafe_allow_html=True,
    )

    meals = db.get_meals()
    df = pd.DataFrame(
        {
            label: [meals[d][slot] for d in range(len(db.DAYS))]
            for slot, label in db.MEAL_SLOTS
        },
        index=db.DAYS,
    )
    df.index.name = "Día"

    edited = st.data_editor(
        df,
        use_container_width=True,
        disabled=False,
        key="meals_editor",
        column_config={
            label: st.column_config.TextColumn(label, width="medium")
            for _, label in db.MEAL_SLOTS
        },
    )

    # Guardar diferencias
    changed = False
    for d in range(len(db.DAYS)):
        for slot, label in db.MEAL_SLOTS:
            new_val = str(edited.iloc[d][label] or "")
            if new_val != meals[d][slot]:
                db.set_meal(d, slot, new_val)
                changed = True
    if changed:
        st.toast("Comidas guardadas", icon="✅")

    ti = today_index()
    st.caption(f"Hoy es {db.DAYS[ti].lower()}.")
    if st.button("Limpiar semana"):
        db.clear_meals()
        st.rerun()


# ================================================================ TAREAS
def who_label(assignee: int) -> str:
    return "Ambos" if assignee == -1 else names[assignee]


with tab_tasks:
    st.subheader("Limpieza y tareas")
    st.markdown(
        '<p class="muted">Cada tarea se agenda a los días de la semana que quieras. '
        "Arriba ves lo de hoy; abajo, la semana completa.</p>",
        unsafe_allow_html=True,
    )

    tasks = db.get_tasks()
    ti = today_index()

    if tasks:
        # ---- resumen del marido ocupado: hoy + progreso + reparto ----
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
        m3.metric("Reparto", f"{load_a} · {load_b}", help=f"{names[0]} · {names[1]} (tareas por semana)")

        # ---- HOY ----
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

        # ---- SEMANA COMPLETA ----
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
                # botón eliminar una sola vez por tarea, en su primer día agendado
                if d == min(t["days"]):
                    if col_del.button("🗑", key=f"deltask_{t['id']}", help="Eliminar tarea de toda la semana"):
                        db.delete_task(t["id"])
                        st.rerun()

        st.divider()
        if st.button("🔄 Empezar nueva semana", help="Desmarca todas las tareas sin borrarlas"):
            db.reset_week()
            st.rerun()
    else:
        st.info("Todavía no hay tareas. Agregá la primera abajo y elegí en qué días de la semana toca.")

    # ---- ALTA DE TAREA ----
    with st.expander("➕ Agregar tarea", expanded=not tasks):
        with st.form("add_task", clear_on_submit=True):
            t_name = st.text_input("Tarea", placeholder="Sacar la basura…")
            cA, cB = st.columns(2)
            who = cA.selectbox("¿Quién la hace?", options=[0, 1, -1], format_func=who_label)
            every_day = cB.checkbox("Todos los días")
            day_sel = st.multiselect(
                "¿Qué días?", options=list(range(7)), format_func=lambda d: db.DAYS[d],
                help="Elegí uno o varios días. Para algo diario, marcá «Todos los días».",
                disabled=every_day,
            )
            if st.form_submit_button("Agregar tarea", type="primary", use_container_width=True):
                chosen = list(range(7)) if every_day else day_sel
                if not t_name.strip():
                    st.warning("Escribí el nombre de la tarea.")
                elif not chosen:
                    st.warning("Elegí al menos un día (o marcá «Todos los días»).")
                else:
                    db.add_task(t_name.strip(), who, chosen)
                    st.rerun()


# ================================================================ COMPRAS
with tab_shop:
    st.subheader("Lista de compras")
    st.markdown(
        '<p class="muted">Sumá lo que falte y marcá lo que ya pusiste en el carrito.</p>',
        unsafe_allow_html=True,
    )

    with st.form("add_shop", clear_on_submit=True):
        c1, c2 = st.columns([4, 2])
        s_name = c1.text_input("Producto", placeholder="Leche…", label_visibility="collapsed")
        s_cat = c2.selectbox("Categoría", db.CATEGORIES, label_visibility="collapsed")
        if st.form_submit_button("Agregar producto", type="primary", use_container_width=True):
            if s_name.strip():
                db.add_shopping(s_name.strip(), s_cat)
                st.rerun()

    shopping = db.get_shopping()
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
                checked = col_chk.checkbox(label, value=bool(s["done"]), key=f"shop_{s['id']}")
                if checked != bool(s["done"]):
                    db.toggle_shopping(s["id"])
                    st.rerun()
                if col_del.button("🗑", key=f"delshop_{s['id']}", help="Eliminar"):
                    db.delete_shopping(s["id"])
                    st.rerun()

        if any(s["done"] for s in shopping):
            if st.button("Quitar comprados"):
                db.clear_bought()
                st.rerun()

        pendientes = [s for s in shopping if not s["done"]]
        if pendientes:
            txt = "LISTA DE COMPRAS\n\n" + "\n".join(
                f"[ ] {s['name']}  ({s['cat']})" for s in pendientes
            )
            st.download_button(
                "⬇️ Descargar lista para el super (.txt)",
                data=txt, file_name="lista-compras.txt", mime="text/plain",
            )


# ================================================================ INSUMOS
with tab_supp:
    st.subheader("Inventario de insumos")
    st.markdown(
        '<p class="muted">Marcá el nivel de cada cosa. Lo que esté en poco o agotado lo mandás a compras.</p>',
        unsafe_allow_html=True,
    )

    with st.form("add_supply", clear_on_submit=True):
        c1, c2 = st.columns([5, 2])
        sup_name = c1.text_input("Insumo", placeholder="Arroz, papel, detergente…", label_visibility="collapsed")
        if c2.form_submit_button("Agregar insumo", type="primary", use_container_width=True):
            if sup_name.strip():
                db.add_supply(sup_name.strip())
                st.rerun()

    supplies = db.get_supplies()
    if not supplies:
        st.info("Sin insumos cargados todavía.")
    else:
        level_keys = list(db.LEVELS.keys())
        for s in supplies:
            col_name, col_lvl, col_del = st.columns([4, 4, 1])
            col_name.markdown(f"**{s['name']}**")
            current = level_keys.index(s["level"]) if s["level"] in level_keys else 0
            choice = col_lvl.radio(
                "Nivel", options=level_keys, index=current,
                format_func=lambda k: db.LEVELS[k],
                horizontal=True, key=f"lvl_{s['id']}", label_visibility="collapsed",
            )
            if choice != s["level"]:
                db.set_level(s["id"], choice)
                st.rerun()
            if col_del.button("🗑", key=f"delsup_{s['id']}", help="Eliminar"):
                db.delete_supply(s["id"])
                st.rerun()

            if s["level"] in ("low", "out"):
                if db.shopping_has(s["name"]):
                    col_name.caption("✓ Ya está en la lista de compras")
                else:
                    if col_name.button(f"+ Agregar a compras", key=f"toshop_{s['id']}"):
                        db.add_shopping(s["name"], "Alimentos")
                        st.toast(f"{s['name']} → lista de compras", icon="🛒")
                        st.rerun()

st.divider()

with st.expander("💾  Respaldo y descargas — guardá una copia de todo"):
    st.markdown(
        '<p class="muted">En Streamlit Cloud los datos pueden borrarse cuando la app se '
        "reinicia. Descargá un respaldo cada tanto; si perdés los datos, lo volvés a cargar acá.</p>",
        unsafe_allow_html=True,
    )
    data = db.export_all()
    col1, col2 = st.columns(2)
    col1.download_button(
        "⬇️ Descargar todo (Excel)",
        data=build_excel(data),
        file_name="tablero-hogar.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    col2.download_button(
        "⬇️ Descargar respaldo (.json)",
        data=json.dumps(data, ensure_ascii=False, indent=2),
        file_name="respaldo-hogar.json",
        mime="application/json",
        use_container_width=True,
    )

    st.markdown("---")
    st.caption("¿Se reinició la app? Subí tu último respaldo `.json` para recuperar todo:")
    up = st.file_uploader("Restaurar respaldo", type="json", label_visibility="collapsed")
    if up is not None:
        st.warning("Restaurar reemplaza todos los datos actuales por los del archivo.")
        if st.button("Restaurar ahora", type="primary"):
            try:
                payload = json.load(up)
                db.import_all(payload)
                st.success("Datos restaurados.")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo leer el respaldo: {e}")

st.markdown(
    '<p class="muted" style="text-align:center;margin-top:20px">'
    "Hecho para organizar el hogar entre dos. Los datos se guardan automáticamente.</p>",
    unsafe_allow_html=True,
)
