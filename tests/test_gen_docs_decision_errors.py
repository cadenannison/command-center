"""gen:build and gen:check name a malformed decision record in one line, not a traceback."""

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

import pytest

GEN_DOCS = Path(__file__).parent.parent / "scripts" / "gen_docs.py"


def load_gen_docs() -> ModuleType:
    loader = SourceFileLoader("gen_docs_under_test", str(GEN_DOCS))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.mark.parametrize("argv", [[], ["--check"]])
def test_a_malformed_record_exits_one_and_names_the_file(
    argv: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "0001-bad.md").write_text("nothing here\n", encoding="utf-8")
    gen_docs = load_gen_docs()
    decisions = gen_docs._decision_index()  # noqa: SLF001
    decisions.DECISIONS_DIR = tmp_path
    monkeypatch.setattr(gen_docs, "_decision_index", lambda: decisions)
    monkeypatch.setattr(gen_docs, "OUT_DIR", tmp_path / "out")

    with pytest.raises(SystemExit) as raised:
        gen_docs.main(argv)

    assert raised.value.code == 1
    err = capsys.readouterr().err
    assert "0001-bad.md" in err
    assert "Traceback" not in err
