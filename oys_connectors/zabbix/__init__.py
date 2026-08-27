"""Conector de Zabbix (JSON-RPC, 7.0.27).

Contrato del conector — ARQUITECTURA-TARGET §4:

    RECURSO   identidad del recurso fisico que este modulo representa
    MODO      "ro" | "rw"
    DUENO     True si este modulo es el unico autorizado a tocar su config
    VERSION   version del conector, independiente de la del paquete

**`MODO = "ro"` no es una promesa, es una ausencia.** La clase no define ni un
solo metodo de escritura, y el transporte tiene una whitelist de metodos `.get`
que rechaza cualquier otro antes de salir a la red. No depende de que nadie se
acuerde de no llamar algo.
"""

RECURSO = "zabbix:jsonrpc"
MODO = "ro"
DUENO = True
VERSION = "0.1.0"

from .client import (  # noqa: E402
    METODOS_LECTURA,
    ZabbixClient,
    ZabbixError,
    ZabbixReadOnlyError,
)

# `METODOS_LECTURA` se exporta a proposito: es parte del contrato, no un detalle
# interno. Es la lista de lo que este conector PUEDE hacer, y quien lo audite
# tiene que poder leerla sin abrir client.py.
__all__ = [
    "RECURSO", "MODO", "DUENO", "VERSION", "METODOS_LECTURA",
    "ZabbixClient", "ZabbixError", "ZabbixReadOnlyError",
]
