"""Static checks for every module: imports, documentation and argument spec agree."""

import importlib
from pathlib import Path

import pytest
import yaml

from ansible_collections.velocloud.api.plugins.doc_fragments.operator import (
    ModuleDocFragment,
)

MODULES = sorted(
    p.stem
    for p in (Path(__file__).resolve().parents[2] / "plugins" / "modules").glob("*.py")
    if p.stem != "__init__"
)
FRAGMENTS = {
    "velocloud.api.operator": yaml.safe_load(ModuleDocFragment.DOCUMENTATION),
}


class _Captured(Exception):
    pass


def _load(name):
    return importlib.import_module(
        f"ansible_collections.velocloud.api.plugins.modules.{name}"
    )


def _import_errors(module):
    return [
        value
        for key, value in vars(module).items()
        if "IMPORT" in key.upper() and "ERR" in key.upper() and value
    ]


def _documented_options(module):
    doc = yaml.safe_load(module.DOCUMENTATION)
    options = {}
    for fragment in doc.get("extends_documentation_fragment") or []:
        options.update(FRAGMENTS[fragment].get("options", {}))
    options.update(doc.get("options") or {})
    return doc, options


def _argument_spec(module, monkeypatch):
    captured = {}

    def fake_module(**kwargs):
        captured.update(kwargs)
        raise _Captured

    monkeypatch.setattr(module, "AnsibleModule", fake_module)
    with pytest.raises(_Captured):
        module.main()
    return captured


@pytest.fixture(params=MODULES)
def module(request):
    return _load(request.param)


def test_imports_without_missing_dependencies(module):
    assert not _import_errors(module)


def test_documentation_parses(module):
    doc = _documented_options(module)[0]
    assert doc["module"] == module.__name__.rsplit(".", 1)[1]
    assert doc.get("short_description")
    assert yaml.safe_load(module.EXAMPLES)
    assert isinstance(yaml.safe_load(module.RETURN) or {}, dict)


def test_documented_options_match_argument_spec(module, monkeypatch):
    documented = _documented_options(module)[1]
    spec = _argument_spec(module, monkeypatch)["argument_spec"]
    assert set(documented) == set(spec)
    for name, arg in spec.items():
        doc = documented[name]
        assert doc.get("type", "str") == arg.get("type", "str"), name
        assert bool(doc.get("required")) == bool(arg.get("required")), name
        assert doc.get("default") == arg.get("default"), name
        assert doc.get("choices") == arg.get("choices"), name
        if arg.get("type") == "list":
            assert doc.get("elements") == arg.get("elements"), name
