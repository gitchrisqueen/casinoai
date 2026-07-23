"""Review-gate tests: approval stamping and immutability."""

import pytest

from casinoai.strategies import load_spec
from casinoai.strategies.review import approve_spec, render_spec
from tests.strategies.test_spec import sample_spec


def test_approve_writes_immutable_yaml(tmp_path):
    spec = sample_spec()
    path = approve_spec(
        spec, approved_by="chris", annotations=["Top of ladder: reset"], approved_dir=tmp_path
    )
    assert path.name == "test-ladder-v1.yaml"
    saved = load_spec(path)
    assert saved.approval.approved_by == "chris"
    assert saved.approval.annotations == ["Top of ladder: reset"]

    with pytest.raises(FileExistsError, match="immutable"):
        approve_spec(sample_spec(), approved_by="chris", annotations=[], approved_dir=tmp_path)


def test_version_bump_gets_new_file(tmp_path):
    approve_spec(sample_spec(), approved_by="chris", annotations=[], approved_dir=tmp_path)
    v2 = sample_spec()
    v2.version = 2
    path = approve_spec(v2, approved_by="chris", annotations=[], approved_dir=tmp_path)
    assert path.name == "test-ladder-v2.yaml"


def test_render_spec_shows_ambiguities():
    out = render_spec(sample_spec())
    assert "AMBIGUITIES (1):" in out
    assert "top of the ladder" in out
