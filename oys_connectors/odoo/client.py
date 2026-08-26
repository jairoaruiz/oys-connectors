"""`OdooClient` — API nueva del conector de Odoo.

Por que una clase, si `compat.py` ya cubre lo que existe: `odoo_connect()`
devuelve una tupla de 4 (`obj, db, uid, pwd`) que hay que arrastrar a cada
llamada. Eso es lo que hoy obliga a firmas de 6 y 9 parametros. La clase guarda
esa conexion una vez y deja las firmas en lo que el llamador realmente decide.

`compat.py` es para no romper lo que existe. **Esto es para lo que se escriba de
ahora en adelante.**

Los invariantes del NOC no son sugerencias en un docstring: estan impuestos en
la forma de la API — ver `buscar_por_ref` y `crear_ticket`.
"""

from . import compat


class OdooClient:
    """Cliente de Odoo por XML-RPC.

    Uso:

        cli = OdooClient("credentials/odoo.env")
        abiertos = cli.search_read(
            "helpdesk.ticket",
            [("stage_id", "not in", OdooClient.STAGE_CLOSED)],
            ["ticket_ref", "create_date"],
        )
    """

    #: Etapas terminales de `helpdesk.ticket`. Constante del conector.
    #:
    #: Incluye 50 ("CERRADO SOLUCIONADO BSAFE") y 52 ("CERRADO SOLUCIONADO
    #: MONITOREO CAMPO"), que son cierres de Brinks **sin flag terminal en
    #: Odoo**: no tienen `close_date`. Por eso un ticket puede estar cerrado y
    #: no contar en los cierres de un periodo.
    STAGE_CLOSED = [8, 10, 16, 17, 35, 45, 50, 51, 52, 66, 72]

    #: Formato de la identidad de un ticket: INC + 8 digitos con padding.
    TICKET_REF_ANCHO = 8
    TICKET_REF_PREFIJO = "INC"

    def __init__(self, env_path="credentials/odoo.env"):
        """Conecta usando las credenciales de `env_path`.

        `env_path` es un parametro y no una constante **a proposito**: cada repo
        consumidor pasa la ruta de SU propio `.env`. Este paquete no comparte
        credenciales entre repos (D13) y no trae ninguna ruta absoluta.
        """
        self.env_path = env_path
        self._env = compat.load_env(env_path)
        self._obj, self._db, self._uid, self._pwd = compat.odoo_connect(self._env)

    # ------------------------------------------------------------ lectura

    def search_read(self, model, domain, fields, order="create_date asc", limit=2000):
        """`search_read`. Mismos defaults que la funcion de compatibilidad."""
        return compat.odoo_search_read(
            self._obj, self._db, self._uid, self._pwd,
            model, domain, fields, order=order, limit=limit,
        )

    def search_count(self, model, domain):
        """`search_count`."""
        return compat.odoo_search_count(
            self._obj, self._db, self._uid, self._pwd, model, domain,
        )

    def read(self, model, ids, fields):
        """`read` por ids internos.

        Uso legitimo: releer registros cuyos ids ya devolvio una consulta. **No**
        es la via para buscar un ticket que un humano nombro — para eso esta
        `buscar_por_ref`.
        """
        return self._obj.execute_kw(
            self._db, self._uid, self._pwd, model, "read",
            [ids], {"fields": fields},
        )

    def fields_get(self, model, attributes=None):
        """`fields_get`. Introspeccion del modelo."""
        opciones = {}
        if attributes is not None:
            opciones["attributes"] = attributes
        return self._obj.execute_kw(
            self._db, self._uid, self._pwd, model, "fields_get", [], opciones,
        )

    # ------------------------------------------------- identidad de ticket

    @classmethod
    def to_ticket_ref(cls, numero):
        """Normaliza a `INC00000000` (8 digitos con padding).

        Acepta `43068`, `"43068"` o `"INC00043068"` y siempre devuelve la forma
        canonica.
        """
        s = str(numero).strip().upper()
        if s.startswith(cls.TICKET_REF_PREFIJO):
            s = s[len(cls.TICKET_REF_PREFIJO):]
        if not s.isdigit():
            raise ValueError("numero de ticket no numerico: %r" % (numero,))
        return cls.TICKET_REF_PREFIJO + s.zfill(cls.TICKET_REF_ANCHO)

    def buscar_por_ref(self, ref, fields=None):
        """Busca un ticket por `ticket_ref`. **La unica identidad valida.**

        No existe un `buscar_por_id` en esta API, y es deliberado: el `id` es la
        clave primaria interna de Odoo y **no es el numero del que habla el
        humano**. Confundirlos ya costo un incidente real — el 2026-07-27 se
        correlaciono El Tesoro sobre `id=43068` cuando el ticket que importaba
        era `ticket_ref=INC00043068`, que es San Nicolas. Son dos tickets
        distintos.

        Al reportar un ticket a una persona, imprimir siempre el `ticket_ref`,
        nunca solo el `id`.
        """
        if fields is None:
            fields = ["id", "ticket_ref", "name", "stage_id", "create_date", "close_date"]
        return self.search_read(
            "helpdesk.ticket",
            [("ticket_ref", "=", self.to_ticket_ref(ref))],
            fields,
            limit=1,
        )

    # ------------------------------------------------------------ cierres

    def cerrados_entre(self, desde_utc, hasta_utc, fields=None, team_id=1):
        """Tickets cerrados en una ventana, razonando por **`close_date`**.

        **Nunca `write_date`.** `write_date` cambia con cualquier escritura y
        quedo contaminado por la migracion BSAFE del 2026-07-02: usarlo para
        medir cierres devuelve numeros que parecen razonables y no lo son.

        Corolario que hay que tener presente: las etapas 50 y 52 cierran sin
        poblar `close_date`, asi que **no aparecen aca aunque esten cerradas**.
        Es correcto para "cuantos se cerraron en el turno" y es incorrecto para
        "cuantos estan cerrados"; para eso se filtra por `STAGE_CLOSED`.
        """
        if fields is None:
            fields = ["id", "ticket_ref", "stage_id", "close_date", "user_id"]
        return self.search_read(
            "helpdesk.ticket",
            [
                ("close_date", ">=", desde_utc),
                ("close_date", "<=", hasta_utc),
                ("stage_id", "in", self.STAGE_CLOSED),
                ("team_id", "=", team_id),
            ],
            fields,
        )

    # ---------------------------------------------------------- escritura

    def crear_ticket(self, valores: dict, *, permitir_real: bool) -> dict:
        """Crea un `helpdesk.ticket`. **Escritura real solo con gate explicito.**

        `permitir_real` es **keyword-only y sin default** a proposito. Olvidarlo
        es un `TypeError` al escribir el codigo, no una escritura accidental en
        produccion descubierta despues. Un default `False` seria mas comodo y
        justamente por eso no esta: haria invisible la decision.

        Con `permitir_real=False` devuelve el payload que *habria* enviado y no
        toca Odoo. Ese dict es lo que se le muestra al humano en el gate, y sale
        de esta misma funcion, asi que no puede divergir de lo que se escribe
        despues.

        Devuelve:
            `{"dry_run": True, "valores": {...}}` si no se permitio, o
            `{"dry_run": False, "id": <int>, "valores": {...}}` si se escribio.
        """
        if not isinstance(valores, dict):
            raise TypeError("valores debe ser dict, no %s" % type(valores).__name__)
        if not valores:
            raise ValueError("valores vacio: no hay nada que crear")

        if not permitir_real:
            return {"dry_run": True, "valores": valores}

        nuevo_id = self._obj.execute_kw(
            self._db, self._uid, self._pwd, "helpdesk.ticket", "create", [valores],
        )
        return {"dry_run": False, "id": nuevo_id, "valores": valores}
