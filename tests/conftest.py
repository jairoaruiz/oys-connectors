"""Doble del transporte JSON-RPC de Zabbix. Sin red.

Se intercepta `urllib.request.urlopen` y no el metodo `_rpc`, a proposito: asi
los tests tambien cubren el transporte real — que el token viaje como
`Authorization: Bearer`, que el cuerpo sea JSON-RPC 2.0 y que un `error` en la
respuesta se convierta en excepcion. Parchear `_rpc` dejaria todo eso sin probar.
"""

import io
import json

import pytest


class _Respuesta:
    """Lo minimo que `urlopen` devuelve y que el cliente usa."""

    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeRPC:
    """Registra las llamadas y responde segun el metodo.

    Por defecto devuelve datos coherentes con la resolucion de host en dos
    pasos: un problema cuyo `objectid` casa con el trigger que se devuelve
    despues. Si no fueran coherentes, los tests pasarian igual y no probarian
    nada — es justo el bug que el conector viene a evitar.
    """

    TRIGGER_ID = "555"
    HOST = {"hostid": "10", "host": "PARKING_CC_PRIMAVERA_URBANA_MED",
            "name": "PARKING_CC_PRIMAVERA_URBANA_MED"}

    def __init__(self):
        self.llamadas = []          # [(metodo, params)]
        self.respuestas = {}        # metodo -> valor o callable
        self.headers_vistos = []
        self.cuerpos = []

    # -- configuracion -------------------------------------------------
    def responder(self, metodo, valor):
        self.respuestas[metodo] = valor

    # -- inspeccion ----------------------------------------------------
    @property
    def metodos(self):
        return [m for m, _ in self.llamadas]

    def params_de(self, metodo):
        """Params de la ULTIMA llamada a ese metodo."""
        for m, p in reversed(self.llamadas):
            if m == metodo:
                return p
        raise AssertionError("no se llamo a %s; se llamo a %s" % (metodo, self.metodos))

    # -- transporte ----------------------------------------------------
    def _por_defecto(self, metodo, params):
        if metodo == "problem.get":
            return [{
                "eventid": "7745020", "objectid": self.TRIGGER_ID,
                "name": "WatchDog caido", "severity": "5",
                "clock": "1756000000", "acknowledged": "0",
            }]
        if metodo == "event.get":
            return [{
                "eventid": "7745021", "objectid": self.TRIGGER_ID,
                "name": "URL publica caida", "severity": "4",
                "clock": "1755900000", "value": "1",
            }]
        if metodo == "trigger.get":
            return [{"triggerid": self.TRIGGER_ID, "description": "WatchDog",
                     "hosts": [self.HOST]}]
        if metodo == "host.get":
            return [self.HOST]
        if metodo == "hostinterface.get":
            return []
        if metodo == "item.get":
            return []
        return []

    def urlopen(self, req, timeout=None):
        cuerpo = json.loads(req.data.decode("utf-8"))
        metodo = cuerpo["method"]
        params = cuerpo.get("params") or {}
        self.llamadas.append((metodo, params))
        self.cuerpos.append(cuerpo)
        try:
            self.headers_vistos.append(dict(req.headers))
        except Exception:
            self.headers_vistos.append({})

        if metodo in self.respuestas:
            valor = self.respuestas[metodo]
            if callable(valor):
                valor = valor(params)
        else:
            valor = self._por_defecto(metodo, params)

        if isinstance(valor, dict) and "error" in valor:
            return _Respuesta({"jsonrpc": "2.0", "id": 1, "error": valor["error"]})
        return _Respuesta({"jsonrpc": "2.0", "id": 1, "result": valor})


@pytest.fixture
def fake_rpc(monkeypatch):
    f = FakeRPC()
    monkeypatch.setattr("urllib.request.urlopen", f.urlopen)
    return f
