# 🏡 Tablero del hogar (multi-hogar)

App en Streamlit para organizar la rutina del hogar: comidas de la semana,
limpieza y tareas (con planificación semanal), lista de compras e inventario
de insumos. Cuando un insumo queda en *poco* o *agotado*, se manda a la lista
de compras con un clic.

## Cómo funciona el multi-hogar (sin login)

Cada grupo tiene su propio **hogar**, identificado por un código corto de 6
caracteres (ej. `ZEKZJ2`). Al abrir la app:

- **Crear un hogar nuevo** genera un código y entra a ese espacio.
- **Entrar con código** te lleva a un hogar existente.

El código viaja en la URL (`...?home=ZEKZJ2`), así que compartir el enlace del
navegador es suficiente para que otras personas entren al **mismo** hogar y
vean/editen los mismos datos. Los datos de cada hogar están aislados: un hogar
nunca ve los de otro.

> **Privacidad:** no hay contraseña. Cualquiera con el código (o el enlace)
> puede entrar a ese hogar, igual que un documento compartido por link. El
> código de 6 caracteres es difícil de adivinar, pero no lo publiques.

## Estructura

```
hogar-app/
├── app.py              # interfaz Streamlit + pantalla de ingreso por código
├── db.py               # capa de datos (SQLite), aislada por hogar
├── requirements.txt
├── .streamlit/config.toml
└── .gitignore
```

## Correr en tu computadora

```bash
cd hogar-app
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

La base `hogar.db` se crea sola. Para otra ubicación, usá `HOGAR_DB`:

```bash
HOGAR_DB=/data/hogar.db streamlit run app.py
```

## Deploy y el tema de los varios hogares a la vez

La separación por hogar ya está lista en el código y funciona con cualquier
motor. Lo que cambia según dónde lo deploees es **dónde viven los datos**:

### Streamlit Community Cloud (rápido, para probar)
Subí el repo a GitHub y conectalo en https://share.streamlit.io.
**Limitación:** el disco es efímero y de una sola instancia. La app corre y el
multi-hogar funciona, pero `hogar.db` se reinicia en cada redeploy y SQLite no
está pensado para mucha escritura concurrente. Sirve para que pocas personas
prueben; usá el respaldo `.json` para no perder datos.

### Host con disco persistente (Railway / Render / Fly.io)
Mismo código, montás un volumen y apuntás `HOGAR_DB` a una ruta dentro de él
(ej. `/data/hogar.db`). Los datos sobreviven a los reinicios. SQLite con WAL
aguanta bien varios hogares con pocas personas cada uno.

### Base gestionada (recomendado para varios hogares en serio)
Para muchos hogares y personas escribiendo a la vez, conviene **PostgreSQL**
(por ejemplo Supabase, gratis). Toda la persistencia está aislada en `db.py`,
así que sólo se reescribe ese archivo (mismas funciones, motor Postgres) y
`app.py` no cambia. Pedímelo y te paso esa versión.

## Notas

- La app relee la base en cada interacción: si dos personas del mismo hogar la
  usan a la vez, cada una ve los cambios de la otra al interactuar o refrescar
  (Streamlit no actualiza en tiempo real por sí solo).
- Cada hogar tiene su propio respaldo descargable (Excel y JSON) desde
  "Respaldo y descargas".
- Las tareas se agendan por día de la semana y "Empezar nueva semana" las
  desmarca sin borrarlas.
