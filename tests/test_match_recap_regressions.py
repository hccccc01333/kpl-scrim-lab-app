"""Regression guards for single-match recap evidence and responsive layout."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "v3" / "public"

JS_CHECKS = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
const raw = fs.readFileSync(process.argv[1], 'utf8');
const mod = await import('data:text/javascript;base64,' + Buffer.from(raw).toString('base64'));
const { normalizedCamp, sampleNear, teamTotal, economyDirection, eventSide, laneRealisation } = mod;

assert.equal(normalizedCamp('left'), 'blue');
assert.equal(normalizedCamp('right'), 'red');
assert.equal(economyDirection(1500), '利于本队'); // even if the match was lost
assert.equal(economyDirection(-500), '利于对手');
assert.equal(economyDirection(0), '持平');
assert.equal(economyDirection(null), '未知');

const series = [{t: 10, gold: 100}, {t: 40, gold: 130}, {t: 150, gold: 240}];
assert.equal(sampleNear(series, 50)?.gold, 130);
assert.equal(sampleNear(series, 100), null); // no near-enough record
assert.equal(sampleNear(series, 40)?.gold, 130);
assert.equal(sampleNear([], 50), null);

const players = Array.from({length: 5}, (_, i) => ({
  camp: 'blue', gold: 1000 + i, kills: i === 0 ? 0 : i, partial: false
}));
assert.equal(teamTotal(players, 'left', 'gold'), 5010);
assert.equal(teamTotal(players, 'blue', 'kills'), 10);
assert.equal(teamTotal(players.slice(0, 4), 'blue', 'gold'), null);
assert.equal(teamTotal([...players.slice(0, 4), {...players[4], gold: null}], 'blue', 'gold'), null);
assert.equal(teamTotal([...players.slice(0, 4), {...players[4], partial: true}], 'blue', 'gold'), null);
assert.equal(teamTotal(players.map(p => ({...p, gold: 0})), 'blue', 'gold'), 0);

assert.equal(eventSide(null, 'blue'), null);
assert.equal(eventSide('garbled', 'blue'), null);
assert.equal(eventSide('red', 'left'), 'foe');
assert.equal(eventSide('blue', 'left'), 'own');
assert.equal(eventSide('red', null), null);

assert.equal(laneRealisation('压制', 500), true);
assert.equal(laneRealisation('压制', -500), false);
assert.equal(laneRealisation('劣势', -300), true);
assert.equal(laneRealisation('均势', 200), null);
assert.equal(laneRealisation('压制', null), null);
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_recap_metric_guards():
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", JS_CHECKS, str(FRONT / "match-recap-metrics.js")],
        text=True, capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_recap_page_uses_safe_metrics_and_labels():
    source = (FRONT / "app.js").read_text(encoding="utf-8")
    assert "economyDirection(s.delta)" in source
    assert "eventSide(e.killerCamp, own)" in source
    assert "teamTotal(m.players, camp, 'gold')" in source
    assert "sampleNear(absPoints, t)" in source
    assert "再没回落" not in source
    assert "realisedEarly" not in source
    assert "data-label=\"当时经济差\"" in source
    assert "本局兑现" not in source


def test_recap_layout_is_scoped_and_loaded():
    index = (FRONT / "index.html").read_text(encoding="utf-8")
    css = (FRONT / "match-recap-fixes.css").read_text(encoding="utf-8")
    assert 'static/match-recap-fixes.css' in index
    assert ".md-page .md-bp-bans" in css
    assert "repeat(var(--bp-slots, 5)" in css
    assert ".md-page .md-node-num::before" in css
    assert ".md-page .md-phase-gain::before" in css
