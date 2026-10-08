"""API-Hilfe aus den cwapi3d-Type-Stubs (ohne `mcp` importierbar).

Das Werkzeug `get_cadwork_api_help` im Server ruft nur `hilfe()`.

Die Stubs kommen aus dem PyPI-Paket `cwapi3d` (Extra `stubs` in
pyproject.toml). Gemessen an cwapi3d 32.443.10: die Distribution heisst
`cwapi3d`, sie legt je Modul einen Ordner OHNE `__init__.py` an
(`element_controller/__init__.pyi`, `py.typed`) — Namespace-Pakete, der
Import liefert `__path__`.

Rueckmeldung 2026-09-28: im Server-Env fehlte das Paket, und die Antwort
hiess fuer JEDES Modul "stub_not_found" — der Agent hielt das Modul fuer
falsch und suchte woanders. Fehlt das Paket selbst, heisst die Antwort
jetzt "stubs_fehlen" und sagt, wie man es installiert.
"""

import ast
from pathlib import Path

PAKET = "cwapi3d"
INSTALL_HINWEIS = (
    "pip install cwapi3d (oder den Server mit dem Extra installieren: "
    "pip install \"open-mcp-cad[stubs]\") — im selben Python wie der "
    "MCP-Server. Die echten Aufrufe in Cadwork brauchen das Paket nicht.")


def stubs_installiert() -> bool:
    """Ist die Distribution `cwapi3d` im Python dieses Prozesses da?"""
    try:
        from importlib import metadata
        metadata.distribution(PAKET)
        return True
    except Exception:                                   # noqa: BLE001
        return False


def pyi_pfad(modul: str):
    """Die __init__.pyi eines cwapi3d-Moduls, sonst None."""
    try:
        m = __import__(modul)
    except Exception:                                   # noqa: BLE001
        return None
    pfade = getattr(m, "__path__", None)
    if not pfade:
        return None
    for p in pfade:
        pyi = Path(p) / "__init__.pyi"
        if pyi.exists():
            return pyi
    return None


def _signatur(node) -> str:
    try:
        args = ast.unparse(node.args)
    except Exception:                                   # noqa: BLE001
        args = "..."
    try:
        ret = ast.unparse(node.returns) if node.returns else None
    except Exception:                                   # noqa: BLE001
        ret = None
    return "(%s)%s" % (args, (" -> %s" % ret) if ret else "")


def funktionen(pyi: Path) -> list:
    """[{name, signature, summary}] aller Top-Level-Funktionen."""
    baum = ast.parse(pyi.read_text(encoding="utf-8"), filename=str(pyi))
    aus = []
    for node in baum.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        doc = ast.get_docstring(node) or ""
        aus.append({"name": node.name, "signature": _signatur(node),
                    "summary": doc.strip().split("\n", 1)[0] if doc else ""})
    return aus


def funktion(pyi: Path, name: str):
    """Signatur und voller Docstring einer Funktion, sonst None."""
    baum = ast.parse(pyi.read_text(encoding="utf-8"), filename=str(pyi))
    for node in baum.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return {"name": name, "signature": _signatur(node),
                    "docstring": ast.get_docstring(node) or ""}
    return None


def hilfe(module: str, function: str, module_liste, aliase) -> dict:
    """Antwort von get_cadwork_api_help."""
    if not module:
        antwort = {
            "ok": True,
            "modules": list(module_liste),
            "aliases": dict(aliase),
            "hint": ("Rufe erneut mit module='<name>' auf, um Funktionen "
                     "aufzulisten, oder zusätzlich mit function='<name>' "
                     "für Details."),
        }
        if not stubs_installiert():
            antwort["stubs"] = "fehlen"
            antwort["stubs_hinweis"] = INSTALL_HINWEIS
        return antwort

    if module not in module_liste and module != "cadwork":
        return {"ok": False, "error": "unknown_module",
                "message": f"Modul {module!r} nicht in CWAPI3D_MODULES.",
                "available": list(module_liste)}

    pyi = pyi_pfad(module)
    if pyi is None:
        if not stubs_installiert():
            return {
                "ok": False, "error": "stubs_fehlen",
                "message": ("Die cwapi3d-Type-Stubs sind im Python des "
                            "MCP-Servers nicht installiert — deshalb kann "
                            "die API-Hilfe KEIN Modul nachschlagen. Das "
                            "Modul %r ist nicht falsch. Die Aufrufe in "
                            "Cadwork selbst gehen trotzdem." % module),
                "hint": INSTALL_HINWEIS,
            }
        return {"ok": False, "error": "stub_not_found",
                "message": f"Kein .pyi-Stub für {module!r} gefunden."}

    if not function:
        try:
            liste = funktionen(pyi)
        except SyntaxError as exc:
            return {"ok": False, "error": "stub_parse_error",
                    "message": f"Stub für {module!r} konnte nicht geparst "
                               f"werden.",
                    "details": str(exc)}
        return {"ok": True, "module": module,
                "function_count": len(liste), "functions": liste}

    info = funktion(pyi, function)
    if info is None:
        return {"ok": False, "error": "unknown_function",
                "message": f"Funktion {function!r} nicht in Modul "
                           f"{module!r} gefunden."}
    return {"ok": True, "module": module, **info}
