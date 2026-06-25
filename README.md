# 🏡 Tablero del hogar — versión PostgreSQL (datos permanentes)

App Streamlit multi-hogar en un solo archivo (`app.py`), con los datos guardados
en **PostgreSQL (Supabase)**. Ya no se pierden en los redeploys.

## Qué cambió
- Antes los datos vivían en SQLite (disco efímero de Streamlit Cloud).
- Ahora viven en Postgres/Supabase: **permanentes**.
- La app NO arranca hasta que configures la conexión (`DATABASE_URL`).

## Paso 1 — Crear la base en Supabase (gratis)
1. Entrá a https://supabase.com y creá una cuenta.
2. **New project**: elegí un nombre, una **contraseña de base de datos** (guardala)
   y una región cercana. Esperá 1-2 minutos a que se cree.
3. En el proyecto: **Connect** (arriba) o **Settings → Database → Connection string**.
   Copiá la cadena en formato **URI**. Se ve así:
   `postgresql://postgres:[YOUR-PASSWORD]@db.xxxxxxxx.supabase.co:5432/postgres`
4. Reemplazá `[YOUR-PASSWORD]` por la contraseña que pusiste en el paso 2.

## Paso 2 — Cargar la conexión en Streamlit Cloud
1. En tu app: **Manage app → Settings → Secrets**.
2. Pegá esta línea (con tu cadena real) y guardá:
   ```
   DATABASE_URL = "postgresql://postgres:TU_PASSWORD@db.xxxxxxxx.supabase.co:5432/postgres"
   ```
3. La app se reinicia y **crea las tablas sola** en el primer arranque.

## Paso 3 — Subir el código
Subí `app.py` y `requirements.txt` (tiene la nueva dependencia `psycopg`).
Si tenés un `db.py` viejo en el repo, borralo.

## Correr local (opcional)
Creá `.streamlit/secrets.toml` con tu `DATABASE_URL` (ver `secrets.toml.example`)
o exportá la variable de entorno, y:
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notas
- `.gitignore` ya excluye `secrets.toml` para que **no subas tus credenciales**.
- Si Supabase te muestra varias opciones de conexión, empezá con la **directa**
  (puerto 5432). Si tu hosting limita conexiones, usá el **pooler** (puerto 6543).
- El login con Google y la sincronización con Google Calendar son los próximos
  pasos: se montan sobre esta base permanente.
