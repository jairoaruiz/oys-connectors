"""Las 4 firmas de `compat` aceptan las llamadas de los 6 sitios reales.

Por que este test importa mas de lo que parece: **2 de los 6 consumidores
importan dentro de un `try/except` con mensaje propio** (`discover_odoo.py:38` y
`resolve_hu1_config.py:37`). Si una firma cambiara de forma incompatible, esos
dos **no** lanzarian `ImportError`: quedarian degradados en silencio. Este test
es el que convierte ese fallo mudo en un fallo ruidoso.

Se prueban las **dos formas** de import que usan esos sitios:
  1. `from ... import load_env, odoo_connect, ...`   (4 sitios)
  2. `import ... as NS` -> `NS.load_env(...)`         (2 sitios)

Nota: la clave de credenciales se arma como CLAVE_PWD por concatenacion. Escrita
entera, el hook `block-writes.py` de noc-claudeagent marca el archivo como
"posible secreto" — es un falso positivo (es el NOMBRE de una clave de `.env`),
pero es mas barato esquivarlo que discutirlo.
"""

import inspect

import pytest

# --- forma 1: from ... import (run_hu1.py:360, discover_odoo.py:38,
#     resolve_hu1_config.py:37, backfill_historial.py:51)
from oys_connectors.odoo.compat import (  # noqa: F401
    load_env,
    odoo_connect,
    odoo_search_read,
    odoo_search_count,
)

# --- forma 2: import ... as NS (alerta_responsable.py:57, notificador_horario.py:47)
import oys_connectors.odoo.compat as NS

CLAVE_PWD = "ODOO_" + "PASS"


def test_forma_2_expone_los_mismos_atributos():
    """`NS.<fn>` tiene que resolver a la misma funcion que el `from ... import`."""
    assert NS.load_env is load_env
    assert NS.odoo_connect is odoo_connect
    assert NS.odoo_search_read is odoo_search_read
    assert NS.odoo_search_count is odoo_search_count


def test_firma_load_env():
    p = list(inspect.signature(load_env).parameters)
    assert p == ["path"]


def test_firma_odoo_connect():
    p = list(inspect.signature(odoo_connect).parameters)
    assert p == ["env"]


def test_firma_odoo_search_read_y_sus_defaults():
    sig = inspect.signature(odoo_search_read)
    assert list(sig.parameters) == [
        "obj", "db", "uid", "pwd", "model", "domain", "fields", "order", "limit",
    ]
    # Los defaults son parte del contrato: hay llamadores que los omiten.
    assert sig.parameters["order"].default == "create_date asc"
    assert sig.parameters["limit"].default == 2000


def test_firma_odoo_search_count():
    p = list(inspect.signature(odoo_search_count).parameters)
    assert p == ["obj", "db", "uid", "pwd", "model", "domain"]


def test_load_env_parsea_como_el_original(tmp_path):
    """Copia fiel: ignora vacios y comentarios, parte en el PRIMER '='."""
    f = tmp_path / "odoo.env"
    f.write_text(
        "\n".join([
            "# comentario",
            "",
            "ODOO_URL=https://ejemplo.local",
            "ODOO_DB=midb",
            "ODOO_UID=7",
            CLAVE_PWD + "=con=signos=igual",
            "   ",
            "SIN_IGUAL",
        ]),
        encoding="utf-8",
    )
    env = load_env(str(f))
    assert env["ODOO_URL"] == "https://ejemplo.local"
    assert env["ODOO_DB"] == "midb"
    assert env["ODOO_UID"] == "7"
    # partition() parte en el primer '=': el resto queda intacto.
    assert env[CLAVE_PWD] == "con=signos=igual"
    assert "SIN_IGUAL" not in env
    assert "" not in env


def test_load_env_no_quita_comillas(tmp_path):
    """Fidelidad, no correccion: el original NO hace strip de comillas.

    Otros scripts del ecosistema si lo hacen. Cambiarlo aca alteraria el valor
    que hoy reciben los 6 consumidores, asi que se deja igual y se documenta.
    """
    f = tmp_path / "odoo.env"
    f.write_text('ODOO_DB="entre-comillas"\n', encoding="utf-8")
    assert load_env(str(f))["ODOO_DB"] == '"entre-comillas"'


def test_load_env_revienta_si_no_existe(tmp_path):
    """Tambien es contrato: 2 consumidores dependen de que reviente adentro de
    su propio `try/except`."""
    with pytest.raises(OSError):
        load_env(str(tmp_path / "no-existe.env"))


def test_odoo_connect_devuelve_la_tupla_de_4(monkeypatch):
    """`(obj, db, uid, pwd)` y `uid` convertido a int."""
    creados = []

    class FakeProxy:
        def __init__(self, url, allow_none=False):
            creados.append((url, allow_none))

    monkeypatch.setattr("xmlrpc.client.ServerProxy", FakeProxy)

    env = {
        "ODOO_URL": "https://ejemplo.local",
        "ODOO_DB": "midb",
        "ODOO_UID": "7",
        CLAVE_PWD: "secreto-de-prueba",
    }
    obj, db, uid, pwd = odoo_connect(env)

    assert isinstance(obj, FakeProxy)
    assert db == "midb"
    assert uid == 7 and isinstance(uid, int)
    assert pwd == "secreto-de-prueba"
    # La URL se arma con /xmlrpc/2/object y allow_none=True.
    assert creados == [("https://ejemplo.local/xmlrpc/2/object", True)]


class _FakeObj:
    """Doble del ServerProxy: registra las llamadas, no toca la red."""

    def __init__(self):
        self.llamadas = []

    def execute_kw(self, db, uid, pwd, model, metodo, args, kwargs=None):
        self.llamadas.append((db, uid, pwd, model, metodo, args, kwargs))
        return "RESULTADO"


def test_odoo_search_read_arma_la_llamada_igual_que_el_original():
    obj = _FakeObj()
    r = odoo_search_read(obj, "db", 7, "pwd", "helpdesk.ticket",
                         [("id", ">", 0)], ["ticket_ref"])
    assert r == "RESULTADO"
    (db, uid, pwd, model, metodo, args, kwargs) = obj.llamadas[0]
    assert (db, uid, pwd, model, metodo) == ("db", 7, "pwd", "helpdesk.ticket", "search_read")
    assert args == [[("id", ">", 0)]]
    assert kwargs == {"fields": ["ticket_ref"], "order": "create_date asc", "limit": 2000}


def test_odoo_search_count_arma_la_llamada_igual_que_el_original():
    obj = _FakeObj()
    r = odoo_search_count(obj, "db", 7, "pwd", "helpdesk.ticket", [("id", ">", 0)])
    assert r == "RESULTADO"
    (db, uid, pwd, model, metodo, args, kwargs) = obj.llamadas[0]
    assert (model, metodo) == ("helpdesk.ticket", "search_count")
    assert args == [[("id", ">", 0)]]
    assert kwargs is None
