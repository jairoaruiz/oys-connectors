"""Conector de Odoo (XML-RPC).

Contrato del conector — ARQUITECTURA-TARGET §4:

    RECURSO   identidad del recurso fisico que este modulo representa
    MODO      "ro" | "rw"
    DUENO     True si este modulo es el unico autorizado a tocar su config
    VERSION   version del conector, independiente de la del paquete

`MODO = "rw"` NO significa que cualquiera pueda escribir: significa que el
conector **puede** hacerlo. La escritura real esta cerrada por la firma de
`crear_ticket`, que exige `permitir_real` keyword-only y sin default.
"""

RECURSO = "odoo:xmlrpc/2"
MODO = "rw"
DUENO = True
VERSION = "0.1.0"

from .client import OdooClient  # noqa: E402  (despues del contrato, a proposito)

__all__ = ["RECURSO", "MODO", "DUENO", "VERSION", "OdooClient"]
