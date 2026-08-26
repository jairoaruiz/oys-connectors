"""Capa de compatibilidad: las 4 funciones de `noc_scheduler`, tal cual.

**Este modulo existe para NO romper 6 sitios que no se van a revisar.** Por eso
reproduce el comportamiento actual byte a byte: misma firma, mismos defaults,
`odoo_connect` devuelve la tupla `(obj, db, uid, pwd)`. No se "mejora" nada aca
— cualquier mejora va en `client.OdooClient`, que es API nueva.

Consumidores reales (6 sitios, 2 formas) — DISENO-CONECTORES §0:

| Archivo | Linea | Forma |
|---|---:|---|
| `agents/email_agent/run_hu1.py` | 360 | `from noc_scheduler import load_env, odoo_connect` |
| `agents/email_agent/tools/discover_odoo.py` | 38 | idem, **dentro de `try/except`** |
| `agents/email_agent/tools/resolve_hu1_config.py` | 37 | idem, **dentro de `try/except`** |
| `tools/alerta_responsable.py` | 57 | `import noc_scheduler as NS` -> `NS.load_env` |
| `tools/backfill_historial.py` | 51 | `from noc_scheduler import` (las 4) |
| `tools/notificador_horario.py` | 47 | `import noc_scheduler as NS` |

Son 6, no 12: el conteo viejo sumaba archivos que solo mencionan el nombre en
prosa. **Dos de los 6 estan envueltos en `try/except` con mensaje propio**, asi
que una firma incompatible no daria `ImportError`: quedarian degradados en
silencio. De ahi que las firmas se validen con un test dedicado.

Nada de este modulo se cablea todavia: no hay shim en `noc_scheduler`, y no lo
habra hasta que se decida en su propio prompt.
"""

import xmlrpc.client

__all__ = ["load_env", "odoo_connect", "odoo_search_read", "odoo_search_count"]


def load_env(path):
    """Lee un `.env` a dict. Copia fiel de `noc_scheduler.load_env`.

    Ojo con dos detalles que parecen bugs y NO se corrigen aca:
    - **No quita comillas** del valor. Otros scripts del ecosistema si lo hacen
      (`zabbix_cronicos_semanal.py`), pero cambiarlo aca alteraria el valor que
      hoy reciben los 6 consumidores.
    - **No captura excepciones.** Si el archivo no existe, revienta. Eso es lo
      que hace hoy, y dos consumidores dependen de que reviente dentro de su
      propio `try/except`.
    """
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def odoo_connect(env):
    """Devuelve la tupla `(obj, db, uid, pwd)`. Copia fiel.

    La tupla de 4 es incomoda de propagar, y por eso existe `OdooClient`. Pero
    aca se conserva: los 6 consumidores la desempaquetan asi.

    `env` debe traer `ODOO_URL`, `ODOO_DB`, `ODOO_UID` y `ODOO_PASS`. Los valores
    viven en `credentials/odoo.env` del repo consumidor y **nunca** en este
    paquete: aca solo se nombra la clave.
    """
    url = env["ODOO_URL"]
    db = env["ODOO_DB"]
    uid = int(env["ODOO_UID"])
    pwd = env["ODOO_PASS"]
    obj = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)
    return obj, db, uid, pwd


def odoo_search_read(obj, db, uid, pwd, model, domain, fields,
                     order="create_date asc", limit=2000):
    """`search_read`. Copia fiel, incluidos los defaults.

    `order="create_date asc"` y `limit=2000` NO son arbitrarios: hay llamadores
    que los omiten y dependen de ellos. Cambiar el limite cambia en silencio lo
    que ven los reportes de turno.
    """
    return obj.execute_kw(db, uid, pwd, model, "search_read",
                          [domain], {"fields": fields, "order": order, "limit": limit})


def odoo_search_count(obj, db, uid, pwd, model, domain):
    """`search_count`. Copia fiel."""
    return obj.execute_kw(db, uid, pwd, model, "search_count", [domain])
