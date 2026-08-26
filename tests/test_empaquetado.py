"""La version del paquete vive en TRES lugares y no pueden divergir.

`pyproject.toml` (PEP 621), `setup.cfg` (formato clasico) y
`oys_connectors.__version__`. La duplicacion es deliberada: DANTE corre pip
22.0.2, que no lee bien la metadata PEP 621 y construye el wheel como
`UNKNOWN-0.0.0` — instala algo con nombre desconocido y sin dejar el modulo
importable, o sea que **falla en silencio**. `setup.cfg` es lo que evita eso.

El precio de tener dos formatos es que pueden desincronizarse. Este test es lo
que hace que ese error sea ruidoso en vez de aparecer como "la version instalada
no es la que dice el repo" tres semanas despues.
"""

import configparser
import pathlib
import re

import oys_connectors
from oys_connectors.odoo import VERSION as VERSION_CONECTOR

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def _version_pyproject():
    txt = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib  # 3.11+
        return tomllib.loads(txt)["project"]["version"]
    except ModuleNotFoundError:
        # DANTE corre 3.10 y no trae tomllib. Para leer una sola clave no vale
        # la pena una dependencia: el paquete no tiene ninguna a proposito.
        m = re.search(r'^\s*version\s*=\s*"([^"]+)"', txt, re.M)
        assert m, "no encontre version en pyproject.toml"
        return m.group(1)


def _cfg():
    c = configparser.ConfigParser()
    c.read(RAIZ / "setup.cfg", encoding="utf-8")
    return c


def test_las_tres_versiones_del_paquete_coinciden():
    py = _version_pyproject()
    cfg = _cfg()["metadata"]["version"]
    mod = oys_connectors.__version__
    assert py == cfg == mod, (
        "versiones desincronizadas -> pyproject=%s setup.cfg=%s __version__=%s"
        % (py, cfg, mod)
    )


def test_el_nombre_coincide_en_los_dos_formatos():
    txt = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^\s*name\s*=\s*"([^"]+)"', txt, re.M)
    assert m
    assert m.group(1) == _cfg()["metadata"]["name"] == "oys-connectors"


def test_la_version_del_conector_es_independiente_de_la_del_paquete():
    """No es un error que difieran: el conector versiona su CONTRATO.

    Si `setup.cfg` sube el paquete por un cambio de empaquetado, el contrato con
    Odoo no cambio y `oys_connectors.odoo.VERSION` no tiene por que moverse.
    Este test documenta esa independencia para que nadie las "sincronice"
    creyendo que es un descuido.
    """
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION_CONECTOR)
    assert re.fullmatch(r"\d+\.\d+\.\d+", oys_connectors.__version__)


def test_setup_cfg_declara_lo_minimo_para_pip_viejo():
    """Es lo que evita el `UNKNOWN-0.0.0` con pip 22."""
    md = _cfg()["metadata"]
    assert md["name"].strip()
    assert md["version"].strip()
