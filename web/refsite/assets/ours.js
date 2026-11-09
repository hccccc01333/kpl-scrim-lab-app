/* 训练赛数据适配：把 /api/studio/teams 映射成参考站点读取的全局对象。
   在参考页面的数据脚本之后、页面脚本之前加载，直接覆盖 KPL_* 全局。
   没有的指标保持 null（页面显示「—」，雷达顶点落圆心），不伪造。 */
(function () {
  'use strict';

  function fetchJSON(url) {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', url, false);   // 同步：必须在页面脚本执行前就绪
    xhr.send(null);
    if (xhr.status !== 200) throw new Error('请求失败 ' + url);
    return JSON.parse(xhr.responseText);
  }

  var payload;
  try {
    payload = fetchJSON('/api/studio/teams');
  } catch (error) {
    console.error('[ours] 读取训练赛数据失败', error);
    return;
  }

  var list = [];
  if (payload.own) {
    list.push({
      team: payload.own.name || '我方',
      icon: '',
      own: true,
      matches: payload.own.matches || 0,
      wins: payload.own.wins || 0,
      losses: payload.own.losses || 0,
      wr: (payload.own.winRate == null ? null : payload.own.winRate / 100),
      gpm: payload.own.metrics ? payload.own.metrics.gpm : null,
      dpm: payload.own.metrics ? payload.own.metrics.dpm : null,
      tower: payload.own.metrics ? payload.own.metrics.towerPerGame : null,
      kda: payload.own.metrics ? payload.own.metrics.kda : null,
    });
  }
  (payload.teams || []).forEach(function (team) {
    list.push({
      team: team.displayName,
      icon: '',
      own: false,
      id: team.id,
      matches: team.matches || 0,
      wins: team.wins || 0,
      losses: team.losses || 0,
      // 营地口径给的是「我方胜率」，对手自己的胜率要反过来
      wr: (team.winRate == null ? null : 1 - team.winRate / 100),
      gpm: team.metrics ? team.metrics.gpm : null,
      dpm: team.metrics ? team.metrics.dpm : null,
      tower: team.metrics ? team.metrics.towerPerGame : null,
      kda: team.metrics ? team.metrics.kda : null,
    });
  });

  var scopeTeams = list.map(function (item) {
    return {
      team: item.team,
      icon: item.icon,
      matches: item.matches,
      mWin: item.wins,        // 训练赛按「局」记，没有大场；大场胜率等同单局胜率
      mLoss: item.losses,
      games: item.matches,
      wins: item.wins,
      losses: item.losses,
      wr: item.wr,
      gpm: item.gpm,
      dpm: item.dpm,
      kda: item.kda,
      by: [],
    };
  });

  // 局数按「我方对局数」计，不能把各队局数相加（同一局会被双方各记一次）
  var battles = payload.own ? (payload.own.matches || 0) : 0;

  /* 英雄组合：页面读 scope.combo2 / combo3，字段 h(英雄数组) / n(局数) / wr(胜率) / syn(协同) */
  var comboData = safeJSON('/api/studio/camp-combos?min=3');
  function comboRows(set, side) {
    var list = (set && set[side] && set[side].combos) || [];
    return list.filter(function (row) { return !row.small; }).map(function (row) {
      return {
        h: row.heroes,
        n: row.games,
        w: Math.round((row.winRate == null ? 0 : row.winRate / 100) * row.games),
        wr: row.winRate == null ? null : row.winRate / 100,
        syn: row.synergy == null ? 0 : row.synergy / 100,
      };
    });
  }
  var combo2 = comboRows(comboData && comboData.pairs, 'own');
  var combo3 = comboRows(comboData && comboData.trios, 'own');

  var scopePlayers = [];
  var scopeHeroes = [];

  window.KPL_SEASONS = {
    years: [2026],
    leagues: [{
      id: 'scrim-2026', name: '训练赛', year: 2026, type: '训练赛',
      start: '', end: '', matches: battles, battles: battles,
      champion: '', runner: '', champDate: '', champLeader: '', champFinished: false, legacy: false,
    }],
    scopes: {
      all: {
        totals: {matches: battles, battles: battles},
        teams: scopeTeams,
        players: scopePlayers,
        heroes: scopeHeroes,
        combo2: combo2,
        combo3: combo3,
      },
    },
  };

  // 六维战力：没有的分位留 null，team.html 会显示「样本不足」
  function percentile(values, value) {
    if (value == null) return null;
    var pool = values.filter(function (v) { return v != null; }).sort(function (a, b) { return a - b; });
    if (!pool.length) return null;
    var below = pool.filter(function (v) { return v <= value; }).length;
    return Math.round(below / pool.length * 100);
  }

  var gpmPool = list.map(function (item) { return item.gpm; });
  var dpmPool = list.map(function (item) { return item.dpm; });
  var towerPool = list.map(function (item) { return item.tower; });
  var wrPool = list.map(function (item) { return item.wr == null ? null : item.wr * 100; });
  var kdaPool = list.map(function (item) { return item.kda; });

  window.KPL_POWER = {
    meta: {
      builtAt: '', algorithmVersion: 'scrim-v1',
      dims: ['wr', 'mm', 'gold', 'kill', 'tower', 'res'],
      dimCN: {wr: '胜率', mm: '局分', gold: '经济', kill: '对抗', tower: '推进', res: '资源'},
      weights: {}, weightCN: {},
    },
    champions: [],
    scopes: {
      all: {
        n: list.length,
        threshold: {g: 1, m: 0},
        teams: list.map(function (item) {
          var wr = item.wr == null ? null : item.wr * 100;
          return {
            t: item.team, ic: item.icon,
            g: item.matches, m: item.matches, mw: item.wins, ml: item.losses,
            gw: item.wins, gl: item.losses,
            wr: item.wr, adjWR: item.wr, mm: item.wr,
            gold: item.gpm, kill: item.kda, tower: item.tower, res: null, dur: null,
            score: null, z: null,
            r: [
              percentile(wrPool, wr),
              percentile(wrPool, wr),
              percentile(gpmPool, item.gpm),
              percentile(kdaPool, item.kda),
              percentile(towerPool, item.tower),
              null,
            ],
          };
        }),
      },
    },
  };

  // 参考站点在 localhost 会插一条「本地实时服务」提示，训练平台里不需要
  var embed = /(^|&)embed=1(&|$)/.test(location.search.slice(1));
  var hide = document.createElement('style');
  hide.textContent = '#kplLocalRuntime{display:none!important}'
    + (embed ? '.topbar,.footer,#siteFooter,.mnav{display:none!important}'
      + 'body{padding-top:0!important}.wrap{max-width:none!important}' : '');
  document.head.appendChild(hide);
  if (embed) {
    var skin = document.createElement('link');
    skin.rel = 'stylesheet';
    skin.href = '/assets/refsite/assets/platform-skin.css';
    document.head.appendChild(skin);
  }

  window.SITE_DATA = {
    generatedAt: '',
    season: '训练赛',
    stats: {matches: battles, battles: battles, heroes: 0, playerRows: 0},
    model: {version: '', name: '', trainedAt: ''},
  };


  /* ---- 选手与英雄：把本队统计映射成参考站的 KPL_PLAYERS / SITE_DETAILS ---- */
  function safeJSON(url) {
    try { return fetchJSON(url); } catch (error) { return null; }
  }

  var playerData = safeJSON('/api/studio/view/players?own=1&compact=1');
  var heroData = safeJSON('/api/studio/view/heroes?own=1&compact=1');

  var players = {};
  ((playerData && playerData.players) || []).forEach(function (row) {
    players[row.label] = {
      games: row.matches || 0,
      wins: row.wins || 0,
      wr: row.winRate == null ? null : row.winRate / 100,
      kda: row.kda == null ? null : row.kda / 100,
      mvp: 0,
      part: row.participation == null ? null : row.participation,
      partN: row.matches || 0,
      dmg: row.dpm == null ? null : row.dpm,
      dmgN: row.matches || 0,
      gold: row.gpm == null ? null : row.gpm,
      pos: (row.positions || [])[0] || '',
      team: payload.own ? (payload.own.name || '我方') : '我方',
      teamIcon: '', icon: '',
      heroes: (row.heroes || []).slice(0, 12).map(function (hero) {
        return [hero.hero, hero.matches, null, null];
      }),
    };
  });
  window.KPL_PLAYERS = players;

  Object.keys(players).forEach(function (name) {
    var row = players[name];
    scopePlayers.push({
      name: name,
      team: row.team,
      teamIcon: '',
      icon: '',
      pos: row.pos,
      games: row.games,
      wins: row.wins,
      wr: row.wr,
      kda: row.kda == null ? null : row.kda * 100,
      mvp: 0,
      part: row.part,
      dmg: row.dmg,
      gold: row.gold,
      last: '',
    });
  });

  var heroList = ((heroData && heroData.heroes) || []).map(function (row) {
    var games = row.picks || 0;
    return {
      name: row.hero,
      icon: '',
      tier: '',
      games: games,
      wins: row.wins || 0,
      wr: row.winRate == null ? null : row.winRate / 100,
      pickRate: battles ? games / battles : null,
      banRate: null,
      kda: row.kda == null ? null : row.kda / 100,
      dmg: row.dpm,
      bh: null,
      players: row.players || [],
      teams: [],
      recent: [],
      trios: [],
      matchups: [],
    };
  });
  heroList.forEach(function (row) {
    scopeHeroes.push({
      name: row.name,
      icon: '',
      games: row.games,
      wins: row.wins,
      wr: row.wr,
      bans: 0,
      tier: '',
      kda: row.kda == null ? null : row.kda * 100,
      dmg: row.dmg,
      bh: null,
      gold: null,
      by: [],
    });
  });

  window.SITE_DETAILS = {
    generatedAt: '',
    matches: [],
    heroes: heroList,
  };


  /* ---- 赛程：KPL_SCHEDULE_ALL（h2h / schedule / find 共用） ---- */
  var matchData = safeJSON('/api/studio/view/matches?limit=500');
  var matches = (matchData && matchData.matches) || [];
  window.KPL_SCHEDULE_ALL = matches.map(function (m, index) {
    var own = payload.own ? (payload.own.name || '我方') : '我方';
    var opponent = m.opponent || '对手待补';
    var win = m.result === 'win';
    var left = m.ownCamp === 'blue' || m.ownCamp == null ? own : opponent;
    var right = left === own ? opponent : own;
    return {
      matchId: m.key || ('scrim-' + index),
      leagueId: 'scrim-2026', leagueName: '训练赛', year: 2026,
      stage: m.session || '训练赛', date: m.date || '', time: '',
      team1: left, icon1: '', team2: right, icon2: '',
      score1: m.result == null ? null : (win ? 1 : 0),
      score2: m.result == null ? null : (win ? 0 : 1),
      winner: m.result == null ? '' : (win ? own : opponent),
      done: m.result != null,
      scrim: true,
    };
  });

  /* ---- 荣誉：对内（周榜）/ 对外（月榜），六项分位加权 ---- */
  var HONOR_META = {
    builtAt: '', algorithmVersion: 'scrim-honors-v1',
    laneOrder: ['对抗路', '打野', '中路', '发育路', '游走'],
    dims: ['kda', 'gpm', 'dpm', 'bhpm', 'part', 'mvpRate'],
    dimCN: {kda: 'KDA', gpm: '分均经济', dpm: '分均输出', bhpm: '分均承伤', part: '参团率', mvpRate: 'MVP 率'},
    thresholds: {
      week: {minGames: 2, minMatches: 1}, month: {minGames: 4, minMatches: 2},
      team: {week: {minMatches: 1, minGames: 2}, month: {minMatches: 2, minGames: 4}},
      completeness: 0.9,
    },
    coverage: {matchFiles: matches.length, battles: battles, scopes: 1},
    formula: {
      weights: {
        '对抗路': {kda: .20, gpm: .10, dpm: .20, bhpm: .25, part: .10, mvpRate: .15},
        '打野': {kda: .22, gpm: .18, dpm: .18, bhpm: .17, part: .15, mvpRate: .10},
        '中路': {kda: .20, gpm: .14, dpm: .26, bhpm: .10, part: .15, mvpRate: .15},
        '发育路': {kda: .22, gpm: .18, dpm: .28, bhpm: .08, part: .12, mvpRate: .12},
        '游走': {kda: .18, gpm: .08, dpm: .10, bhpm: .28, part: .24, mvpRate: .12},
      },
      teamWeights: {wr: .5, goldDiff: .2, killDiff: .15, stab: .15},
    },
  };

  function zscores(rows, key) {
    var values = rows.map(function (r) { return r[key]; }).filter(function (v) { return typeof v === 'number' && isFinite(v); });
    if (values.length < 2) return {};
    var mean = values.reduce(function (a, b) { return a + b; }, 0) / values.length;
    var variance = values.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / values.length;
    var sd = Math.sqrt(variance) || 1;
    var out = {};
    rows.forEach(function (r) {
      out[r.name] = typeof r[key] === 'number' && isFinite(r[key]) ? (r[key] - mean) / sd : 0;
    });
    return out;
  }

  function buildBoard(candidates, lane) {
    var weights = (HONOR_META.formula.weights[lane]) || {kda: .2, gpm: .15, dpm: .2, bhpm: .2, part: .15, mvpRate: .1};
    var rows = candidates.filter(function (c) { return c.lane === lane; });
    if (!rows.length) return {n: 0, board: [], note: '该分路没有达到门槛的选手。'};
    var z = {};
    Object.keys(weights).forEach(function (key) { z[key] = zscores(rows, key); });
    var scored = rows.map(function (row) {
      var total = 0;
      Object.keys(weights).forEach(function (key) { total += weights[key] * (z[key][row.name] || 0); });
      return Object.assign({}, row, {z: Math.round(total * 100) / 100, score: Math.round(Math.max(0, Math.min(100, 50 + total * 16)))});
    }).sort(function (a, b) { return b.score - a.score; });
    scored.forEach(function (row, index) {
      row.t1 = index === 0 ? 1 : null;
      row.ci = [Math.max(0, row.score - 8), Math.min(100, row.score + 8)];
    });
    return {n: scored.length, board: scored, note: '六项在该分路内标准化后加权；MVP 率暂无样本，权重为 0。'};
  }

  function buildPeriod(id, label, players, teamRows, kind) {
    var lanes = {};
    HONOR_META.laneOrder.forEach(function (lane) { lanes[lane] = buildBoard(players, lane); });
    var board = teamRows.slice().sort(function (a, b) { return b.score - a.score; });
    board.forEach(function (row, index) {
      row.t1 = index === 0 ? 1 : null;
      row.ci = [Math.max(0, row.score - 8), Math.min(100, row.score + 8)];
    });
    return {
      id: id, label: label, start: '', end: '', ongoing: true, season: '训练赛',
      games: battles,
      matches: battles,
      lanes: lanes,
      team: {n: board.length, board: board, note: ''},
    };
  }

  var campCompare = safeJSON('/api/studio/camp-compare');
  function normalizeRow(row, teamName) {
    return {
      name: row.name, team: teamName || '我方',
      tic: '', pic: '',
      lane: row.lane || '',
      g: row.games || 0, m: row.games || 0,
      wr: row.winRate == null ? null : row.winRate / 100,
      kda: row.kda == null ? null : row.kda,
      gpm: row.gpm == null ? null : Math.round(row.gpm),
      dpm: row.dpm == null ? null : Math.round(row.dpm),
      bhpm: row.dtpm == null ? null : Math.round(row.dtpm),
      part: row.participation == null ? null : Math.round(row.participation),
      mvp: 0, mvpRate: 0,
    };
  }
  var ownPlayers = ((campCompare && campCompare.players && campCompare.players.own) || [])
    .map(function (row) { return normalizeRow(row, payload.own ? (payload.own.name || '我方') : '我方'); })
    .filter(function (row) { return row.lane; });

  var campCompare = safeJSON('/api/studio/camp-compare');
  var enemyPlayers = ((campCompare && campCompare.players && campCompare.players.enemy) || [])
    .map(function (row) {
      var team = (list.find(function (t) { return t.id === row.teamId; }) || {}).team;
      return normalizeRow(row, team || '对手');
    })
    .filter(function (row) { return row.lane; });

  function teamRow(item) {
    var wr = item.wr;
    return {
      team: item.team, tic: '', g: item.matches, m: item.matches,
      gw: item.wins, gl: item.losses, wr: wr, oppAdj: 0, stab: 0.2,
      score: Math.round(((wr == null ? 0 : wr) * 60 + Math.min(40, item.matches)) ),
    };
  }

  window.KPL_HONORS = {
    meta: HONOR_META,
    weeks: [buildPeriod('scrim-internal', '对内 · 本队', ownPlayers, [teamRow(list[0])], 'own')],
    months: [buildPeriod('scrim-external', '对外 · 全部对手', enemyPlayers, list.slice(1).map(teamRow), 'enemy')],
  };


  /* ---- 智能找局 / 精选对局：按局建档 ---- */
  window.KPL_GAME_INDEX = {};
  matches.forEach(function (m, index) {
    var id = m.key || ('scrim-' + index);
    var winnerName = m.result === 'win' ? (payload.own ? (payload.own.name || '我方') : '我方')
      : (m.result === 'loss' ? (m.opponent || '对手') : '');
    window.KPL_GAME_INDEX[id] = {
      b: [[id, 1, m.duration ? Math.round(m.duration / 60) : null, 0, winnerName, 3]],
    };
    // 赛程行补上找局要用的字段
    var row = window.KPL_SCHEDULE_ALL[index];
    if (row) {
      row.duration = m.duration ? Math.round(m.duration / 60) : null;
      row.winner = m.result === 'win' ? row.team1 : m.result === 'loss' ? row.team2 : '';
      row.state = m.result == null ? '未开始' : '已结束';
      row.game = 1;
    }
  });

  /* 精选对局：用训练赛能算的规则筛（不看胜率曲线） */
  var RULES = [
    {k: 'long', label: '长局', rule: '单局时长 ≥ 20 分钟', test: function (m) { return m.duration && m.duration / 60 >= 20; }},
    {k: 'short', label: '速通局', rule: '单局时长 ≤ 12 分钟', test: function (m) { return m.duration && m.duration / 60 <= 12; }},
    {k: 'blowout', label: '大分差', rule: '双方击杀差 ≥ 15', test: function (m) {
      var s = m.scores || {}; var a = Number(s.blue ?? s.left ?? 0), b = Number(s.red ?? s.right ?? 0);
      return Math.abs(a - b) >= 15;
    }},
    {k: 'close', label: '一杀之差', rule: '双方击杀差 ≤ 2 且总局数 ≥ 20', test: function (m) {
      var s = m.scores || {}; var a = Number(s.blue ?? s.left ?? 0), b = Number(s.red ?? s.right ?? 0);
      return Math.abs(a - b) <= 2 && (a + b) >= 20;
    }},
  ];
  var pickRows = [];
  matches.forEach(function (m, index) {
    var tags = RULES.filter(function (rule) { return rule.test(m); }).map(function (rule) { return rule.k; });
    if (!tags.length) return;
    pickRows.push({
      battleId: m.key || ('scrim-' + index), seq: index + 1,
      dur: m.duration ? Math.round(m.duration / 60) : null,
      win: m.result === 'win' ? 'left' : m.result === 'loss' ? 'right' : '',
      t1: (payload.own ? (payload.own.name || '我方') : '我方'), t2: m.opponent || '对手待补',
      winner: m.result === 'win' ? (payload.own ? (payload.own.name || '我方') : '我方')
        : (m.result === 'loss' ? (m.opponent || '对手') : ''),
      swing: null, minProb: null, minMinute: null, swingMinute: null,
      events: null, tags: tags, score: 50,
      matchId: m.key || ('scrim-' + index), date: m.date || '',
    });
  });
  window.KPL_PICKS = {
    updatedAt: '', totalBattles: battles,
    rows: pickRows,
    picked: pickRows.length,
    rules: RULES.map(function (rule) {
      return {k: rule.k, label: rule.label, rule: rule.rule,
              total: matches.filter(rule.test).length};
    }),
  };


  /* ---- BP：用营地面板的禁用/选用，按标准 20 手模板套出顺序 ---- */
  var bpMatches = matches.filter(function (m) { return m.campBp; });
  if (window.KPL_BP) {
    var heroNames = [];
    var heroIndex = {};
    function heroIdx(name) {
      if (!name) return null;
      if (heroIndex[name] == null) { heroIndex[name] = heroNames.length; heroNames.push(name); }
      return heroIndex[name];
    }
    // 模板：[阵营(0/1), 动作(1=禁 2=选)]
    var TEMPLATE = window.KPL_BP.template || [];
    var games = [];
    bpMatches.forEach(function (m, index) {
      var bp = m.campBp || {};
      var bans = {left: (bp.bans && bp.bans.left) || [], right: (bp.bans && bp.bans.right) || []};
      var picks = {left: (bp.picks && bp.picks.left) || [], right: (bp.picks && bp.picks.right) || []};
      var cursor = {left: {ban: 0, pick: 0}, right: {ban: 0, pick: 0}};
      var hands = [];
      TEMPLATE.forEach(function (hand) {
        var campKey = hand[0] === 0 ? 'left' : 'right';
        var action = hand[1];               // 1 禁 / 2 选
        var bucket = action === 1 ? bans[campKey] : picks[campKey];
        var slot = action === 1 ? 'ban' : 'pick';
        var entry = bucket[cursor[campKey][slot]];
        if (!entry || !entry.name) return;
        cursor[campKey][slot] += 1;
        hands.push((action === 1 ? 1 : 2) + ',' + (campKey === 'left' ? 1 : 2) + ',' + heroIdx(entry.name));
      });
      games.push([
        '2026', 'scrim-2026', m.session || '训练赛',
        m.team1 || '', m.team2 || '', 1,
        m.result === 'win' ? 1 : (m.result === 'loss' ? 2 : 0),
        hands.join(';'), '20',
      ]);
    });
    window.KPL_BP.heroes = heroNames;
    window.KPL_BP.games = games;
    window.KPL_BP.totalBattles = games.length;
    window.KPL_BP.leagues = {'scrim-2026': {name: '训练赛', year: '2026', stage: ['训练赛']}};
    window.KPL_BP.note = '手序按标准 20 手模板推定，非营地原始顺序。';
  }

  // 单队详情页需要的两份数据（暂不提供逐场系列与赛程）
  window.KPL_TEAM_DATA = {};
  // series.html 会读 D.matches / D.series；训练赛没有 BO 系列，给 0 并让页面走空态
  window.KPL_DEEP = {teams: {}, players: {}, matches: battles, series: 0};
})();
