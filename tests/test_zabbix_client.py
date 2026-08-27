"""`ZabbixClient` contra el doble del transporte. Sin red, sin Zabbix vivo.

Lo que mas importa aca es que la resolucion de host en dos pasos funcione de
verdad: que el `objectid` del problema se use para pedir el trigger, y que el
host que vuelve termine pegado al problema correcto. Un test que solo cuente
llamadas dejaria pasar un mapeo cruzado.
"""

import pytest

from oys_connectors.zabbix import ZabbixClient, ZabbixError

from conftest import FakeRPC


@pytest.fixture
def cli():
    return ZabbixClient(url="http://zabbix.local/api_jsonrpc.php", token="tok-de-prueba")


# ------------------------------------------------------------ transporte

def test_el_token_viaja_como_bearer_en_el_header(cli, fake_rpc):
    """Zabbix 7.0 dejo de aceptar el token en `params.auth`."""
    cli.listar_hosts()
    headers = fake_rpc.headers_vistos[0]
    # urllib capitaliza los nombres de header
    auth = headers.get("Authorization") or headers.get("authorization")
    assert auth == "Bearer tok-de-prueba"
    assert "auth" not in fake_rpc.cuerpos[0].get("params", {})


def test_el_cuerpo_es_jsonrpc_20(cli, fake_rpc):
    cli.listar_hosts()
    c = fake_rpc.cuerpos[0]
    assert c["jsonrpc"] == "2.0"
    assert c["method"] == "host.get"


def test_un_error_de_la_api_se_convierte_en_excepcion(cli, fake_rpc):
    fake_rpc.responder("host.get", {"error": {"code": -32602, "message": "Invalid params"}})
    with pytest.raises(ZabbixError) as e:
        cli.listar_hosts()
    assert "host.get" in str(e.value)


# ------------------------------------- resolucion de host en dos pasos

def test_el_host_resuelto_queda_pegado_al_problema(cli, fake_rpc):
    problemas = cli.problemas_activos()
    assert len(problemas) == 1
    assert problemas[0]["hosts"] == [FakeRPC.HOST]


def test_el_trigger_se_pide_con_el_objectid_del_problema(cli, fake_rpc):
    """El vinculo entre los dos pasos. Si se rompe, el host sale vacio o cruzado."""
    cli.problemas_activos()
    assert fake_rpc.params_de("trigger.get")["triggerids"] == [FakeRPC.TRIGGER_ID]


def test_cada_problema_recibe_SU_host_y_no_el_del_vecino(cli, fake_rpc):
    """Dos problemas de triggers distintos no deben cruzarse."""
    fake_rpc.responder("problem.get", [
        {"eventid": "1", "objectid": "100", "name": "A", "severity": "5", "clock": "1"},
        {"eventid": "2", "objectid": "200", "name": "B", "severity": "4", "clock": "2"},
    ])
    fake_rpc.responder("trigger.get", [
        {"triggerid": "100", "hosts": [{"hostid": "1", "host": "SEDE_A", "name": "SEDE_A"}]},
        {"triggerid": "200", "hosts": [{"hostid": "2", "host": "SEDE_B", "name": "SEDE_B"}]},
    ])
    por_evento = {p["eventid"]: p["hosts"][0]["name"] for p in cli.problemas_activos()}
    assert por_evento == {"1": "SEDE_A", "2": "SEDE_B"}


def test_un_problema_sin_trigger_correspondiente_queda_con_hosts_vacio(cli, fake_rpc):
    """No debe reventar ni heredar el host de otro."""
    fake_rpc.responder("problem.get", [
        {"eventid": "9", "objectid": "999", "name": "huerfano", "severity": "3", "clock": "1"},
    ])
    fake_rpc.responder("trigger.get", [])
    assert cli.problemas_activos()[0]["hosts"] == []


def test_sin_problemas_no_se_llama_a_trigger_get(cli, fake_rpc):
    """Ahorra una llamada; y `trigger.get` sin ids traeria TODOS los triggers."""
    fake_rpc.responder("problem.get", [])
    assert cli.problemas_activos() == []
    assert fake_rpc.metodos == ["problem.get"]


# --------------------------------------------------- filtro por sede

def test_problemas_por_host_filtra_por_nombre_resuelto(cli, fake_rpc):
    assert len(cli.problemas_por_host("PRIMAVERA_URBANA")) == 1
    assert cli.problemas_por_host("UNICENTRO") == []


def test_el_filtro_por_host_es_case_insensitive(cli, fake_rpc):
    assert len(cli.problemas_por_host("primavera_urbana")) == 1


# ------------------------------------------------------------ eventos

def test_eventos_resuelve_host_igual_que_problemas(cli, fake_rpc):
    ev = cli.eventos(1755000000, 1756000000)
    assert ev[0]["hosts"] == [FakeRPC.HOST]
    assert fake_rpc.metodos == ["event.get", "trigger.get"]


def test_eventos_acota_la_ventana_temporal(cli, fake_rpc):
    cli.eventos(1755000000, 1756000000)
    p = fake_rpc.params_de("event.get")
    assert p["time_from"] == 1755000000 and p["time_till"] == 1756000000
    assert p["source"] == 0 and p["object"] == 0


def test_eventos_por_host_filtra(cli, fake_rpc):
    assert len(cli.eventos_por_host("PRIMAVERA", 1, 2)) == 1
    assert cli.eventos_por_host("NO_EXISTE", 1, 2) == []


# ------------------------------------------------------- IP -> host

def test_host_por_ip_por_hostinterface_es_autoritativo(cli, fake_rpc):
    fake_rpc.responder("hostinterface.get", [
        {"interfaceid": "1", "hostid": "10", "ip": "10.0.0.5", "type": "1", "main": "1"},
    ])
    r = cli.host_por_ip("10.0.0.5")
    assert r["method"] == "hostinterface"
    assert r["ambiguo"] is False
    assert "item.get" not in fake_rpc.metodos  # no hace falta el segundo camino


def test_host_por_ip_cae_a_item_key_si_no_hay_interfaz(cli, fake_rpc):
    """El caso normal aca: el agente vive en el server de parking de la sede."""
    fake_rpc.responder("hostinterface.get", [])
    fake_rpc.responder("item.get", [
        {"itemid": "7", "hostid": "10", "name": "ping", "key_": "remoto.ping.status[172.16.63.61]"},
    ])
    r = cli.host_por_ip("172.16.63.61")
    assert r["method"] == "item_key"
    assert r["ambiguo"] is False


def test_ip_que_resuelve_a_dos_hosts_queda_AMBIGUA(cli, fake_rpc):
    """Reuso de IP privada entre sedes. NO se adjudica: es gate humano."""
    fake_rpc.responder("hostinterface.get", [])
    fake_rpc.responder("item.get", [
        {"itemid": "1", "hostid": "10", "key_": "ping[172.16.63.61]"},
        {"itemid": "2", "hostid": "20", "key_": "ping[172.16.63.61]"},
    ])
    fake_rpc.responder("host.get", [
        {"hostid": "10", "host": "SEDE_A", "name": "SEDE_A"},
        {"hostid": "20", "host": "SEDE_B", "name": "SEDE_B"},
    ])
    r = cli.host_por_ip("172.16.63.61")
    assert r["ambiguo"] is True
    assert len(r["hosts"]) == 2


def test_ip_desconocida_tambien_es_AMBIGUA(cli, fake_rpc):
    """0 hosts no es "sin sede": es "Zabbix no la conoce". Tampoco se adjudica."""
    fake_rpc.responder("hostinterface.get", [])
    fake_rpc.responder("item.get", [])
    r = cli.host_por_ip("192.0.2.1")
    assert r["ambiguo"] is True
    assert r["hosts"] == []


# ------------------------------------------------------------- grupos

def test_grupos_de_hosts_acepta_filtrar_por_hostids(cli, fake_rpc):
    cli.grupos_de_hosts(hostids=["10", "20"])
    assert fake_rpc.params_de("host.get")["hostids"] == ["10", "20"]


# ------------------------ solo_problemas: PROBLEM vs evento de resolucion

#: Mezcla deliberada: 2 eventos PROBLEM (`value="1"`) y 3 de resolucion
#: (`value="0"`). La proporcion imita lo medido en produccion el 2026-08-27 —de
#: 400 eventos, 198 problemas y 202 resoluciones—, o sea que NO filtrar mas que
#: duplica el resultado. Todos con el mismo `objectid` para que resuelvan al
#: mismo host y el filtro por sede pueda distinguirse del filtro por `value`.
_MEZCLA = [
    {"eventid": "1", "objectid": FakeRPC.TRIGGER_ID, "name": "caida A",
     "severity": "4", "clock": "1756000001", "value": "1"},
    {"eventid": "2", "objectid": FakeRPC.TRIGGER_ID, "name": "recuperado A",
     "severity": "4", "clock": "1756000002", "value": "0"},
    {"eventid": "3", "objectid": FakeRPC.TRIGGER_ID, "name": "caida B",
     "severity": "5", "clock": "1756000003", "value": "1"},
    {"eventid": "4", "objectid": FakeRPC.TRIGGER_ID, "name": "recuperado B",
     "severity": "5", "clock": "1756000004", "value": "0"},
    {"eventid": "5", "objectid": FakeRPC.TRIGGER_ID, "name": "recuperado C",
     "severity": "3", "clock": "1756000005", "value": "0"},
]

#: Igual, pero las resoluciones cuelgan de OTRO trigger. Sirve para ver si el
#: filtro corre antes o despues de resolver hosts: si corre antes, el
#: `trigger.get` nunca ve el id 999.
_MEZCLA_IDS = [
    {"eventid": "1", "objectid": FakeRPC.TRIGGER_ID, "name": "caida A",
     "severity": "4", "clock": "1756000001", "value": "1"},
    {"eventid": "2", "objectid": "999", "name": "recuperado A",
     "severity": "4", "clock": "1756000002", "value": "0"},
]


def test_eventos_sin_solo_problemas_devuelve_todo(cli, fake_rpc):
    """Default `False`: no altera lo que este metodo ya devolvia."""
    fake_rpc.responder("event.get", _MEZCLA)
    ev = cli.eventos(1, 2)
    assert len(ev) == 5
    assert sorted({e["value"] for e in ev}) == ["0", "1"]


def test_eventos_con_solo_problemas_descarta_las_resoluciones(cli, fake_rpc):
    fake_rpc.responder("event.get", _MEZCLA)
    ev = cli.eventos(1, 2, solo_problemas=True)
    assert [e["eventid"] for e in ev] == ["1", "3"]
    assert all(e["value"] == "1" for e in ev)


def test_solo_problemas_arranca_en_False(cli):
    """Explicito, no por descuido: subirlo a `True` cambiaria el resultado de
    cualquier consumidor que hoy llama sin el parametro."""
    import inspect
    p = inspect.signature(ZabbixClient.eventos).parameters["solo_problemas"]
    assert p.default is False


def test_el_filtro_de_value_corre_ANTES_de_resolver_hosts(cli, fake_rpc):
    """Resolver un evento que se va a descartar es un `trigger.get` de mas.

    Con `solo_problemas=True` el trigger de la resolucion (999) no debe llegar
    nunca al segundo paso.
    """
    fake_rpc.responder("event.get", _MEZCLA_IDS)
    cli.eventos(1, 2, solo_problemas=True)
    assert fake_rpc.params_de("trigger.get")["triggerids"] == [FakeRPC.TRIGGER_ID]

    fake_rpc.llamadas.clear()
    cli.eventos(1, 2, solo_problemas=False)
    # sorted() sobre strings: "555" antes que "999".
    assert fake_rpc.params_de("trigger.get")["triggerids"] == [FakeRPC.TRIGGER_ID, "999"]


def test_eventos_por_host_hereda_solo_problemas(cli, fake_rpc):
    """Mismo criterio que `eventos()`, sobre los eventos ya filtrados por sede."""
    fake_rpc.responder("event.get", _MEZCLA)
    assert len(cli.eventos_por_host("PRIMAVERA", 1, 2)) == 5
    assert len(cli.eventos_por_host("PRIMAVERA", 1, 2, solo_problemas=True)) == 2


def test_eventos_por_host_pide_2000_por_defecto(cli, fake_rpc):
    """El filtro por host ocurre DESPUES de traer los datos, asi que un limite
    corto puede dejar una sede en cero por recorte y no por ausencia."""
    cli.eventos_por_host("PRIMAVERA", 1, 2)
    assert fake_rpc.params_de("event.get")["limit"] == 2000


def test_problemas_por_host_sigue_en_500(cli, fake_rpc):
    """La asimetria con `eventos_por_host` es deliberada: los eventos historicos
    de una ventana son muchos mas que los problemas activos de un instante."""
    cli.problemas_por_host("PRIMAVERA")
    assert fake_rpc.params_de("problem.get")["limit"] == 500
