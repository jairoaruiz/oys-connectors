"""`OdooClient` contra un doble del XML-RPC. Sin red, sin Odoo vivo.

El test que mas importa es el del gate de escritura: `crear_ticket` con
`permitir_real=False` **no debe llamar a `execute_kw`**. No alcanza con que
devuelva un dict con `dry_run`: si igual escribiera, el dict seria una mentira
prolija.
"""

import pytest

from oys_connectors.odoo import DUENO, MODO, RECURSO, VERSION, OdooClient

CLAVE_PWD = "ODOO_" + "PASS"


class FakeObj:
    """Doble del ServerProxy. Registra llamadas y devuelve lo que se le diga."""

    def __init__(self, respuesta=None):
        self.llamadas = []
        self.respuesta = respuesta if respuesta is not None else []

    def execute_kw(self, db, uid, pwd, model, metodo, args, kwargs=None):
        self.llamadas.append({
            "model": model, "metodo": metodo, "args": args, "kwargs": kwargs,
        })
        if callable(self.respuesta):
            return self.respuesta(model, metodo, args, kwargs)
        return self.respuesta

    @property
    def metodos(self):
        return [c["metodo"] for c in self.llamadas]


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """Un `OdooClient` conectado a un `FakeObj`, sin tocar la red."""
    env = tmp_path / "odoo.env"
    env.write_text(
        "ODOO_URL=https://ejemplo.local\n"
        "ODOO_DB=midb\n"
        "ODOO_UID=7\n"
        + CLAVE_PWD + "=secreto-de-prueba\n",
        encoding="utf-8",
    )
    fake = FakeObj()
    monkeypatch.setattr("xmlrpc.client.ServerProxy",
                        lambda url, allow_none=False: fake)
    c = OdooClient(str(env))
    c._fake = fake
    return c


# ------------------------------------------------------------- contrato

def test_contrato_del_conector():
    """ARQUITECTURA-TARGET §4: el modulo declara su contrato."""
    assert RECURSO == "odoo:xmlrpc/2"
    assert MODO == "rw"
    assert DUENO is True
    assert VERSION == "0.1.0"


def test_stage_closed_es_la_lista_del_noc():
    assert OdooClient.STAGE_CLOSED == [8, 10, 16, 17, 35, 45, 50, 51, 52, 66, 72]


# ------------------------------------------------------- identidad ticket

@pytest.mark.parametrize("entrada,esperado", [
    (43068, "INC00043068"),
    ("43068", "INC00043068"),
    ("INC00043068", "INC00043068"),
    ("inc00043068", "INC00043068"),
    (1, "INC00000001"),
])
def test_to_ticket_ref_normaliza(entrada, esperado):
    assert OdooClient.to_ticket_ref(entrada) == esperado


def test_to_ticket_ref_rechaza_basura():
    with pytest.raises(ValueError):
        OdooClient.to_ticket_ref("no-es-un-numero")


def test_buscar_por_ref_consulta_por_ticket_ref_no_por_id(cli):
    """El dominio tiene que filtrar por `ticket_ref`. Nunca por `id`.

    Es el invariante que costo el incidente del 2026-07-27: `id=43068` y
    `ticket_ref=INC00043068` son tickets distintos.
    """
    cli.buscar_por_ref(43068)
    llamada = cli._fake.llamadas[0]
    assert llamada["metodo"] == "search_read"
    dominio = llamada["args"][0]
    assert dominio == [("ticket_ref", "=", "INC00043068")]
    assert all(c[0] != "id" for c in dominio)


def test_no_existe_busqueda_por_id_crudo():
    """La API no expone un `buscar_por_id`: es deliberado, no un olvido."""
    assert not hasattr(OdooClient, "buscar_por_id")


# ----------------------------------------------------------- cierres

def test_cerrados_entre_usa_close_date_y_nunca_write_date(cli):
    """`write_date` quedo contaminado por la migracion BSAFE del 2026-07-02."""
    cli.cerrados_entre("2026-08-25 12:00:00", "2026-08-25 19:00:00")
    dominio = cli._fake.llamadas[0]["args"][0]
    campos = [c[0] for c in dominio]
    assert "close_date" in campos
    assert "write_date" not in campos
    assert ("stage_id", "in", OdooClient.STAGE_CLOSED) in dominio


# ------------------------------------------------- GATE DE ESCRITURA

def test_crear_ticket_exige_permitir_real_explicito(cli):
    """Sin el keyword es `TypeError`, no una escritura silenciosa."""
    with pytest.raises(TypeError):
        cli.crear_ticket({"name": "prueba"})


def test_crear_ticket_dry_run_no_llama_execute_kw(cli):
    """El test central: con False NO se escribe. Nada de `create`."""
    r = cli.crear_ticket({"name": "prueba", "team_id": 1}, permitir_real=False)

    assert r["dry_run"] is True
    assert r["valores"] == {"name": "prueba", "team_id": 1}
    assert "id" not in r
    # Lo que de verdad importa: cero llamadas al XML-RPC.
    assert cli._fake.llamadas == []


def test_crear_ticket_real_si_llama_execute_kw(cli):
    cli._fake.respuesta = 12345
    r = cli.crear_ticket({"name": "prueba", "team_id": 1}, permitir_real=True)

    assert r["dry_run"] is False
    assert r["id"] == 12345
    assert cli._fake.metodos == ["create"]
    llamada = cli._fake.llamadas[0]
    assert llamada["model"] == "helpdesk.ticket"
    assert llamada["args"] == [{"name": "prueba", "team_id": 1}]


def test_crear_ticket_valida_la_entrada(cli):
    with pytest.raises(TypeError):
        cli.crear_ticket("no soy un dict", permitir_real=False)
    with pytest.raises(ValueError):
        cli.crear_ticket({}, permitir_real=False)
    assert cli._fake.llamadas == []


# ------------------------------------------------------------- lectura

def test_search_read_pasa_los_defaults(cli):
    cli.search_read("helpdesk.ticket", [("id", ">", 0)], ["ticket_ref"])
    kwargs = cli._fake.llamadas[0]["kwargs"]
    assert kwargs == {"fields": ["ticket_ref"], "order": "create_date asc", "limit": 2000}


def test_search_count(cli):
    cli._fake.respuesta = 42
    assert cli.search_count("helpdesk.ticket", [("id", ">", 0)]) == 42
    assert cli._fake.metodos == ["search_count"]


def test_read_y_fields_get(cli):
    cli.read("helpdesk.ticket", [1, 2], ["ticket_ref"])
    assert cli._fake.llamadas[-1]["metodo"] == "read"

    cli.fields_get("helpdesk.ticket", attributes=["type"])
    ultima = cli._fake.llamadas[-1]
    assert ultima["metodo"] == "fields_get"
    assert ultima["kwargs"] == {"attributes": ["type"]}


def test_env_path_es_parametro_no_constante(tmp_path, monkeypatch):
    """Cada repo pasa SU `.env` (D13: no se comparten credenciales)."""
    import inspect
    sig = inspect.signature(OdooClient.__init__)
    assert sig.parameters["env_path"].default == "credentials/odoo.env"
