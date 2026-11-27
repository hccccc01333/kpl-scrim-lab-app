"""回归：「待命名战队 #N」不得再冒充可选对手 / 分析对象。

问题背景：3.5.5 之后战队分析页和 BP 工作台仍出现占位队名。真实原因是
team_clusters / match_facts / analysis_profile 在读取时把未确认的签名簇
「显示兜底」成队名，而 bp_board 把这个 displayName 当成 opponent 往下传。
清缓存、前端隐藏都治不了：升级保留 data，兜底逻辑每次还会重算。

这里锁住四处口径：
1. 占位识别只有一份（workspace_store.is_placeholder_team）；
2. 工作区战队读取视图排除占位；
3. BP 取数只认真实战队卡，未确认局单独标记；
4. 前端浮层走 top-layer + CSS 锚定位，不再靠 JS 量矩形，Ban 斜线对齐头像。
"""
from pathlib import Path

import pytest

from workspace_store import Workspace, is_placeholder_team

ROOT = Path(__file__).resolve().parents[1]


class TestPlaceholderTeamIdentity:
    @pytest.mark.parametrize('name', [
        '', '   ', '待命名战队', '待命名战队 #3', '待命名战队 #15',
        '待命名队伍', '待命名', '未命名战队', '未标注对手', '未标注对手 #3',
    ])
    def test_placeholder_names_are_recognized(self, name):
        assert is_placeholder_team(name)

    @pytest.mark.parametrize('name', [
        '校队12', '成都AG超玩会青训分部', 'AGE超玩会青训分部', '本队', '__all__',
    ])
    def test_real_names_are_not_placeholders(self, name):
        assert not is_placeholder_team(name)

    def test_named_team_view_excludes_placeholders(self, tmp_path):
        ws = Workspace(tmp_path / 'training.sqlite3')
        ws.ensure_schema()
        ws.upsert_team(team_id='team-real', name='校队12', coach='张教练')
        # 写入口径不动：升级保留 data 时这类历史行确实还在，必须能在读取端挡住。
        ws.upsert_team(team_id='team-placeholder', name='待命名战队 #3')

        teams = ws.list_teams()
        assert {team['id']: team['placeholder'] for team in teams} == {
            'team-real': False, 'team-placeholder': True,
        }
        named = ws.list_named_teams()
        assert [team['id'] for team in named] == ['team-real']
        assert named[0]['name'] == '校队12'

    def test_identity_service_rejects_alias_placeholder(self):
        from identity_service import PLACEHOLDER_TEAM
        assert PLACEHOLDER_TEAM.match('待命名战队 #3')
        assert PLACEHOLDER_TEAM.match('待命名队伍')
        assert not PLACEHOLDER_TEAM.match('校队12')


class TestBpBoardOpponentContract:
    """静态守门：这些口径要跑真实营地数据，成本高，这里检查源码不回退。"""

    def test_bp_board_uses_real_name_only(self):
        source = (ROOT / 'v3' / 'serve.py').read_text(encoding='utf-8')
        assert "'opponent': real_name if named else ''" in source
        assert "is_placeholder_team(card['name'])" in source
        assert "team.get('displayName') or '未归属对手'" not in source
        assert "'unnamed': not named" in source

    def test_scrim_opponents_filter_placeholders(self):
        source = (ROOT / 'v3' / 'serve.py').read_text(encoding='utf-8')
        assert 'unassignedOpponents' in source
        assert "and not is_placeholder_team(game.get('enemy'))" in source

    def test_cluster_teams_never_expose_fake_name(self):
        source = (ROOT / 'v3' / 'serve.py').read_text(encoding='utf-8')
        assert "'name': _neutral_pending_team(cluster['id'])" in source
        assert "'pending': True" in source

    def test_studio_teams_endpoint_normalizes(self):
        source = (ROOT / 'studio_api.py').read_text(encoding='utf-8')
        assert 'def normalize(report)' in source
        assert "row['displayName'] = '未确认对手 · '" in source
        assert "result['pendingTeams'] = pending" in source

    def test_opponents_endpoint_skips_placeholders(self):
        source = (ROOT / 'v3' / 'serve.py').read_text(encoding='utf-8')
        assert "if not item.get('opponent') or is_placeholder_team(item['opponent']):" in source

    def test_analysis_opponents_endpoint_normalizes(self):
        source = (ROOT / 'studio_api.py').read_text(encoding='utf-8')
        assert "if is_placeholder_team(row.get('name')):" in source
        assert "row['name'] = '未确认对手 · '" in source
        assert "result['pendingHint'] = (" in source


class TestDropdownAndBanAlignment:
    def test_dropdown_uses_top_layer_and_anchor_positioning(self):
        js = (ROOT / 'v3' / 'public' / 'bp-studio.js').read_text(encoding='utf-8')
        css = (ROOT / 'v3' / 'public' / 'bp-studio.css').read_text(encoding='utf-8')
        assert 'popover="auto"' in js
        assert 'popovertarget="bps-pop-opponent"' in js
        # 不再用 JS 量矩形算浮层位置（其它分区的几何逻辑不在本测试范围）。
        close_pops = js.split('function closePops(')[1].split('\n  }')[0]
        assert 'getBoundingClientRect' not in close_pops
        assert 'panel.style.left' not in close_pops
        assert 'showPopover()' in close_pops
        assert '@supports (anchor-name: --bps-anchor)' in css
        assert 'position-area: block-end span-inline-end' in css
        assert 'position-try-fallbacks:' in css
        assert 'inset: auto' in css

    def test_dropdown_is_keyboard_operable_without_truncated_text(self):
        js = (ROOT / 'v3' / 'public' / 'bp-studio.js').read_text(encoding='utf-8')
        css = (ROOT / 'v3' / 'public' / 'bp-studio.css').read_text(encoding='utf-8')
        assert "'ArrowDown', 'ArrowUp', 'Home', 'End'" in js
        assert "const isPlaceholder = (name)" in js
        assert 'class="bps-pop-hint"' in js
        assert 'text-overflow: ellipsis' not in css.split('.bps-team-option b {')[1].split('}')[0]
        assert 'overflow-wrap: anywhere' in css
        assert 'max-height: 380px' not in css

    def test_ban_slash_is_aligned_to_avatar_box(self):
        js = (ROOT / 'v3' / 'public' / 'bp-studio.js').read_text(encoding='utf-8')
        css = (ROOT / 'v3' / 'public' / 'bp-studio.css').read_text(encoding='utf-8')
        assert '<span class="bps-ban-face"' in js
        ban_css = css.split('.bps-ban-face {')[1].split('@supports')[0]
        assert 'inline-size: 30px' in ban_css
        assert 'block-size: 30px' in ban_css
        assert 'inset: 0' in ban_css
        assert 'linear-gradient(to top right' in ban_css


class TestSourceOfTruth:
    """源头不再造名：三处口径一致，历史落盘缓存一次性失效。"""

    def test_real_team_name_normalizes_only_placeholders(self):
        from workspace_store import real_team_name
        assert real_team_name('待命名战队 #3') == ''
        assert real_team_name('待命名队伍') == ''
        assert real_team_name('未标注对手') == ''
        assert real_team_name('校队12') == '校队12'

    def test_source_modules_share_one_normalizer(self):
        for filename in ('match_facts.py', 'analysis_profile.py', 'team_clusters.py'):
            text = (ROOT / filename).read_text(encoding='utf-8')
            assert "f'待命名战队 #" not in text, filename
            assert 'real_team_name' in text or 'workspace_store import is_placeholder_team' in text
        assert 'real_team_name(names.get(key))' in (
            ROOT / 'analysis_profile.py').read_text(encoding='utf-8')
        assert "names.setdefault(key, '')" in (
            ROOT / 'match_facts.py').read_text(encoding='utf-8')
        assert 'is_placeholder_team(clean_name(name))' in (
            ROOT / 'team_clusters.py').read_text(encoding='utf-8')

    def test_name_policy_version_invalidates_old_disk_caches(self, tmp_path):
        from match_facts import _NAME_POLICY_VERSION, data_signature
        signature = data_signature(tmp_path / 'replays', tmp_path / 'camp')
        assert signature[-1] == _NAME_POLICY_VERSION
        assert 'no-placeholders' in _NAME_POLICY_VERSION

    def test_team_clusters_pending_teams_have_empty_names(self, tmp_path):
        import team_clusters
        from tests.test_team_clusters import A, panel, write_panels
        camp = tmp_path / 'camp'
        write_panels(camp, [('1', panel(1, A, '11-02 12:00'))])
        result = team_clusters.list_teams(camp, tmp_path / 'db.sqlite3', '本队')
        assert result['summary']['pending'] == 1
        assert all(team['displayName'] == '' and not team['named']
                   and team['name'] == '' for team in result['teams'])

    def test_match_facts_unconfirmed_names_are_empty(self):
        from match_facts import _opponent_names
        panels = {'1': {'start': '11-02 12:00', 'date': '11-02'}}
        names, _ = _opponent_names(None, panels, None, {'1': 'sig-1'})
        assert names == {'sig-1': ''}

    def test_migration_skips_unnamed_clusters(self):
        src = (ROOT / 'scripts' / 'migrate_matches.py').read_text(encoding='utf-8')
        assert 'real_team_name' in src
        assert 'if not name:' in src
        assert "upsert_team(team['id'], name=team['displayName']" not in src
