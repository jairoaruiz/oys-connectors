"""La version del paquete vive en DOS lugares y no pueden divergir.

`pyproject.toml` (PEP 621) y `oys_connectors.__version__`. Antes eran tres:
habia un `setup.cfg` con metadata clasica que se elimino en v0.1.2 — ver el
comentario en `[build-system]` de `pyproject.toml` y el commit de esa version.

Este test tambien cubre algo que un `pip install` local NO detecta: que el wheel
lleve el codigo y no solo metadata. Eso paso de verdad en DANTE con v0.1.1 (wheel
de 1043 B, `top_level.txt` vacio, `ModuleNotFoundError` al importar) y un build
local no lo reprodujo, porque local usa build-tools modernas.
"""

import pathlib
import re

import oys_connectors
from oys_connectors.odoo import VERSION as VERSION_CONECTOR

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def _pyproject_texto():
    return (RAIZ / "pyproject.toml").read_text(encoding="utf-8")


def _version_pyproject():
    txt = _pyproject_texto()
    try:
        import tomllib  # 3.11+
        return tomllib.loads(txt)["project"]["version"]
    except ModuleNotFoundError:
        # DANTE corre 3.10 y no trae tomllib. Para leer una sola clave no vale
        # la pena una dependencia: el paquete no tiene ninguna a proposito.
        m = re.search(r'^\s*version\s*=\s*"([^"]+)"', txt, re.M)
        assert m, "no encontre version en pyproject.toml"
        return m.group(1)


def test_las_dos_versiones_del_paquete_coinciden():
    py = _version_pyproject()
    mod = oys_connectors.__version__
    assert py == mod, (
        "versiones desincronizadas -> pyproject=%s __version__=%s" % (py, mod)
    )


def test_no_reaparecio_setup_cfg():
    """`setup.cfg` se elimino en v0.1.2 y no debe volver.

    Documentaba una causa equivocada ("pip viejo no lee metadata moderna") y su
    efecto real fue peor que el problema: con el presente, las build-tools viejas
    de DANTE tomaban la via clasica, y como no declaraba paquetes, el wheel salia
    **sin una sola linea de codigo**. Este test existe para que nadie lo resucite
    leyendo aquel comentario y creyendo que ayudaba.
    """
    assert not (RAIZ / "setup.cfg").exists(), (
        "reaparecio setup.cfg: ver el commit de v0.1.2 antes de agregarlo"
    )


def test_build_system_pide_wheel_explicito():
    """Sin `wheel` en `requires`, las tools viejas construyen por una via legacy."""
    txt = _pyproject_texto()
    m = re.search(r"^\s*requires\s*=\s*\[([^\]]*)\]", txt, re.M)
    assert m, "no encontre requires en [build-system]"
    req = m.group(1)
    assert "setuptools" in req and "wheel" in req


def test_el_paquete_declara_donde_estan_los_modulos():
    """Lo que faltaba cuando el wheel salio vacio.

    Si nadie declara los paquetes, setuptools no encuentra `oys_connectors/` y
    empaqueta solo `dist-info`. El sintoma es un `ModuleNotFoundError` DESPUES de
    un `Successfully installed`, que es de los peores: `pip show` da verde.
    """
    txt = _pyproject_texto()
    assert "[tool.setuptools.packages.find]" in txt
    assert "oys_connectors" in txt


def test_la_version_del_conector_es_independiente_de_la_del_paquete():
    """No es un error que difieran: el conector versiona su CONTRATO.

    Si el paquete sube por un cambio de empaquetado, el contrato con Odoo no
    cambio y `oys_connectors.odoo.VERSION` no tiene por que moverse. Este test
    documenta esa independencia para que nadie las "sincronice" creyendo que es
    un descuido.
    """
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION_CONECTOR)
    assert re.fullmatch(r"\d+\.\d+\.\d+", oys_connectors.__version__)
