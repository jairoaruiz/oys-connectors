"""oys_connectors — conectores compartidos del ecosistema O&S / Ezytec.

Un conector por recurso fisico. Cada submodulo declara su contrato
(`RECURSO`, `MODO`, `DUENO`, `VERSION`) segun ARQUITECTURA-TARGET §4.

Hoy solo existe `oys_connectors.odoo`. Zabbix y WhatsApp vienen despues.

**Este paquete no comparte identidad ni credenciales entre repos** (D13): cada
consumidor le pasa la ruta de SU propio `.env`. Un conector que leyera un `.env`
comun volveria a fusionar justo lo que esa decision separa.
"""

__version__ = "0.2.1"
