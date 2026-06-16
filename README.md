# 🏡 Tablero del hogar

App en Streamlit para organizar la rutina del hogar entre dos: comidas de la
semana, limpieza y tareas, lista de compras e inventario de insumos. Cuando un
insumo queda en *poco* o *agotado*, se manda a la lista de compras con un clic.

Los datos se guardan en una base SQLite (`hogar.db`), así que todo persiste
entre sesiones y ambos ven la misma información.

## Estructura

```
hogar-app/
├── app.py              # interfaz Streamlit (las 4 secciones)
├── db.py               # capa de datos (SQLite) — toda la persistencia vive acá
├── requirements.txt    # dependencias
├── .streamlit/
│   └── config.toml     # tema (verde salvia, fondo cálido)
└── .gitignore
```

## Correr en tu computadora

Necesitás Python 3.10 o superior.

```bash
cd hogar-app
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Se abre en `http://localhost:8501`. Lo primero que conviene hacer es desplegar
**"Editar nombres"** y poner los suyos: con eso las tareas quedan asignadas a
cada uno por nombre.

La base `hogar.db` se crea sola en la carpeta. Si la borrás, empezás de cero.
Para usar otra ubicación, definí la variable de entorno `HOGAR_DB`:

```bash
HOGAR_DB=/ruta/a/mi/hogar.db streamlit run app.py
```

## Deploy

### Opción A — Streamlit Community Cloud (gratis, la más rápida)

1. Subí esta carpeta a un repositorio de GitHub.
2. Entrá a https://share.streamlit.io, conectá tu cuenta de GitHub y elegí el
   repo. Apuntá a `app.py` y deployá.

> **Importante sobre los datos:** en el plan gratuito de Streamlit Community
> Cloud el disco es **efímero**. La app funciona, pero cada vez que el servicio
> se reinicia o redeployás, el archivo `hogar.db` vuelve a cero. Sirve para
> probarla; para uso diario sin perder datos, mirá la opción B o C.

### Opción B — Host con disco persistente (datos que no se borran)

Railway, Render o Fly.io permiten montar un volumen persistente. El comando de
arranque es el mismo:

```bash
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

Apuntá `HOGAR_DB` a una ruta dentro del volumen (por ejemplo `/data/hogar.db`)
para que la base sobreviva a los reinicios.

### Opción C — Base de datos en la nube (lo más robusto entre dos)

Si quieren acceder cada uno desde su dispositivo con datos siempre
sincronizados, conviene una base gestionada como **Supabase** (PostgreSQL
gratis). Toda la persistencia está aislada en `db.py`, así que sólo hay que
reescribir ese archivo para usar `psycopg`/SQLAlchemy contra Postgres; `app.py`
no cambia. Si querés, te paso esa versión de `db.py`.

## Notas

- La app relee la base en cada interacción, así que si los dos la usan al mismo
  tiempo, cada uno ve los cambios del otro al refrescar.
- Las tareas tienen un botón **"Desmarcar todas"** para arrancar una semana
  nueva sin borrarlas.
- "Quitar comprados" en la lista de compras elimina sólo lo ya tildado.
