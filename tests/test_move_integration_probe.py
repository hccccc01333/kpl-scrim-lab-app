"""Pin the negative result: `.abc` move commands cannot be integrated.

The replay stores inputs, not positions; the client recomputes state.  This test
keeps the measured verdict attached to the sample so nobody re-derives a
trajectory from move commands and presents it as data.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from probe_move_integration import probe  # noqa: E402

ABC = (ROOT / "data/replays/samples/20261102_161129"
       / "20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc")


@pytest.fixture(scope="module")
def report():
    if not ABC.exists():
        pytest.skip("sample replay not available")
    return probe(ABC)


def test_anchors_are_sparse(report):
    counts = report["anchorsPerEntity"]
    assert set(counts) == {"1760", "296"}
    assert counts["1760"] == 70
    assert counts["296"] == 8


def test_integration_has_no_predictive_power(report):
    assert report["verdict"] == "no predictive power"
    best = report["best"]
    assert best is not None
    # Residual is as large as the displacement it tries to explain.
    assert best["ratio"] > 0.8
    for fit in report["fits"]:
        assert fit["ratio"] > 0.8


def test_every_fit_is_reported_with_its_parameters(report):
    assert len(report["fits"]) == 4
    for fit in report["fits"]:
        assert set(fit) == {"entity", "ratio", "offsetDeg", "speed",
                            "intervals", "ySign"}
        assert 0 <= fit["offsetDeg"] < 360
