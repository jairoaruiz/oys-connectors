# oys-connectors

Conectores compartidos del ecosistema **O&S / Ezytec**. Un conector por recurso
físico, cada uno declarando su contrato (`RECURSO`, `MODO`, `DUENO`, `VERSION`)
según `ARQUITECTURA-TARGET-ECOSISTEMA-2026-08-25.md` §4.

Hoy existe **solo `oys_connectors.odoo`**. Zabbix y WhatsApp vienen después.

> **Estado: aislado.** Este paquete todavía **no está cableado a nada**. No hay
> shim en `noc_scheduler`, ni units, ni deploy en DANTE. Ese cableado es un
> trabajo aparte y no se hizo aquí.

## Por qué existe

`noc_scheduler.py` concentra la conexión a Odoo y **6 sitios reales** la importan
(no 12 — ese conteo viejo sumaba archivos que solo mencionan el nombre en prosa).
Mover esa lógica a un paquete permite que `agentes-oys` y `noc-claudeagent`
compartan **código** sin compartir **identidad ni credenciales**, que es
exactamente la frontera que fija la decisión D13.

## Las dos capas, y por qué son dos

| Módulo | Para qué |
|---|---|
| `oys_connectors.odoo.compat` | Las 4 funciones de `noc_scheduler`, **copia fiel**. Existe para no romper 6 sitios que no se van a revisar. |
| `oys_connectors.odoo.client` | API nueva (`OdooClient`). Para todo lo que se escriba de ahora en adelante. |

`compat` no "mejora" nada a propósito: misma firma, mismos defaults
(`order="create_date asc"`, `limit=2000`), y `odoo_connect()` sigue devolviendo
la tupla `(obj, db, uid, pwd)`. Incluso conserva dos comportamientos que parecen
bugs —no quita comillas del valor, y revienta si el `.env` no existe— porque
**dos de los 6 consumidores importan dentro de un `try/except`** y dependen de
que reviente ahí.

## Invariantes impuestos, no sugeridos

No están en un docstring esperando que alguien lo lea: están en la forma de la
API.

- **`crear_ticket(valores, *, permitir_real)`** — keyword-only y **sin default**.
  Olvidarlo es un `TypeError` al escribir el código, no una escritura accidental
  en producción descubierta después. Con `False` devuelve el payload y no toca
  Odoo.
- **No existe `buscar_por_id`.** La identidad de un ticket es `ticket_ref`
  (`INC00000000`), nunca el `id` interno. Confundirlos ya costó un incidente
  real: el 2026-07-27 se correlacionó sobre `id=43068` cuando el ticket que
  importaba era `INC00043068` — son dos tickets distintos.
- **Los cierres razonan por `close_date`**, jamás `write_date`, que quedó
  contaminado por la migración BSAFE del 2026-07-02.
- **`env_path` es un parámetro**, no una constante: cada repo pasa el suyo.

## Desarrollo

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Linux: .venv/bin/python
./.venv/Scripts/python.exe -m pytest -q
```

Los tests **no tocan la red ni Odoo**: usan un doble del `ServerProxy` XML-RPC.
Sin dependencias de runtime — `xmlrpc.client` es stdlib, y agregar una obligaría
a instalarla en DANTE, que corre los timers del NOC.
