# Login simple con email + PIN

Esta versión elimina el ingreso por código como método principal. Cada usuario entra con un email y un PIN/clave. La app guarda la relación `email -> hogar` en la misma base PostgreSQL/Supabase.

## Archivos

- `app_email_pin.py`: app Streamlit actualizada.
- `requirements_email_pin.txt`: dependencias.

## Qué tenés que configurar

En Streamlit Cloud, en **Settings → Secrets**, sólo necesitás mantener la conexión a la base:

```toml
DATABASE_URL = "postgresql://usuario:password@host:5432/postgres"
```

No necesitás Google Cloud, `client_id`, `client_secret`, `redirect_uri` ni `[auth]`.

## Cómo usarla

1. Subí `app_email_pin.py` como archivo principal de la app.
2. Usá `requirements_email_pin.txt` como `requirements.txt`.
3. Deploy.
4. Al abrir la app, entrá en **Crear cuenta**.
5. Cargá email, nombre del hogar y PIN.
6. La próxima vez entrás con **email + PIN**.

## Si ya tenías datos cargados con código

En la pantalla inicial usá la pestaña **Recuperar código viejo**:

1. Cargá tu email.
2. Elegí un PIN.
3. Pegá el código viejo del hogar.
4. La app vincula ese hogar a tu email.

Después ya no necesitás recordar el código.

## Agregar otra persona

Dentro de la app:

1. Abrí **Hogar, usuarios y nombres**.
2. En **Agregar otra persona**, cargá su email y un PIN inicial.
3. Esa persona entra con esos datos y ve el mismo hogar.

## Seguridad básica

El PIN no se guarda en texto plano. Se guarda como hash con salt usando `hashlib.pbkdf2_hmac`. Para una app familiar/simple es suficiente. Para una app pública o comercial convendría usar autenticación formal con Google, Supabase Auth u otro proveedor.
