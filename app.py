"""Tablero del hogar — app Streamlit para gestionar la rutina en pareja.

Secciones: comidas de la semana, limpieza y tareas, lista de compras
e inventario de insumos. Toda la persistencia vive en db.py (SQLite).
"""

import datetime

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
with tab_tasks:
    st.subheader("Limpieza y tareas")
    st.markdown(
        '<p class="muted">Asigná cada tarea a uno de los dos y marcala al terminar.</p>',
        unsafe_allow_html=True,
    )

    with st.form("add_task", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 2, 2])
        t_name = c1.text_input("Tarea", placeholder="Lavar los platos…", label_visibility="collapsed")
        who = c2.selectbox(
            "Asignar a", options=[0, 1, -1],
            format_func=lambda i: "Ambos" if i == -1 else names[i],
            label_visibility="collapsed",
        )
        freq = c3.selectbox(
            "Frecuencia", ["Diaria", "Semanal", "Mensual"], index=1,
            label_visibility="collapsed",
        )
        if st.form_submit_button("Agregar tarea", type="primary", use_container_width=True):
            if t_name.strip():
                db.add_task(t_name.strip(), who, freq)
                st.rerun()

    tasks = db.get_tasks()
    if not tasks:
        st.info("Todavía no hay tareas. Agregá la primera arriba.")
    else:
        for t in tasks:
            col_chk, col_meta, col_del = st.columns([6, 3, 1])
            label = f"~~{t['name']}~~" if t["done"] else t["name"]
            checked = col_chk.checkbox(label, value=bool(t["done"]), key=f"task_{t['id']}")
            if checked != bool(t["done"]):
                db.toggle_task(t["id"])
                st.rerun()
            who_lbl = "Ambos" if t["assignee"] == -1 else names[t["assignee"]]
            col_meta.caption(f"{who_lbl} · {t['freq']}")
            if col_del.button("🗑", key=f"deltask_{t['id']}", help="Eliminar"):
                db.delete_task(t["id"])
                st.rerun()

        if st.button("Desmarcar todas (nueva semana)"):
            db.reset_tasks()
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

st.markdown(
    '<p class="muted" style="text-align:center;margin-top:28px">'
    "Hecho para organizar el hogar entre dos. Los datos se guardan automáticamente.</p>",
    unsafe_allow_html=True,
)
