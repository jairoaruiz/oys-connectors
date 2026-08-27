"""`ZabbixClient` — API del conector de Zabbix (JSON-RPC 7.0.27).

Read-only por construccion. Ver `__init__.py` para el contrato.

**Por que no hay `compat.py`.** El conector de Odoo tiene uno porque habia 6
sitios importando funciones de `noc_scheduler` que no se podian romper. Aca no
aplica: `mcp/zabbix_mcp.py` no es una libreria sino un **servidor FastMCP** —
instancia `FastMCP(...)` al importarse, decora sus funciones con `@mcp.tool()` y
lee las credenciales a nivel de modulo, asi que importarlo sin `.env` revienta
con `KeyError`. Envolverlo no es posible. Cuando toque cablear, sera el MCP el
que consuma este conector, no al reves.

Lo que este modulo va a absorber cuando llegue ese momento:

- `mcp/zabbix_mcp.py` — sus 5 herramientas.
- `tools/disaster_alert.py` — hace `problem.get` + `trigger.get` **a mano**, con
  su propio JSON-RPC inline. Es la duplicacion mas cara de las dos, porque corre
  en produccion cada hora.
- `tools/zabbix_host_by_ip.py` — ojo: `tools/audit_site_config.py` importa de el
  `_rpc` y `_sede`, o sea funciones privadas. Mover ese archivo sin mirar ese
  import lo rompe en silencio.
"""

import json
import os
import urllib.request


class ZabbixError(RuntimeError):
    """La API de Zabbix devolvio un error."""


class ZabbixReadOnlyError(ZabbixError):
    """Se intento un metodo JSON-RPC que no es de lectura."""


#: Whitelist de metodos JSON-RPC permitidos. **Solo `.get`.**
#:
#: Es la segunda mitad del `MODO="ro"`: la clase no define metodos de escritura,
#: y aunque alguien llamara `_rpc` a mano con `host.create`, no sale a la red.
#: Lista blanca y no negra a proposito: un metodo nuevo de Zabbix entra como
#: prohibido por defecto, que es el lado correcto en el que fallar.
METODOS_LECTURA = frozenset({
    "apiinfo.version",
    "event.get",
    "host.get",
    "hostgroup.get",
    "hostinterface.get",
    "item.get",
    "problem.get",
    "trigger.get",
})


def cargar_env(path):
    """Lee un `.env` a dict. **NO toca `os.environ`.**

    Los scripts del NOC usan `os.environ.setdefault(...)`, que contamina el
    entorno del proceso entero: dos clientes con `.env` distintos se pisan, y el
    primero que corre gana. Aca el contenido se queda en el objeto.
    """
    env = {}
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, _, v = linea.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class ZabbixClient:
    """Cliente read-only de Zabbix.

        cli = ZabbixClient("credentials/zabbix.env")
        for p in cli.problemas_activos():
            print(p["name"], [h["name"] for h in p["hosts"]])
    """

    #: Campos que se piden de un problema. `objectid` es el triggerid y **no es
    #: opcional**: sin el no se puede resolver el host en el segundo paso.
    CAMPOS_PROBLEMA = ["eventid", "objectid", "name", "severity", "clock", "acknowledged"]

    #: Nombres de las claves en el `.env`. Aca solo se nombran; los valores
    #: viven en `credentials/zabbix.env` del repo consumidor.
    CLAVE_URL = "ZABBIX_URL"
    CLAVE_TOKEN = "ZABBIX_TOKEN"

    def __init__(self, env_path="credentials/zabbix.env", *, url=None, token=None):
        """El entorno gana sobre el `.env`, igual que en el MCP actual.

        `url`/`token` explicitos existen para los tests: permiten construir el
        cliente sin tocar el disco ni el entorno.

        `env_path` es parametro y no constante: cada repo consumidor pasa el
        suyo. Este paquete no comparte credenciales entre repos (D13).
        """
        env = {}
        if url is None or token is None:
            try:
                env = cargar_env(env_path)
            except OSError:
                env = {}
        self.url = url or os.environ.get(self.CLAVE_URL) or env.get(self.CLAVE_URL)
        self._token = token or os.environ.get(self.CLAVE_TOKEN) or env.get(self.CLAVE_TOKEN)
        if not self.url or not self._token:
            raise ValueError(
                "faltan %s / %s: no estan ni en el entorno ni en %s"
                % (self.CLAVE_URL, self.CLAVE_TOKEN, env_path))
        self.timeout = 30

    # ------------------------------------------------------------ transporte

    def _rpc(self, metodo, params=None):
        """Una llamada JSON-RPC. Bearer en el header, nunca en el campo `auth`.

        Zabbix 7.0 dejo de aceptar el token en `params.auth`; va como
        `Authorization: Bearer <token>`.
        """
        if metodo not in METODOS_LECTURA:
            raise ZabbixReadOnlyError(
                "metodo no permitido (este conector es read-only): %s" % metodo)

        cuerpo = json.dumps({
            "jsonrpc": "2.0", "method": metodo, "params": params or {}, "id": 1,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=cuerpo, method="POST",
            headers={
                "Content-Type": "application/json-rpc",
                "Authorization": "Bearer " + self._token,
            })
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            datos = json.loads(r.read().decode("utf-8"))
        if "error" in datos:
            raise ZabbixError("%s -> %s" % (metodo, datos["error"]))
        return datos["result"]

    # ------------------------------------------------- resolucion de host

    def _resolver_hosts(self, registros):
        """**Paso 2, obligatorio en 7.0.27.** Agrega `hosts` a cada registro.

        `problem.get` YA NO acepta `selectHosts`, asi que el host se resuelve por
        `trigger.get` usando el `objectid` (=triggerid) de cada registro. Sirve
        igual para `problem.get` y para `event.get` de triggers.

        Esta encapsulado a proposito: **el llamador nunca arma los dos pasos a
        mano**. Hoy esa logica esta duplicada en el MCP y en `disaster_alert.py`,
        y una copia que se olvide del segundo paso devuelve alarmas sin host —
        que para quien lee el reporte es indistinguible de "no hay alarmas".

        NO se pide `expandExpression` aca: esta llamada solo necesita el host, y
        expandir la expresion de cada trigger es trabajo extra del servidor sin
        beneficio. Para leer la expresion esta `detalle_trigger()`.
        """
        if not registros:
            return registros

        trigger_ids = sorted({r["objectid"] for r in registros if r.get("objectid")})
        if not trigger_ids:
            for r in registros:
                r.setdefault("hosts", [])
            return registros

        triggers = self._rpc("trigger.get", {
            "triggerids": trigger_ids,
            "output": ["triggerid", "description"],
            "selectHosts": ["hostid", "host", "name"],
        })
        por_trigger = {t["triggerid"]: t.get("hosts", []) for t in triggers}
        for r in registros:
            r["hosts"] = por_trigger.get(r.get("objectid"), [])
        return registros

    # ------------------------------------------------------------ lectura

    def listar_hosts(self, limit=500):
        """Hosts con `hostid`, `host` y `name`.

        Para identificar una sede se usa **`name`** (canonico), nunca `host`, que
        es inconsistente: camelCase, abreviaturas y aliases arbitrarios.
        """
        return self._rpc("host.get", {
            "output": ["hostid", "host", "name", "status"],
            "limit": limit,
        })

    def problemas_activos(self, limit=500):
        """Problemas activos, ya con su host resuelto."""
        problemas = self._rpc("problem.get", {
            "output": self.CAMPOS_PROBLEMA,
            "recent": False,
            "sortfield": ["eventid"],
            "sortorder": "DESC",
            "limit": limit,
        })
        return self._resolver_hosts(problemas)

    def problemas_por_host(self, nombre_contiene, limit=500):
        """Problemas activos de los hosts cuyo nombre CONTIENE el texto dado.

        Pensado para acotar por sede (`"PRIMAVERA_URBANA"`). El filtro es sobre
        el host **resuelto por Zabbix**, nunca sobre la IP ni la subnet del
        evento: un mismo rango privado se reusa entre sedes, y adjudicar por IP
        ya produjo una correlacion falsa el 2026-07-25 — triggers de
        `172.16.63.x` resolvieron a Unicentro, no a la sede que el rango sugeria.
        """
        aguja = nombre_contiene.strip().lower()
        salida = []
        for p in self.problemas_activos(limit=limit):
            for h in p.get("hosts", []):
                if aguja in (h.get("host", "") + " " + h.get("name", "")).lower():
                    salida.append(p)
                    break
        return salida

    def eventos(self, time_from, time_till, limit=1000, severidades=None):
        """Eventos historicos de triggers, con su host resuelto.

        Para correlacionar incidentes YA CERRADOS: `problem.get` solo trae lo que
        sigue activo.
        """
        params = {
            "output": ["eventid", "objectid", "name", "severity", "clock", "value"],
            "source": 0,          # 0 = evento generado por un trigger
            "object": 0,          # 0 = trigger
            "time_from": int(time_from),
            "time_till": int(time_till),
            "sortfield": ["clock"],
            "sortorder": "DESC",
            "limit": limit,
        }
        if severidades:
            params["severities"] = list(severidades)
        return self._resolver_hosts(self._rpc("event.get", params))

    def eventos_por_host(self, nombre_contiene, time_from, time_till, limit=1000):
        """Eventos historicos acotados por nombre de host.

        Mismo criterio que `problemas_por_host`: se filtra por host resuelto,
        jamas por IP.
        """
        aguja = nombre_contiene.strip().lower()
        salida = []
        for e in self.eventos(time_from, time_till, limit=limit):
            for h in e.get("hosts", []):
                if aguja in (h.get("host", "") + " " + h.get("name", "")).lower():
                    salida.append(e)
                    break
        return salida

    def detalle_trigger(self, triggerid):
        """Un trigger con su expresion EXPANDIDA y sus items.

        `expandExpression=True` va aca y no en `_resolver_hosts`: sin el, la
        `expression` vuelve con referencias internas en vez de nombres, que es
        inservible para diagnosticar por que un trigger no cierra.
        """
        return self._rpc("trigger.get", {
            "triggerids": [triggerid],
            "output": "extend",
            "selectHosts": ["hostid", "host", "name"],
            "selectItems": ["itemid", "key_", "name", "status", "state", "error"],
            "expandExpression": True,
        })

    def grupos_de_hosts(self, hostids=None):
        """Grupos de host, pedidos con **`selectGroups`**.

        NUNCA `selectHostGroups`. No es preferencia de estilo: en este Zabbix,
        `host.get` con `selectHostGroups` devuelve la lista **vacia y sin error**
        — y como en Zabbix todo host pertenece al menos a un grupo, un vacio ahi
        es imposible y solo puede ser un falso negativo. Verificado el 2026-08-20
        comparando los dos parametros contra la misma consulta.

        Ese es el peor modo de fallo posible: no explota, miente.
        """
        params = {
            "output": ["hostid", "host", "name"],
            "selectGroups": ["groupid", "name"],
        }
        if hostids:
            params["hostids"] = list(hostids)
        return self._rpc("host.get", params)

    # --------------------------------------------- IP -> host (autoritativo)

    def host_por_ip(self, ip):
        """Resuelve una IP a host(es) **preguntandole a Zabbix**, no deduciendo.

        Esto NO es inferir la sede por subnet — es exactamente lo contrario, y es
        la unica forma valida de responder "a que sede pertenece esta IP".

        Dos estrategias, en orden:
          1. `hostinterface`: la IP es interfaz propia de un host. Raro aca — el
             agente vive en el servidor de parking de cada sede.
          2. `item_key`: la IP aparece en el key de un item (el ping local que
             hace ese agente). Como un agente cubre UNA sede, resolver a un solo
             host es autoritativo.

        Devuelve `ambiguo=True` con 0 o con >1 hosts. **Con `ambiguo` no se
        adjudica sede**: 0 significa que Zabbix no conoce esa IP, y >1 que la IP
        privada se reusa entre sedes. Los dos casos son gate humano.
        """
        interfaces = self._rpc("hostinterface.get", {
            "output": ["interfaceid", "hostid", "ip", "port", "type", "main"],
            "filter": {"ip": ip},
        })
        if interfaces:
            hostids = sorted({i["hostid"] for i in interfaces})
            hosts = self._rpc("host.get", {
                "output": ["hostid", "host", "name", "status"],
                "hostids": hostids,
            })
            return self._empaquetar_ip(ip, "hostinterface", hosts, interfaces)

        items = self._rpc("item.get", {
            "output": ["itemid", "hostid", "name", "key_"],
            "search": {"key_": ip},
            "searchByAny": True,
        })
        hostids = sorted({i["hostid"] for i in items})
        hosts = self._rpc("host.get", {
            "output": ["hostid", "host", "name"],
            "hostids": hostids,
        }) if hostids else []
        return self._empaquetar_ip(ip, "item_key", hosts, items)

    @staticmethod
    def _empaquetar_ip(ip, metodo, hosts, evidencia):
        ambiguo = len({h["hostid"] for h in hosts}) != 1
        return {
            "ip": ip,
            "method": metodo,
            "ambiguo": ambiguo,
            "hosts": hosts,
            "evidencia": evidencia,
        }
