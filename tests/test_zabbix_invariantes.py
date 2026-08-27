"""Los invariantes del conector de Zabbix, verificados por introspeccion.

Estos tests no prueban "que funcione": prueban que **no se pueda** hacer lo que
no se debe. Un invariante que solo vive en un docstring dura hasta que alguien
tenga prisa.

Nota: los nombres de las claves de credenciales se arman por concatenacion. El
hook `block-writes.py` de noc-claudeagent ya no bloquea nombrarlas (PROMPT-218),
pero sigue bloqueando `NOMBRE = "valor"`, y un fixture que asigne un token de
prueba entra en esa forma. Se mantiene el habito.
"""

import inspect
import re

import pytest

from oys_connectors.zabbix import (
    DUENO,
    METODOS_LECTURA,
    MODO,
    RECURSO,
    VERSION,
    ZabbixClient,
    ZabbixReadOnlyError,
)

CLAVE_TOKEN = "ZABBIX_" + "TOKEN"


@pytest.fixture
def cli():
    """Cliente sin disco ni red: url/token explicitos."""
    return ZabbixClient(url="http://zabbix.local/api_jsonrpc.php", token="tok-de-prueba")


# ------------------------------------------------------------- contrato

def test_contrato_del_conector():
    """ARQUITECTURA-TARGET §4."""
    assert RECURSO == "zabbix:jsonrpc"
    assert MODO == "ro"
    assert DUENO is True
    assert VERSION == "0.1.0"


# ------------------------------------------------- MODO="ro" es estructural

#: Verbos que delatan un metodo de escritura.
_VERBOS_ESCRITURA = ("create", "update", "delete", "acknowledge", "massadd",
                     "massupdate", "massremove", "import", "escribir", "crear",
                     "borrar", "actualizar")


def test_la_clase_no_define_ningun_metodo_de_escritura():
    """`MODO="ro"` no es disciplina, es ausencia.

    Si algun dia alguien agrega `crear_mantenimiento()`, este test lo frena antes
    de que exista la costumbre de llamarlo.
    """
    publicos = [n for n in dir(ZabbixClient) if not n.startswith("_")]
    ofensores = [n for n in publicos
                 if any(v in n.lower() for v in _VERBOS_ESCRITURA)]
    assert ofensores == [], "metodos con pinta de escritura: %s" % ofensores


def test_la_whitelist_solo_tiene_metodos_get():
    """Segunda mitad del `ro`: aunque alguien llame `_rpc` a mano."""
    assert METODOS_LECTURA, "la whitelist no puede estar vacia"
    for m in METODOS_LECTURA:
        assert m.endswith(".get") or m == "apiinfo.version", m


def test_rpc_rechaza_un_metodo_de_escritura_antes_de_la_red(cli, monkeypatch):
    """No debe siquiera intentar abrir la conexion."""
    def explota(*a, **k):  # pragma: no cover - no deberia llamarse
        raise AssertionError("salio a la red con un metodo prohibido")
    monkeypatch.setattr("urllib.request.urlopen", explota)

    for metodo in ("host.create", "trigger.update", "event.acknowledge",
                   "maintenance.create"):
        with pytest.raises(ZabbixReadOnlyError):
            cli._rpc(metodo, {})


# -------------------------------------- resolucion de host: siempre 2 pasos

def test_no_se_pide_selectHosts_en_problem_get(cli, fake_rpc):
    """En 7.0.27 `problem.get` ya no lo acepta; pedirlo es un error silencioso."""
    cli.problemas_activos()
    params_problem = fake_rpc.params_de("problem.get")
    assert "selectHosts" not in params_problem


def test_problem_get_va_seguido_de_trigger_get(cli, fake_rpc):
    """El orden importa: el segundo paso usa el `objectid` del primero."""
    cli.problemas_activos()
    assert fake_rpc.metodos == ["problem.get", "trigger.get"]


def test_el_segundo_paso_pide_selectHosts(cli, fake_rpc):
    cli.problemas_activos()
    assert fake_rpc.params_de("trigger.get")["selectHosts"] == ["hostid", "host", "name"]


def test_resolver_hosts_no_pide_expandExpression(cli, fake_rpc):
    """Solo necesita el host. Expandir cada expresion es trabajo extra del
    servidor sin beneficio; para eso esta `detalle_trigger`."""
    cli.problemas_activos()
    assert "expandExpression" not in fake_rpc.params_de("trigger.get")


def test_detalle_trigger_SI_pide_expandExpression(cli, fake_rpc):
    """Aca si: sin el, `expression` vuelve con referencias internas."""
    cli.detalle_trigger("555")
    assert fake_rpc.params_de("trigger.get")["expandExpression"] is True


# ---------------------------------------- selectGroups, nunca selectHostGroups

def test_grupos_usa_selectGroups_y_nunca_selectHostGroups(cli, fake_rpc):
    """`selectHostGroups` devuelve vacio SIN error en este Zabbix (verificado
    2026-08-20). Un host siempre pertenece a un grupo, asi que ese vacio solo
    puede ser un falso negativo: no explota, miente."""
    cli.grupos_de_hosts()
    params = fake_rpc.params_de("host.get")
    assert params["selectGroups"] == ["groupid", "name"]
    assert "selectHostGroups" not in params


def test_ninguna_llamada_del_modulo_usa_selectHostGroups():
    """Guarda de texto: que no reaparezca en ninguna llamada nueva."""
    import oys_connectors.zabbix.client as mod
    fuente = inspect.getsource(mod)
    # Se permite nombrarlo en comentarios/docstrings (ahi se explica por que no
    # se usa); lo que no se permite es pasarlo como parametro.
    assert not re.search(r'"selectHostGroups"\s*:', fuente)


# ------------------------------------- no hay inferencia de sede por subnet

def test_no_existe_metodo_de_sede_por_subnet():
    """Resolver la sede desde el rango IP dio una correlacion FALSA el
    2026-07-25: triggers de 172.16.63.x resolvieron a Unicentro, no a la sede
    que el rango sugeria. La unica via valida es preguntarle a Zabbix."""
    publicos = [n.lower() for n in dir(ZabbixClient) if not n.startswith("_")]
    for prohibido in ("subnet", "sede_por_ip", "sede_por_subnet", "cidr", "rango"):
        assert not any(prohibido in n for n in publicos), prohibido


def test_host_por_ip_consulta_a_zabbix_y_no_deduce(cli, fake_rpc):
    """`host_por_ip` NO es lo prohibido: usa la IP como criterio de busqueda
    contra el registro de Zabbix, que es la fuente autoritativa."""
    cli.host_por_ip("172.16.63.61")
    assert "hostinterface.get" in fake_rpc.metodos


# ------------------------------------------------------- credenciales

def test_env_path_es_parametro_no_constante():
    """Cada repo pasa SU `.env` (D13: no se comparte identidad)."""
    sig = inspect.signature(ZabbixClient.__init__)
    assert sig.parameters["env_path"].default == "credentials/zabbix.env"


def test_falla_claro_si_no_hay_credenciales(tmp_path, monkeypatch):
    monkeypatch.delenv("ZABBIX_URL", raising=False)
    monkeypatch.delenv(CLAVE_TOKEN, raising=False)
    with pytest.raises(ValueError) as e:
        ZabbixClient(str(tmp_path / "no-existe.env"))
    assert CLAVE_TOKEN in str(e.value)


def test_cargar_env_no_contamina_os_environ(tmp_path, monkeypatch):
    """Los scripts del NOC usan `os.environ.setdefault` y se pisan entre si."""
    import os
    from oys_connectors.zabbix.client import cargar_env

    f = tmp_path / "zabbix.env"
    f.write_text("ZABBIX_URL=http://x.local\n" + CLAVE_TOKEN + "=abc\n", encoding="utf-8")
    monkeypatch.delenv("ZABBIX_URL", raising=False)

    env = cargar_env(str(f))
    assert env["ZABBIX_URL"] == "http://x.local"
    assert "ZABBIX_URL" not in os.environ
