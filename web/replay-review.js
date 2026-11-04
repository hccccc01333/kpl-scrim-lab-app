/* Replay 2D review viewer — read-only, local-only.
 *
 * Data contract in this file:
 *   bundle file:  { name, label, date, players[], commands[], headings[], events[],
 *                   tail, heroMeta[], ratings[], stream[] }
 *   players   row: [team, slot, entity, nickname, offset]
 *   command   row: [seq, entity, isLocal(-1 unknown), type, id, x, y, cmdSeq, segment]
 *   heading   row: [seq, entity, isLocal, degree, segment]
 *   event     row: [seq, entity, isLocal, tag, sub, dataHex, segment]
 *   stream    row: [seq, entity, label, x|null, y|null, degree|null, data]
 *
 * Optional R1 JSONL adapter accepts: file/replay/sample, seq/frame,
 * hero_id/entity_id/actor, x/y, degree/heading, kind/type/tag, sub, label/message.
 * The adapter is intentionally permissive because docs/replay_event_stream.md
 * was not present when this viewer was built.
 */
(() => {
  'use strict';

  const FPS_ASSUMED = 30;
  const WORLD_HALF = 55000;
  const PLAYER_COLORS = ['#5aa9ff', '#ff8a9a', '#6ee7b7', '#fbbf24', '#c084fc', '#38bdf8', '#fb923c', '#f472b6', '#a3e635', '#22d3ee', '#e879f9', '#f87171'];
  const DATASET_FILES = [
    'replay_players.csv', 'replay_commands.csv', 'replay_heading.csv', 'replay_events.csv',
    'replay_tail_roster.csv', 'replay_tail_commands.csv', 'replay_tail_heading.csv',
    'replay_tail_events.csv', 'replay_tail_frames.csv', 'replay_tail_summary.csv',
    'agent_skin_ids.csv', 'replay_event_stream.jsonl',
    '20261102_buy_events.csv', '20261102_skill_events.csv',
    '20261102_player_actions.csv', 'agent_equip_prices.csv',
  ];
  const GZIP_STREAM_FILES = [
    'replay_event_stream_events.jsonl.gz',
    'replay_event_stream.jsonl.gz',
  ];
  const STREAM_POINT_ACTIONS = new Set([
    'aim_point_command', 'aim_trajectory_point', 'point_update', 'command',
    'use_position_skill', 'use_objective_skill', 'world_point', 'target_point',
  ]);

  const CMD_META = {
    0x0200: { key: 'attack', label: '攻击目标', short: '攻击', color: '#ff5c7a', cls: 'rr-tag-attack' },
    0x0201: { key: 'cancel', label: '攻击取消', short: '取消', color: '#6b7a90', cls: 'rr-tag-unknown' },
    0x0100: { key: 'skill', label: '技能瞄准', short: '技能', color: '#57b4ff', cls: 'rr-tag-skillcmd' },
    0x0101: { key: 'cancel', label: '技能取消', short: '取消', color: '#6b7a90', cls: 'rr-tag-unknown' },
    0x0400: { key: 'signal', label: '信号 / 小地图', short: '信号', color: '#45d18a', cls: 'rr-tag-signal' },
    0x0401: { key: 'cancel', label: '信号取消', short: '取消', color: '#6b7a90', cls: 'rr-tag-unknown' },
    0x0300: { key: 'unknown', label: '未知命令', short: '未知', color: '#a78bfa', cls: 'rr-tag-unknown' },
    0x0301: { key: 'cancel', label: '未知取消', short: '取消', color: '#6b7a90', cls: 'rr-tag-unknown' },
  };

  const EVENT_META = {
    buy: { label: 'BUYEQUIP 购买', short: '买', color: '#f4a261', cls: 'rr-tag-buy' },
    learn: { label: 'LEARNSKILL 加点', short: '点', color: '#b6e36a', cls: 'rr-tag-learn' },
    skill: { label: '技能升级', short: '技', color: '#f4c95d', cls: 'rr-tag-skill' },
    state: { label: '状态 0x23', short: '态', color: '#57b4ff', cls: 'rr-tag-state' },
    beacon: { label: 'beacon 0x03', short: 'b03', color: '#7e9cba', cls: 'rr-tag-beacon' },
    tail: { label: '尾部事件', short: '尾', color: '#f2a7ff', cls: 'rr-tag-tail' },
    other: { label: '其他 / 待解', short: '?', color: '#a78bfa', cls: 'rr-tag-unknown' },
    stream: { label: 'R1 其他事件', short: '流', color: '#e879f9', cls: 'rr-tag-tail' },
  };

  const TIMELINE_CATS = ['buy', 'learn', 'skill', 'state', 'beacon', 'tail', 'other', 'stream'];
  const COMMAND_CHIPS = ['attack', 'skill', 'signal', 'unknown', 'cancel'];
  const EVENT_CHIPS = ['buy', 'learn', 'skill', 'state', 'beacon', 'tail', 'other', 'stream'];
  const DEFAULT_EVENT_CATS = ['buy', 'learn', 'skill', 'state', 'tail', 'other', 'stream'];

  const state = {
    dataset: null,
    file: null,
    time: 0,
    minSeq: 0,
    maxSeq: 1,
    playing: false,
    speed: 1,
    loop: false,
    focusEntity: null,
    tab: 'now',
    filters: {
      search: '',
      team: 'all',
      hero: 'all',
      localOnly: false,
      hidden: new Set(),
      eventCats: new Set(DEFAULT_EVENT_CATS),
      commandCats: new Set(['attack', 'skill', 'signal', 'unknown']),
      eventFocusOnly: false,
      commandFocusOnly: false,
    },
    layers: {
      history: true,
      labels: true,
      heading: true,
      events: true,
      map: true,
      historyWindow: 1800,
    },
    dirty: true,
    inspectorDirty: true,
    lastInspectorAt: 0,
    lastRenderAt: 0,
    lastTs: 0,
    modelCache: new Map(),
    timelineCache: null,
    mapGeom: null,
    mapHits: [],
    mouse: { x: 0, y: 0, inside: false, hit: null },
    timelineHoverSeq: null,
    mapSize: { w: 0, h: 0 },
    timelineSize: { w: 0, h: 0 },
    pendingSample: null,
    pendingTime: null,
    pendingEntity: null,
    searchTimer: null,
    toastTimer: null,
    mapStats: { commands: 0, visible: 0, stream: 0 },
    streamStatus: null,
    staticScreenshotChecks: [],
    staticEquipPrices: {},
    staticHeroNames: {},
    staticEventStreamIndex: null,
    staticEventStreams: [],
  };

  const els = {};

  function cacheEls() {
    const ids = [
      'source-badge', 'btn-reload', 'btn-folder', 'btn-path', 'btn-gzip', 'gzip-input', 'folder-input', 'sample-select',
      'sample-count', 'sample-meta', 'sample-warnings', 'source-list', 'search', 'team-filter',
      'hero-filter', 'local-only', 'btn-all-players', 'btn-none-players', 'visible-count',
      'roster-list', 'btn-reset-filters', 'layer-history', 'layer-labels', 'layer-heading',
      'layer-events', 'layer-map', 'history-window', 'map', 'map-empty', 'map-time',
      'map-visible', 'map-cmds', 'map-selected', 'map-subtitle', 'btn-step-back100',
      'btn-step-back1', 'btn-play', 'btn-step-fwd1', 'btn-step-fwd100', 'speed-select',
      'loop-toggle', 'btn-tail', 'time-display', 'timeline', 'timeline-tooltip', 'scrubber',
      'tail-marker-text', 'inspector-body', 'footer-source', 'toast',
    ];
    ids.forEach((id) => { els[toCamel(id)] = document.getElementById(id); });
    els.tabs = Array.from(document.querySelectorAll('.rr-tab'));
  }

  function toCamel(id) {
    return id.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  }

  // ---------------------------------------------------------------------------
  // generic helpers
  // ---------------------------------------------------------------------------
  function $(sel, root = document) { return root.querySelector(sel); }
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
  }
  function fmt(n) { return Number(n || 0).toLocaleString('en-US'); }
  function fmtClock(frame) {
    const seconds = Math.max(0, frame) / FPS_ASSUMED;
    const m = Math.floor(seconds / 60);
    const s = seconds - m * 60;
    return `${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
  }
  function truncate(text, max = 28) {
    const chars = Array.from(String(text == null ? '' : text));
    return chars.length > max ? chars.slice(0, max - 1).join('') + '…' : chars.join('');
  }
  function formatBytes(bytes) {
    if (!bytes) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  }
  function hexLabel(n) {
    if (n == null || Number.isNaN(n)) return '—';
    return n < 0 ? `-0x${Math.abs(n).toString(16)}` : `0x${Number(n).toString(16)}`;
  }
  function num(value, fallback = 0) {
    if (value == null || value === '') return fallback;
    const text = String(value).trim();
    if (/^-0x/i.test(text)) return -parseInt(text.slice(3), 16);
    if (/^0x/i.test(text)) return parseInt(text.slice(2), 16);
    const parsed = Number(text);
    return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
  }
  function numOrNull(value) {
    if (value == null || value === '') return null;
    const parsed = num(value, NaN);
    return Number.isFinite(parsed) ? parsed : null;
  }
  function firstNum(...values) {
    for (const value of values) {
      const parsed = numOrNull(value);
      if (parsed != null) return parsed;
    }
    return null;
  }
  function toast(message, isError = false, ms = 4200) {
    if (!els.toast) return;
    els.toast.textContent = message;
    els.toast.hidden = false;
    els.toast.classList.toggle('is-error', !!isError);
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => { els.toast.hidden = true; }, ms);
  }
  function clamp(value, lo, hi) { return Math.max(lo, Math.min(hi, value)); }

  function parseCsv(text) {
    const rows = [];
    let row = [];
    let field = '';
    let quoted = false;
    const source = String(text || '').replace(/^\uFEFF/, '');
    for (let i = 0; i < source.length; i++) {
      const ch = source[i];
      if (quoted) {
        if (ch === '"') {
          if (source[i + 1] === '"') { field += '"'; i++; } else { quoted = false; }
        } else {
          field += ch;
        }
      } else if (ch === '"') {
        quoted = true;
      } else if (ch === ',') {
        row.push(field);
        field = '';
      } else if (ch === '\n') {
        row.push(field);
        rows.push(row);
        row = [];
        field = '';
      } else if (ch !== '\r') {
        field += ch;
      }
    }
    if (field !== '' || row.length) {
      row.push(field);
      rows.push(row);
    }
    if (!rows.length) return [];
    const headers = rows[0].map((h) => h.trim());
    return rows.slice(1)
      .filter((cells) => cells.some((cell) => cell !== ''))
      .map((cells) => {
        const item = {};
        headers.forEach((header, index) => { item[header] = cells[index] == null ? '' : cells[index]; });
        return item;
      });
  }

  // ---------------------------------------------------------------------------
  // dataset construction
  // ---------------------------------------------------------------------------
  function emptyRaw(name) {
    let label = name;
    let date = '';
    const match = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/.exec(name);
    if (match) {
      label = `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}:${match[6]}`;
      date = `${match[1]}-${match[2]}-${match[3]}`;
    }
    return {
      name, label, date, players: [], commands: [], headings: [], events: [],
      tail: null, heroMeta: [], ratings: [], stream: [], streamHeroNames: {},
      buyEvents: [], skillEvents: [], actions: [], synthetic: false,
      _playerSet: new Set(),
      _buySkillHydrated: false,
    };
  }

  function ensureRaw(map, name) {
    if (!name) return null;
    if (!map.has(name)) {
      const raw = emptyRaw(name);
      map.set(name, raw);
      return raw;
    }
    return map.get(name);
  }

  function rowsOf(texts, name) {
    const text = texts[name.toLowerCase()];
    return text ? parseCsv(text) : [];
  }

  function parseEquipPrices(rows) {
    const prices = {};
    rows.forEach((row) => {
      if ((row.section || '') !== 'battle_item') return;
      const id = num(row.item_id);
      if (!id) return;
      prices[String(id)] = {
        name: row.item_name || '',
        buy: num(row.buy_price),
        sell: num(row.sell_price),
        type: num(row.price_type),
      };
    });
    return prices;
  }

  function addPlayerToRaw(raw, entity, team, slot, name, heroId, heroNames) {
    if (!raw || !entity) return;
    if (!(raw._playerSet instanceof Set)) {
      raw._playerSet = new Set((raw.players || []).map((row) => row[2]));
    }
    if (!raw._playerSet.has(entity) && !(raw.players || []).some((row) => row[2] === entity)) {
      raw.players.push([team || 0, slot == null ? null : slot, entity, name || '未知选手', '']);
      raw._playerSet.add(entity);
    } else if (name) {
      const row = raw.players.find((item) => item[2] === entity);
      if (row && (!row[3] || row[3] === '未知选手')) row[3] = name;
    }
    if (heroId) {
      const heroName = (heroNames && heroNames[String(heroId)]) || '';
      const meta = (raw.heroMeta || []).find((item) => item[0] === entity);
      if (!meta) {
        raw.heroMeta.push([entity, heroId, heroName, '', '']);
      } else if (!meta[2] && heroName) {
        meta[2] = heroName;
      }
    }
    if (name) raw.streamHeroNames[entity] = name;
  }

  function makeBuyStreamRow(frame, entity, equipId, equipName, buyPrice, autoRaw, firstForEntity, equipPrices) {
    const info = (equipPrices && equipPrices[String(equipId)]) || {};
    return [
      frame, entity, 'BUYEQUIP', null, null, null, '',
      'BUYEQUIP', equipId, equipName || info.name || '',
      buyPrice || info.buy || 0, null, null, autoRaw == null ? null : autoRaw,
      firstForEntity == null ? null : firstForEntity, null,
    ];
  }

  function makeLearnStreamRow(frame, entity, slot, level0, autoRaw) {
    return [
      frame, entity, 'LEARNSKILL', null, null, null, '',
      'LEARNSKILL', null, null, null, slot, level0 == null ? null : level0 + 1,
      autoRaw == null ? null : autoRaw, null, level0,
    ];
  }

  function hydrateRawBuySkill(raw, equipPrices) {
    if (!raw || raw._buySkillHydrated) return;
    (raw.buyEvents || []).forEach((row) => {
      if (!row) return;
      raw.stream.push(makeBuyStreamRow(row[0], row[1], row[2], row[3], row[4], row[5], row[6], equipPrices));
    });
    (raw.skillEvents || []).forEach((row) => {
      if (!row) return;
      raw.stream.push(makeLearnStreamRow(row[0], row[1], row[2], row[3], row[4]));
    });
    raw._buySkillHydrated = true;
  }

  function applyBuySkillRows(rawMap, buyRows, skillRows, actionRows, equipPrices, heroNames) {
    let buyCount = 0;
    let skillCount = 0;
    let actionCount = 0;
    buyRows.forEach((row) => {
      const raw = ensureRaw(rawMap, row.file);
      if (!raw) return;
      const frame = num(row.frame);
      const entity = num(row.entity);
      const heroId = num(row.hero_id);
      const equipId = num(row.equip_id);
      const priceInfo = (equipPrices && equipPrices[String(equipId)]) || {};
      const equipName = row.equip_name || priceInfo.name || '';
      const buyPrice = num(row.buy_price) || priceInfo.buy || 0;
      addPlayerToRaw(raw, entity, 0, null, row.player || '', heroId, heroNames);
      raw.buyEvents.push([
        frame, entity, equipId, equipName, buyPrice,
        row.auto_buy === '' || row.auto_buy == null ? null : num(row.auto_buy),
        row.first_for_entity === '' || row.first_for_entity == null ? null : num(row.first_for_entity),
      ]);
      buyCount++;
    });
    skillRows.forEach((row) => {
      const raw = ensureRaw(rawMap, row.file);
      if (!raw) return;
      const level0 = num(row.level);
      addPlayerToRaw(raw, num(row.entity), 0, null, row.player || '', num(row.hero_id), heroNames);
      raw.skillEvents.push([
        num(row.frame), num(row.entity), num(row.slot), level0,
        row.auto_learn === '' || row.auto_learn == null ? null : num(row.auto_learn),
      ]);
      skillCount++;
    });
    actionRows.forEach((row) => {
      const raw = ensureRaw(rawMap, row.file);
      if (!raw) return;
      addPlayerToRaw(raw, num(row.entity), 0, null, row.player || '', num(row.hero_id), heroNames);
      raw.actions.push([
        num(row.entity), row.player || '', num(row.hero_id), Number(row.score) || 0,
        num(row.buy_events_raw), num(row.unique_buy_items),
        num(row.unique_equip_price_sum_unverified) || num(row.unique_buy_spend_lower_bound),
        row.buy_equip_ids || '', num(row.learn_events), row.learn_slots || '',
        num(row.move_events), num(row.attack_events), num(row.directional_skill),
        num(row.position_skill), num(row.objective_skill),
        num(row.move_events_file_total), num(row.attack_events_file_total),
        num(row.attackwithobj_events_file_total), row.per_player_attribution || '',
      ]);
      actionCount++;
    });
    rawMap.forEach((raw) => {
      raw.synthetic = !raw.commands.length && !raw.headings.length && !raw.events.length
        && (raw.buyEvents.length > 0 || raw.skillEvents.length > 0);
      hydrateRawBuySkill(raw, equipPrices);
    });
    return { buyCount, skillCount, actionCount };
  }

  // R1 JSONL adapter.  Field names are intentionally permissive; BUYEQUIP and
  // LEARNSKILL are classified explicitly and never treated as gold income.
  function applyStreamRecord(rawMap, record, equipPrices, heroNames, keys) {
    if (!record || typeof record !== 'object') return { applied: false };
    const hint = String(record.file || record.replay || record.sample || record.source_file
      || record.match || record.match_id || record.source || '').split(/[\\/]/).pop();
    const keyList = keys || Array.from(rawMap.keys());
    let fileKey = hint ? matchFileKey(hint, keyList) : null;
    let raw = fileKey ? rawMap.get(fileKey) : null;
    if (!raw && hint) {
      raw = emptyRaw(hint);
      rawMap.set(hint, raw);
      keyList.push(hint);
      fileKey = hint;
    }
    if (!raw && keyList.length === 1) {
      fileKey = keyList[0];
      raw = rawMap.get(fileKey);
    }
    if (!raw) return { applied: false, reason: 'file' };

    const seq = firstNum(record.seq, record.frame, record.frame_index, record.frameIndex,
      record.frame_seq, record.t, record.tick);
    if (seq == null) return { applied: false, reason: 'seq' };
    const extra = record.extra || {};
    // R1's event-stream "hero_id" is the R2 roster entity/object id (e.g. 1879),
    // while actor_id is a child actor.  Prefer hero_id, then explicit entity ids.
    const heroTemplateId = firstNum(extra.hero_template_id, record.hero_template_id);
    let entity = firstNum(record.hero_id, record.entity_id, record.entityId, record.object_id,
      extra.hero_object_id, extra.object_id, record.actor_id, record.actor, record.heroId);
    if (entity == null) entity = 0;
    const playerName = extra.player || record.player || '';
    const knownEntity = raw.players.some((row) => row[2] === entity);
    if (knownEntity || playerName) {
      addPlayerToRaw(raw, entity, firstNum(extra.team, record.team), firstNum(extra.slot, record.slot),
        playerName, heroTemplateId, heroNames);
    }

    const kind = String(record.kind || record.event || record.type || '');
    let action = String(record.action || '');
    if (!action) action = kind === 'buy_equip' ? 'BUYEQUIP' : kind === 'learn_skill' ? 'LEARNSKILL' : kind || 'event';
    const buy = /BUYEQUIP|buy_equip/i.test(action) || /buy_equip/i.test(kind);
    const learn = /LEARNSKILL|learn_skill/i.test(action) || /learn_skill/i.test(kind);
    const x = firstNum(record.x, record.target_x, record.targetX, record.point && record.point.x,
      record.target && record.target.x, record.pos && record.pos.x);
    const y = firstNum(record.y, record.target_y, record.targetY, record.point && record.point.y,
      record.target && record.target.y, record.pos && record.pos.y);
    const degree = firstNum(record.direction, record.degree, record.heading, record.angle, record.dir);
    const data = record.raw_hex || record.data_hex || record.data || record.payload || '';

    if (buy) {
      const itemId = firstNum(record.item_id, extra.equip_id);
      const info = (equipPrices && equipPrices[String(itemId)]) || {};
      const itemName = info.name || record.item_name || '';
      const autoRaw = firstNum(extra.auto_buy_raw, record.auto_buy_raw);
      raw.buyEvents.push([seq, entity, itemId, itemName, info.buy || 0, autoRaw, null]);
      raw.stream.push(makeBuyStreamRow(seq, entity, itemId, itemName, info.buy || 0, autoRaw, null, equipPrices));
    } else if (learn) {
      const slot = firstNum(record.skill_slot, extra.skill_slot);
      const level0 = firstNum(extra.level, record.level);
      const level = firstNum(extra.level_display, level0 == null ? null : level0 + 1);
      const autoRaw = firstNum(extra.auto_learn_raw, record.auto_learn_raw);
      raw.skillEvents.push([seq, entity, slot, level0, autoRaw]);
      const row = makeLearnStreamRow(seq, entity, slot, level0, autoRaw);
      row[12] = level;
      raw.stream.push(row);
    } else {
      const label = action + (kind && kind !== action ? ` · ${kind}` : '');
      raw.stream.push([seq, entity, label, x, y, degree, String(data), action,
        null, null, null, null, null, null, null, null]);
    }
    return { applied: true, file: fileKey, action };
  }

  function applyStreamLines(rawMap, lines, equipPrices, heroNames) {
    let applied = 0;
    let unmatched = 0;
    const keys = Array.from(rawMap.keys());
    lines.forEach((line) => {
      let record;
      try { record = JSON.parse(line); } catch (error) { unmatched++; return; }
      const result = applyStreamRecord(rawMap, record, equipPrices, heroNames, keys);
      if (result.applied) applied++; else unmatched++;
    });
    return { applied, unmatched };
  }

  function sortRaw(raw) {
    raw.players.sort((a, b) => (a[0] - b[0]) || ((a[1] == null ? 99 : a[1]) - (b[1] == null ? 99 : b[1])) || (a[2] - b[2]));
    raw.commands.sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[8] - b[8]));
    raw.headings.sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[4] - b[4]));
    raw.events.sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[6] - b[6]));
    raw.stream.sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]));
    raw.heroMeta.sort((a, b) => a[0] - b[0]);
    raw.ratings.sort((a, b) => a[0] - b[0]);
    raw.buyEvents.sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[2] - b[2]));
    raw.skillEvents.sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[2] - b[2]));
    raw.actions.sort((a, b) => a[0] - b[0]);
  }

  function buildDatasetFromTexts(texts, source, label) {
    const rawMap = new Map();
    const players = rowsOf(texts, 'replay_players.csv');
    const commands = rowsOf(texts, 'replay_commands.csv');
    const headings = rowsOf(texts, 'replay_heading.csv');
    const events = rowsOf(texts, 'replay_events.csv');
    const tailRoster = rowsOf(texts, 'replay_tail_roster.csv');
    const tailCommands = rowsOf(texts, 'replay_tail_commands.csv');
    const tailHeadings = rowsOf(texts, 'replay_tail_heading.csv');
    const tailEvents = rowsOf(texts, 'replay_tail_events.csv');
    const tailFrames = rowsOf(texts, 'replay_tail_frames.csv');
    const skinRows = rowsOf(texts, 'agent_skin_ids.csv');
    const buyRows = rowsOf(texts, '20261102_buy_events.csv');
    const skillRows = rowsOf(texts, '20261102_skill_events.csv');
    const actionRows = rowsOf(texts, '20261102_player_actions.csv');
    const equipPrices = parseEquipPrices(rowsOf(texts, 'agent_equip_prices.csv'));
    const heroNames = state.staticHeroNames || {};

    players.forEach((row) => {
      const raw = ensureRaw(rawMap, row.file);
      if (!raw) return;
      raw.players.push([num(row.team), num(row.slot), num(row.hero_id), row.name || '', row.offset || '']);
    });

    commands.forEach((row) => {
      const raw = ensureRaw(rawMap, row.file);
      if (!raw) return;
      raw.commands.push([num(row.seq), num(row.hero_id), row.is_local === '1' ? 1 : 0, num(row.type), num(row.id), num(row.x), num(row.y), num(row.cmd_seq), 0]);
    });
    tailCommands.forEach((row) => {
      const raw = ensureRaw(rawMap, row.file);
      if (!raw) return;
      raw.commands.push([num(row.seq), num(row.hero_id), -1, num(row.type), num(row.id), num(row.x), num(row.y), num(row.cmd_seq), 1]);
    });

    headings.forEach((row) => {
      const raw = ensureRaw(rawMap, row.file);
      if (!raw) return;
      raw.headings.push([num(row.seq), num(row.hero_id), row.is_local === '1' ? 1 : 0, num(row.degree), 0]);
    });
    tailHeadings.forEach((row) => {
      const raw = ensureRaw(rawMap, row.file);
      if (!raw) return;
      raw.headings.push([num(row.seq), num(row.hero_id), -1, num(row.degree), 1]);
    });

    events.forEach((row) => {
      const raw = ensureRaw(rawMap, row.file);
      if (!raw) return;
      raw.events.push([num(row.seq), num(row.hero_id), row.is_local === '1' ? 1 : 0, num(row.tag), num(row.sub), row.data_hex || '', 0]);
    });
    tailEvents.forEach((row) => {
      const raw = ensureRaw(rawMap, row.file);
      if (!raw) return;
      raw.events.push([num(row.seq), num(row.hero_id), -1, num(row.tag), num(row.sub), row.data_hex || '', 1]);
    });

    const tailRanges = new Map();
    tailFrames.forEach((row) => {
      const name = row.file;
      if (!name) return;
      if (!tailRanges.has(name)) tailRanges.set(name, []);
      tailRanges.get(name).push(num(row.seq));
    });

    tailRoster.forEach((row) => {
      const raw = ensureRaw(rawMap, row.file);
      if (!raw) return;
      const pairs = (row.hero_skin_pairs || '').split(/\s+/).filter(Boolean).map((pair) => {
        const [entity, value] = pair.split(':');
        return [num(entity), num(value)];
      });
      const range = tailRanges.get(row.file);
      raw.tail = {
        lastMainSeq: num(row.last_main_seq),
        secondStart: num(row.second_start),
        secondFrames: num(row.second_frames),
        tailBytes: num(row.tail_bytes),
        footerBytes: num(row.footer_bytes),
        footerExtra: num(row.footer_extra),
        frameStart: range && range.length ? Math.min(...range) : null,
        frameEnd: range && range.length ? Math.max(...range) : null,
        pairs,
        localSlot: row.local_slot === '' || row.local_slot == null ? null : num(row.local_slot),
        localHero: row.local_hero === '' || row.local_hero == null ? null : num(row.local_hero),
        values: row.values || '',
        rawPairs: row.hero_skin_pairs || '',
      };
    });

    skinRows.forEach((row) => {
      const raw = rawMap.get(row.sample);
      if (!raw) return;
      if (row.record_type === 'player_skin') {
        raw.heroMeta.push([num(row.entityID), num(row.heroID), row.heroName || '', row.derived || '', row.derived_name || '']);
      } else if (row.record_type === 'trailer_score') {
        raw.ratings.push([num(row.entityID), Math.round(num(row.raw) / 10) / 10, row.verdict || '', num(row.team), num(row.slot)]);
      }
    });

    const buySkill = applyBuySkillRows(rawMap, buyRows, skillRows, actionRows, equipPrices, heroNames);
    rawMap.forEach((raw) => {
      raw._playerSet = new Set((raw.players || []).map((row) => row[2]));
    });

    const streamLines = (texts['replay_event_stream.jsonl'] || '').split(/\r?\n/).filter((line) => line.trim());
    let streamApplied = 0;
    let streamUnmatched = 0;
    if (streamLines.length) {
      const result = applyStreamLines(rawMap, streamLines, equipPrices, heroNames);
      streamApplied = result.applied;
      streamUnmatched = result.unmatched;
    }

    const files = Array.from(rawMap.values());
    files.forEach((raw) => sortRaw(raw));
    if (!files.length) {
      throw new Error('未找到可用数据（至少需要 replay_*.csv、11/2 购买/加点 CSV 或 gzip 事件流）');
    }

    files.sort((a, b) => String(b.label).localeCompare(String(a.label)));
    const counts = {
      files: files.length,
      players: files.reduce((sum, f) => sum + f.players.length, 0),
      commands: files.reduce((sum, f) => sum + f.commands.length, 0),
      headings: files.reduce((sum, f) => sum + f.headings.length, 0),
      events: files.reduce((sum, f) => sum + f.events.length, 0),
      tailSegments: files.filter((f) => f.tail && f.tail.secondFrames).length,
      tailFrames: files.reduce((sum, f) => sum + ((f.tail && f.tail.secondFrames) || 0), 0),
      stream: files.reduce((sum, f) => sum + f.stream.length, 0),
      buyEvents: files.reduce((sum, f) => sum + f.buyEvents.length, 0),
      skillEvents: files.reduce((sum, f) => sum + f.skillEvents.length, 0),
      playerActions: files.reduce((sum, f) => sum + f.actions.length, 0),
    };

    const sourceFiles = DATASET_FILES.map((name) => {
      const text = texts[name.toLowerCase()];
      if (!text) return { name, ok: false, rows: 0, bytes: 0 };
      const rows = name.endsWith('.csv') ? parseCsv(text).length : text.split(/\r?\n/).filter(Boolean).length;
      return { name, ok: true, rows, bytes: text.length };
    });

    return {
      source, label, files, counts, sourceFiles, streamApplied, streamUnmatched, generatedAt: '',
      equipPrices, heroNames,
      screenshotChecks: state.staticScreenshotChecks || [],
      eventStreamIndex: state.staticEventStreamIndex,
      eventStreams: state.staticEventStreams || [],
      buySkill,
    };
  }

  function buildDatasetFromBundle(bundle) {
    const equipPrices = bundle.equipPrices || {};
    const heroNames = bundle.heroNames || {};
    state.staticEquipPrices = equipPrices;
    state.staticHeroNames = heroNames;
    state.staticScreenshotChecks = bundle.screenshotChecks || [];
    state.staticEventStreamIndex = bundle.eventStreamIndex || null;
    state.staticEventStreams = bundle.eventStreams || [];
    const files = bundle.files.map((item) => Object.assign(emptyRaw(item.name || ''), item, {
      players: item.players || [],
      commands: item.commands || [],
      headings: item.headings || [],
      events: item.events || [],
      tail: item.tail || null,
      heroMeta: item.heroMeta || [],
      ratings: item.ratings || [],
      stream: item.stream || [],
      streamHeroNames: item.streamHeroNames || {},
      buyEvents: item.buyEvents || [],
      skillEvents: item.skillEvents || [],
      actions: item.actions || [],
      synthetic: !!item.synthetic,
      _playerSet: new Set((item.players || []).map((row) => row[2])),
      _buySkillHydrated: false,
    }));
    files.forEach((raw) => hydrateRawBuySkill(raw, equipPrices));
    let streamApplied = 0;
    let streamUnmatched = 0;
    if (bundle.eventStream && Array.isArray(bundle.eventStream.lines) && bundle.eventStream.lines.length) {
      const result = applyStreamLines(new Map(files.map((f) => [f.name, f])), bundle.eventStream.lines, equipPrices, heroNames);
      streamApplied = result.applied;
      streamUnmatched = result.unmatched;
    }
    files.forEach((raw) => sortRaw(raw));
    files.sort((a, b) => String(b.label).localeCompare(String(a.label)));
    return {
      source: 'bundle',
      label: '内置快照',
      files,
      counts: bundle.counts || {},
      sourceFiles: (bundle.sourceFiles || []).map((item) => ({ ...item, rows: null })),
      streamApplied,
      streamUnmatched,
      generatedAt: bundle.generatedAt || '',
      equipPrices,
      heroNames,
      screenshotChecks: state.staticScreenshotChecks,
      eventStreamIndex: state.staticEventStreamIndex,
      eventStreams: state.staticEventStreams,
    };
  }

  function matchFileKey(hint, keys) {
    if (!hint) return keys.length === 1 ? keys[0] : null;
    if (keys.includes(hint)) return hint;
    const exact = keys.find((key) => key === hint || key.startsWith(hint) || hint.startsWith(key));
    if (exact) return exact;
    const loose = keys.find((key) => key.includes(hint) || hint.includes(key));
    return loose || null;
  }

  // ---------------------------------------------------------------------------
  // model
  // ---------------------------------------------------------------------------
  function groupByEntity(rows) {
    const map = new Map();
    rows.forEach((row) => {
      const entity = row[1];
      if (!map.has(entity)) map.set(entity, []);
      map.get(entity).push(row);
    });
    return map;
  }

  function buildPurchaseModel(raw, equipPrices) {
    const map = new Map();
    const ensure = (entity) => {
      if (!map.has(entity)) {
        map.set(entity, {
          rawNotifications: 0, items: new Map(), spendLowerBound: 0, unknownPriceItems: 0,
          firstFrame: null, lastFrame: null, learnEvents: 0, learnRows: [], learnSlots: new Map(),
          firstLearnFrame: null,
        });
      }
      return map.get(entity);
    };
    (raw.buyEvents || []).forEach((row) => {
      const entity = row[1];
      if (entity == null) return;
      const entry = ensure(entity);
      entry.rawNotifications++;
      entry.firstFrame = entry.firstFrame == null ? row[0] : Math.min(entry.firstFrame, row[0]);
      entry.lastFrame = entry.lastFrame == null ? row[0] : Math.max(entry.lastFrame, row[0]);
      const key = String(row[2]);
      if (!entry.items.has(key)) {
        const info = (equipPrices && equipPrices[key]) || {};
        const price = row[4] || info.buy || 0;
        entry.items.set(key, {
          itemId: row[2], name: row[3] || info.name || '装备未识别', price,
          firstFrame: row[0], notifications: 0,
        });
        if (price) entry.spendLowerBound += price; else entry.unknownPriceItems++;
      }
      entry.items.get(key).notifications++;
    });
    (raw.skillEvents || []).forEach((row) => {
      const entity = row[1];
      if (entity == null) return;
      const entry = ensure(entity);
      entry.learnEvents++;
      entry.learnRows.push(row);
      entry.firstLearnFrame = entry.firstLearnFrame == null ? row[0] : Math.min(entry.firstLearnFrame, row[0]);
      const slot = row[2] == null ? '?' : row[2];
      entry.learnSlots.set(slot, (entry.learnSlots.get(slot) || 0) + 1);
    });
    return map;
  }

  function buildFileModel(raw) {
    const equipmentPrices = (state.dataset && state.dataset.equipPrices) || state.staticEquipPrices || {};
    const commands = raw.commands.slice().sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[8] - b[8]));
    const headings = raw.headings.slice().sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[4] - b[4]));
    const events = raw.events.slice().sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[6] - b[6]));
    const stream = (raw.stream || []).slice().sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]));
    const streamPoints = stream.filter((row) => row[3] != null && row[4] != null
      && (!row[7] || STREAM_POINT_ACTIONS.has(String(row[7]))));
    const purchaseByEntity = buildPurchaseModel(raw, equipmentPrices);

    const localEntities = new Set();
    commands.forEach((row) => { if (row[2] === 1) localEntities.add(row[1]); });
    headings.forEach((row) => { if (row[2] === 1) localEntities.add(row[1]); });

    const heroMeta = new Map();
    raw.heroMeta.forEach((row) => {
      heroMeta.set(row[0], { heroId: row[1], heroName: row[2], skinId: row[3], skinName: row[4] });
    });
    const ratings = new Map();
    raw.ratings.forEach((row) => {
      ratings.set(row[0], { rating: row[1], verdict: row[2], team: row[3], slot: row[4] });
    });

    const rosterByEntity = new Map();
    const roster = [];
    raw.players.forEach((row) => {
      const player = {
        entity: row[2], team: row[0], slot: row[1], name: row[3] || '未知选手',
        offset: row[4], source: 'players',
      };
      roster.push(player);
      rosterByEntity.set(player.entity, player);
    });
    heroMeta.forEach((meta, entity) => {
      let player = rosterByEntity.get(entity);
      if (!player) {
        player = { entity, team: 0, slot: null, name: '未知选手', offset: '', source: 'heroMeta' };
        roster.push(player);
        rosterByEntity.set(entity, player);
      }
      player.heroId = meta.heroId;
      player.heroName = meta.heroName;
      player.skinId = meta.skinId;
      player.skinName = meta.skinName;
    });
    ratings.forEach((meta, entity) => {
      let player = rosterByEntity.get(entity);
      if (!player) {
        player = { entity, team: meta.team || 0, slot: meta.slot == null ? null : meta.slot, name: '未知选手', offset: '', source: 'ratings' };
        roster.push(player);
        rosterByEntity.set(entity, player);
      }
      player.rating = meta.rating;
      player.verdict = meta.verdict;
    });

    const tailPairs = (raw.tail && raw.tail.pairs) || [];
    const tailRoster = tailPairs.map((pair, index) => {
      const entity = pair[0];
      const rawValue = pair[1];
      let player = rosterByEntity.get(entity);
      if (!player) {
        player = { entity, team: 0, slot: null, name: '未知选手', offset: '', source: 'tail' };
        roster.push(player);
        rosterByEntity.set(entity, player);
      }
      player.tailValue = rawValue;
      player.tailIndex = index;
      if (player.rating == null) player.rating = Math.round(rawValue) / 100;
      return {
        entity, rawValue, rating: Math.round(rawValue) / 100, index,
        player, verdict: player.verdict || '', name: player.name, heroName: player.heroName || '',
      };
    });

    const commandCount = new Map();
    commands.forEach((row) => commandCount.set(row[1], (commandCount.get(row[1]) || 0) + 1));
    const headingCount = new Map();
    headings.forEach((row) => headingCount.set(row[1], (headingCount.get(row[1]) || 0) + 1));
    const eventCount = new Map();
    events.forEach((row) => eventCount.set(row[1], (eventCount.get(row[1]) || 0) + 1));
    const streamCount = new Map();
    stream.forEach((row) => streamCount.set(row[1], (streamCount.get(row[1]) || 0) + 1));

    roster.sort((a, b) => ((a.team || 9) - (b.team || 9)) || ((a.slot == null ? 9 : a.slot) - (b.slot == null ? 9 : b.slot)) || (a.entity - b.entity));
    roster.forEach((player, index) => {
      player.index = index;
      player.color = PLAYER_COLORS[index % PLAYER_COLORS.length];
      player.isLocal = localEntities.has(player.entity);
      player.commandCount = commandCount.get(player.entity) || 0;
      player.headingCount = headingCount.get(player.entity) || 0;
      player.eventCount = eventCount.get(player.entity) || 0;
      player.streamCount = streamCount.get(player.entity) || 0;
    });

    let minDataSeq = Infinity;
    let maxSeq = 0;
    [commands, headings, events, stream].forEach((rows) => rows.forEach((row) => {
      if (row[0] < minDataSeq) minDataSeq = row[0];
      if (row[0] > maxSeq) maxSeq = row[0];
    }));
    if (raw.tail) {
      maxSeq = Math.max(maxSeq, raw.tail.frameEnd || 0, raw.tail.lastMainSeq || 0);
    }
    let tailStart = raw.tail && raw.tail.secondFrames
      ? (raw.tail.frameStart || (raw.tail.lastMainSeq || 0) + 1) : null;
    let tailEnd = raw.tail && raw.tail.secondFrames
      ? (raw.tail.frameEnd || (tailStart + raw.tail.secondFrames - 1)) : null;
    if (raw.tail && raw.tail.secondFrames && !raw.tail.frameStart) {
      const tailSeqs = [];
      commands.forEach((row) => { if (row[8] === 1) tailSeqs.push(row[0]); });
      headings.forEach((row) => { if (row[4] === 1) tailSeqs.push(row[0]); });
      events.forEach((row) => { if (row[6] === 1) tailSeqs.push(row[0]); });
      if (tailSeqs.length) {
        tailStart = Math.min(...tailSeqs);
        tailEnd = Math.max(Math.max(...tailSeqs), tailStart + raw.tail.secondFrames - 1);
      }
    }
    if (tailEnd) maxSeq = Math.max(maxSeq, tailEnd);
    if (!Number.isFinite(minDataSeq)) minDataSeq = 0;
    maxSeq = Math.max(1, maxSeq);

    const eventCategoryCounts = {};
    EVENT_CHIPS.forEach((key) => { eventCategoryCounts[key] = 0; });
    events.forEach((row) => { eventCategoryCounts[eventCategory(row)] = (eventCategoryCounts[eventCategory(row)] || 0) + 1; });
    stream.forEach((row) => {
      const cat = streamCategory(row);
      eventCategoryCounts[cat] = (eventCategoryCounts[cat] || 0) + 1;
    });

    const commandCategoryCounts = {};
    COMMAND_CHIPS.forEach((key) => { commandCategoryCounts[key] = 0; });
    commands.forEach((row) => {
      const key = commandMeta(row[3]).key;
      commandCategoryCounts[key] = (commandCategoryCounts[key] || 0) + 1;
    });

    const tailCounts = {
      commands: commands.filter((row) => row[8] === 1).length,
      headings: headings.filter((row) => row[4] === 1).length,
      events: events.filter((row) => row[6] === 1).length,
      stream: 0,
    };

    let firstCommandSeq = null;
    for (const row of commands) {
      if (!isCancelCommand(row)) { firstCommandSeq = row[0]; break; }
    }
    if (firstCommandSeq == null && commands.length) firstCommandSeq = commands[0][0];

    return {
      name: raw.name,
      label: raw.label,
      date: raw.date,
      raw,
      players: raw.players,
      commands,
      headings,
      events,
      stream,
      streamPoints,
      buyEvents: raw.buyEvents || [],
      skillEvents: raw.skillEvents || [],
      actions: raw.actions || [],
      purchaseByEntity,
      synthetic: !!raw.synthetic,
      tailRoster,
      tail: raw.tail,
      tailStart,
      tailEnd,
      heroMeta,
      ratings,
      roster,
      rosterByEntity,
      commandsByEntity: groupByEntity(commands),
      headingsByEntity: groupByEntity(headings),
      eventsByEntity: groupByEntity(events),
      streamByEntity: groupByEntity(stream),
      localEntities,
      minDataSeq,
      maxSeq,
      firstCommandSeq,
      commandCategoryCounts,
      eventCategoryCounts,
      tailCounts,
      commandEntityCount: new Set(commands.map((row) => row[1])).size,
      playerBlockCount: raw.players.length,
      missingHero: roster.filter((player) => !player.heroName).length,
      localNames: Array.from(localEntities).map((entity) => rosterByEntity.get(entity)).filter(Boolean),
    };
  }

  function getModel(raw) {
    if (!state.modelCache.has(raw.name)) state.modelCache.set(raw.name, buildFileModel(raw));
    return state.modelCache.get(raw.name);
  }

  // ---------------------------------------------------------------------------
  // command / event semantics
  // ---------------------------------------------------------------------------
  function commandMeta(type) {
    return CMD_META[type] || {
      key: 'unknown', label: `命令 ${hexLabel(type)}`, short: '未知', color: '#a78bfa', cls: 'rr-tag-unknown',
    };
  }
  function isCancelCommand(row) {
    return (row[3] & 0xff) === 1 || (row[5] === 0 && row[6] === 0);
  }
  function eventCategory(row) {
    const segment = row[6] || 0;
    const tag = row[3];
    const sub = row[4];
    if (segment === 1) return (tag === 2 && (sub === 0 || sub === 0x87)) ? 'skill' : 'tail';
    if (tag === 2 && (sub === 0 || sub === 0x87)) return 'skill';
    if (tag === 1 && sub === 35) return 'state';
    if (tag === 1 && sub === 3) return 'beacon';
    return 'other';
  }
  function streamCategory(row) {
    const action = String((row && row[7]) || '');
    if (/BUYEQUIP|buy_equip/i.test(action)) return 'buy';
    if (/LEARNSKILL|learn_skill/i.test(action)) return 'learn';
    return 'stream';
  }
  function decodeSkill(dataHex) {
    const hex = String(dataHex || '');
    if (hex.length < 12) return null;
    const actor = parseInt(hex.slice(6, 8), 16);
    const slot = parseInt(hex.slice(8, 10), 16);
    const level = parseInt(hex.slice(10, 12), 16) + 1;
    if (!Number.isFinite(actor) || !Number.isFinite(slot) || !Number.isFinite(level)) return null;
    return { actor, slot, level };
  }
  function eventDetail(row) {
    const cat = eventCategory(row);
    const data = row[5] || '';
    if (cat === 'skill') {
      if (row[4] === 0x87) return `LEARNSKILL · data ${truncate(data || '—', 24)}`;
      const decoded = decodeSkill(data);
      return decoded
        ? `actor ${decoded.actor} · slot ${decoded.slot} → lv ${decoded.level} · ${truncate(data, 18)}`
        : `data ${truncate(data, 26)}`;
    }
    if (row[3] === 2 && row[4] === 0x85) {
      return `BUYEQUIP 出装 · data ${truncate(data || '—', 18)}（去重标价和，不是花费/收入）`;
    }
    if (cat === 'state') {
      const value = data ? parseInt(data.slice(-2), 16) : NaN;
      return `值 ${Number.isFinite(value) ? value : '?'} · data ${truncate(data || '—', 18)}`;
    }
    if (cat === 'beacon') return `data ${truncate(data || '0300', 18)}`;
    return `tag ${hexLabel(row[3])} / sub ${hexLabel(row[4])}${data ? ` · ${truncate(data, 18)}` : ''}`;
  }
  function streamDetail(row) {
    const action = String(row[7] || '');
    if (/BUYEQUIP|buy_equip/i.test(action)) {
      const price = row[10] ? `${fmt(row[10])} 金` : '价格未命中';
      const first = row[14] === 1 ? ' · 首次购买（去重键）' : row[14] === 0 ? ' · 重复通知' : '';
      return `BUYEQUIP · #${row[8] == null ? '?' : row[8]} ${row[9] || '装备未识别'} · ${price}（标价参考，不是花费/收入）${first}`;
    }
    if (/LEARNSKILL|learn_skill/i.test(action)) {
      const level = row[12] == null ? '?' : row[12];
      const level0 = row[15] == null ? '' : `（0-based ${row[15]}）`;
      return `LEARNSKILL · 技能 ${row[11] == null ? '?' : row[11]} → 等级 ${level}${level0}`;
    }
    const parts = [];
    if (row[2]) parts.push(String(row[2]));
    if (row[3] != null && row[4] != null) parts.push(`x ${fmt(row[3])}, y ${fmt(row[4])}`);
    if (row[5] != null) parts.push(`朝向 ${row[5]}°`);
    if (row[6]) parts.push(truncate(row[6], 26));
    return parts.join(' · ') || 'R1 事件流记录';
  }

  // ---------------------------------------------------------------------------
  // time / playback
  // ---------------------------------------------------------------------------
  function setTime(value, options = {}) {
    state.time = clamp(Number(value) || 0, state.minSeq, state.maxSeq);
    if (options.pause !== false) setPlaying(false);
    updateTimeUI();
    state.dirty = true;
    state.inspectorDirty = true;
    renderInspector();
  }
  function stepTime(delta) {
    setTime(Math.round(state.time) + delta, { pause: true });
  }
  function setPlaying(playing) {
    if (state.playing === playing) return;
    state.playing = playing;
    if (els.btnPlay) {
      els.btnPlay.textContent = playing ? '暂停' : '播放';
      els.btnPlay.classList.toggle('is-playing', playing);
      els.btnPlay.setAttribute('aria-label', playing ? '暂停' : '播放');
    }
    if (playing && state.time >= state.maxSeq) state.time = state.minSeq;
    state.dirty = true;
  }
  function togglePlay() { setPlaying(!state.playing); }
  function jumpTail() {
    if (state.file && state.file.tailStart != null) {
      setTime(state.file.tailStart, { pause: true });
      toast(`已跳到尾部第二段起点：帧 ${fmt(state.file.tailStart)}`);
    } else {
      toast('该样本没有尾部第二段（712 帧只在 20260925_105224 样本出现）', true);
    }
  }
  function updateTimeUI() {
    const frame = Math.floor(state.time);
    if (els.timeDisplay) els.timeDisplay.textContent = `帧 ${fmt(frame)} / ${fmt(state.maxSeq)} · ${fmtClock(frame)}`;
    if (els.mapTime) els.mapTime.textContent = `帧 ${fmt(frame)}`;
    if (els.scrubber) {
      els.scrubber.max = String(state.maxSeq);
      if (document.activeElement !== els.scrubber) els.scrubber.value = String(clamp(frame, state.minSeq, state.maxSeq));
    }
    if (els.btnTail) els.btnTail.disabled = !(state.file && state.file.tailStart != null);
    if (els.mapSelected) {
      const player = state.focusEntity != null && state.file ? state.file.rosterByEntity.get(state.focusEntity) : null;
      els.mapSelected.textContent = player ? `聚焦：${player.name} · ${player.heroName || '英雄未解析'} · #${player.entity}` : '未选中选手';
    }
    if (els.tailMarkerText) {
      const file = state.file;
      if (file && file.tail && file.tail.secondFrames) {
        els.tailMarkerText.textContent = `尾部 ${file.tail.secondFrames} 帧 · seq ${fmt(file.tailStart)}–${fmt(file.tailEnd)}`;
      } else {
        els.tailMarkerText.textContent = '无尾部第二段';
      }
    }
  }

  // ---------------------------------------------------------------------------
  // filters / roster
  // ---------------------------------------------------------------------------
  function matchingRoster(model = state.file) {
    if (!model) return [];
    const query = state.filters.search.trim().toLowerCase();
    return model.roster.filter((player) => {
      if (state.filters.team !== 'all' && String(player.team) !== state.filters.team) return false;
      if (state.filters.hero !== 'all') {
        const hero = player.heroName || '__unknown__';
        if (hero !== state.filters.hero) return false;
      }
      if (state.filters.localOnly && !player.isLocal) return false;
      if (query) {
        const haystack = [player.name, player.heroName, player.skinName, String(player.entity),
          player.slot != null ? `t${player.team}·${player.slot}` : ''].join(' ').toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    });
  }
  function visibleEntitySet() {
    return new Set(matchingRoster().filter((player) => !state.filters.hidden.has(player.entity)).map((player) => player.entity));
  }
  function populateHeroFilter() {
    if (!state.file) return;
    const heroes = Array.from(new Set(state.file.roster.map((player) => player.heroName).filter(Boolean)))
      .sort((a, b) => String(a).localeCompare(String(b), 'zh'));
    if (state.file.roster.some((player) => !player.heroName)) heroes.push('__unknown__');
    const current = state.filters.hero;
    els.heroFilter.innerHTML = '<option value="all">全部</option>'
      + heroes.map((hero) => `<option value="${esc(hero)}">${hero === '__unknown__' ? '未解析' : esc(hero)}</option>`).join('');
    state.filters.hero = heroes.includes(current) ? current : 'all';
    els.heroFilter.value = state.filters.hero;
  }
  function renderRoster() {
    if (!state.file) {
      els.rosterList.innerHTML = '<div class="rr-empty">尚未载入数据</div>';
      els.visibleCount.textContent = '0 / 0 可见';
      return;
    }
    const matching = matchingRoster();
    if (!matching.length) {
      els.rosterList.innerHTML = '<div class="rr-empty">筛选条件下没有选手</div>';
      els.visibleCount.textContent = `0 / ${state.file.roster.length} 可见`;
      return;
    }
    const visible = matching.filter((player) => !state.filters.hidden.has(player.entity));
    els.visibleCount.textContent = `${visible.length} / ${state.file.roster.length} 可见`;
    els.rosterList.innerHTML = matching.map((player) => {
      const hidden = state.filters.hidden.has(player.entity);
      const selected = player.entity === state.focusEntity;
      const slot = player.slot != null ? `T${player.team}·${player.slot}` : 'T?';
      const rating = player.rating != null ? Number(player.rating).toFixed(2) : '—';
      const badge = player.verdict === 'mvp'
        ? '<span class="rr-role-badge">MVP</span>'
        : player.verdict === 'svp' ? '<span class="rr-role-badge svp">SVP</span>' : '';
      const hero = player.heroName || '英雄未解析';
      const skin = player.skinName ? ` · ${player.skinName}` : '';
      const noCommand = player.commandCount ? '' : ' · 无命令';
      return `<div class="rr-player team-${player.team || 0}${hidden ? ' is-hidden' : ''}${selected ? ' is-selected' : ''}" data-entity="${player.entity}" tabindex="0" title="${esc(`${player.name} · ${hero} · entity #${player.entity}`)}">
        <input type="checkbox" data-entity="${player.entity}" ${hidden ? '' : 'checked'} aria-label="显示 ${esc(player.name)}">
        <span class="rr-slot">${esc(slot)}</span>
        <span class="rr-player-main">
          <span class="rr-player-name"><i class="rr-player-color" style="background:${player.color}"></i>${esc(player.name)}${player.isLocal ? '<i class="rr-local-dot" title="本地/被记录视角"></i>' : ''}</span>
          <span class="rr-player-sub">${esc(hero)}${esc(skin)} · #${player.entity}${esc(noCommand)}</span>
        </span>
        <span class="rr-player-badges"><span class="rr-rating">${esc(rating)}</span>${badge}</span>
      </div>`;
    }).join('');
  }
  function applyFilters() {
    renderRoster();
    state.dirty = true;
    state.inspectorDirty = true;
    renderInspector();
  }

  // ---------------------------------------------------------------------------
  // sample loading / metadata
  // ---------------------------------------------------------------------------
  function setDataset(dataset) {
    state.dataset = dataset;
    state.modelCache.clear();
    state.timelineCache = null;
    state.filters.hidden.clear();
    state.filters.search = '';
    state.filters.team = 'all';
    state.filters.hero = 'all';
    state.filters.localOnly = false;
    state.filters.eventCats = new Set(DEFAULT_EVENT_CATS);
    state.filters.commandCats = new Set(['attack', 'skill', 'signal', 'unknown']);
    state.filters.eventFocusOnly = false;
    state.filters.commandFocusOnly = false;
    if (els.search) els.search.value = '';
    if (els.teamFilter) els.teamFilter.value = 'all';
    if (els.localOnly) els.localOnly.checked = false;
    state.streamStatus = null;

    renderSampleOptions();

    let chosen = null;
    if (state.pendingSample) {
      chosen = dataset.files.find((raw) => raw.name === state.pendingSample || raw.label === state.pendingSample
        || raw.name.startsWith(state.pendingSample)) || null;
    }
    if (!chosen) chosen = dataset.files.find((raw) => raw.tail && raw.tail.secondFrames) || dataset.files[0];
    if (!chosen) {
      toast('数据集中没有样本', true);
      return;
    }
    els.sampleSelect.value = chosen.name;
    updateSourceBadge();
    renderSourceList();
    loadFileByName(chosen.name, {
      time: state.pendingTime != null ? Number(state.pendingTime) : null,
      entity: state.pendingEntity != null ? Number(state.pendingEntity) : null,
    });
    state.pendingSample = null;
    state.pendingTime = null;
    state.pendingEntity = null;
  }

  function renderSampleOptions() {
    const dataset = state.dataset;
    if (!dataset) return;
    els.sampleSelect.innerHTML = dataset.files.map((raw) => {
      const tail = raw.tail && raw.tail.secondFrames ? ` · 尾 ${raw.tail.secondFrames}` : '';
      const buy = raw.buyEvents && raw.buyEvents.length ? ` · BUY ${fmt(raw.buyEvents.length)}` : '';
      const skill = raw.skillEvents && raw.skillEvents.length ? ` · SKILL ${fmt(raw.skillEvents.length)}` : '';
      return `<option value="${esc(raw.name)}" title="${esc(raw.name)}">${esc(raw.label)} · CMD ${fmt(raw.commands.length)}${esc(buy)}${esc(skill)}${esc(tail)}</option>`;
    }).join('');
    els.sampleCount.textContent = `${dataset.files.length} 个样本`;
  }

  function loadFileByName(name, options = {}) {
    const raw = state.dataset && state.dataset.files.find((item) => item.name === name);
    if (!raw) return;
    const model = getModel(raw);
    state.file = model;
    state.minSeq = 0;
    state.maxSeq = model.maxSeq;
    state.filters.hidden.clear();
    state.filters.hero = 'all';
    state.filters.team = 'all';
    state.filters.search = '';
    state.filters.localOnly = false;
    if (els.search) els.search.value = '';
    if (els.teamFilter) els.teamFilter.value = 'all';
    if (els.localOnly) els.localOnly.checked = false;
    if (els.historyWindow) state.layers.historyWindow = num(els.historyWindow.value, 1800);

    let focus = options.entity != null && model.rosterByEntity.has(options.entity) ? options.entity : null;
    if (focus == null) {
      const local = Array.from(model.localEntities).find((entity) => model.rosterByEntity.has(entity));
      const withCommands = model.roster.find((player) => player.commandCount > 0);
      focus = local != null ? local : (withCommands ? withCommands.entity : (model.roster[0] ? model.roster[0].entity : null));
    }
    state.focusEntity = focus;
    let initialTime = model.firstCommandSeq != null ? model.firstCommandSeq : (model.minDataSeq || 0);
    if (focus != null) {
      const focusCommands = model.commandsByEntity.get(focus) || [];
      const firstFocusCommand = focusCommands.find((row) => !isCancelCommand(row));
      if (firstFocusCommand) initialTime = firstFocusCommand[0];
    }
    state.time = options.time != null
      ? clamp(options.time, state.minSeq, state.maxSeq)
      : initialTime;
    state.playing = false;
    setPlaying(false);
    state.timelineCache = null;
    state.mapHits = [];
    if (els.scrubber) {
      els.scrubber.min = '0';
      els.scrubber.max = String(state.maxSeq);
      els.scrubber.value = String(Math.floor(state.time));
    }
    els.sampleSelect.value = model.name;
    populateHeroFilter();
    renderSampleMeta();
    renderRoster();
    updateTimeUI();
    state.inspectorDirty = true;
    renderInspector(true);
    state.dirty = true;
  }

  function updateSourceBadge() {
    const dataset = state.dataset;
    if (!dataset) return;
    if (dataset.source === 'bundle') {
      const gzip = state.streamStatus && state.streamStatus.status === 'done' ? ` + gzip ${fmt(state.streamStatus.lines)}` : '';
      els.sourceBadge.textContent = `内置快照 · ${dataset.files.length} 样本${gzip}`;
      els.sourceBadge.classList.remove('is-folder', 'is-error');
    } else {
      const gzip = state.streamStatus && state.streamStatus.status === 'done' ? ` + gzip ${fmt(state.streamStatus.lines)}` : '';
      els.sourceBadge.textContent = dataset.label + gzip;
      els.sourceBadge.classList.add('is-folder');
      els.sourceBadge.classList.remove('is-error');
    }
    els.footerSource.textContent = dataset.source === 'bundle'
      ? `内置快照 ${dataset.generatedAt || ''}`.trim()
      : dataset.label;
  }

  function renderSourceList() {
    const dataset = state.dataset;
    if (!dataset) { els.sourceList.innerHTML = ''; return; }
    const lines = (dataset.sourceFiles || []).map((item) => {
      if (item.ok === false) return `<div class="miss">${esc(item.name)} · 未提供</div>`;
      const amount = item.rows != null ? `${fmt(item.rows)} 行` : formatBytes(item.bytes || 0);
      return `<div class="ok">${esc(item.name)} · ${esc(amount)}</div>`;
    });
    const counts = dataset.counts || {};
    lines.push(`<div>玩家 ${fmt(counts.players || 0)} · 命令 ${fmt(counts.commands || 0)} · 朝向 ${fmt(counts.headings || 0)} · 事件 ${fmt(counts.events || 0)}</div>`);
    lines.push(`<div>BUYEQUIP ${fmt(counts.buyEvents || 0)} · LEARNSKILL ${fmt(counts.skillEvents || 0)} · 购买汇总 ${fmt(counts.playerActions || 0)}</div>`);
    const index = dataset.eventStreamIndex || state.staticEventStreamIndex;
    if (index) {
      lines.push(`<div class="ok">R1 gzip 索引 · ${esc(index.name)} · ${fmt(index.lines)} 事件 / ${fmt((index.files || []).length)} 文件（浏览器解压，未内联）</div>`);
    }
    if (state.streamStatus) {
      const status = state.streamStatus;
      const cls = status.status === 'done' ? 'ok' : '';
      lines.push(`<div class="${cls}">gzip 加载 · ${esc(status.name || '')} · ${fmt(status.lines || 0)} 行${status.applied != null ? ` · 接入 ${fmt(status.applied)}` : ''}${status.unmatched ? ` · 未匹配 ${fmt(status.unmatched)}` : ''}${status.status === 'loading' ? ' · 读取中…' : ''}${status.error ? ` · ${esc(status.error)}` : ''}</div>`);
    }
    if (dataset.streamApplied) lines.push(`<div class="ok">JSONL 事件流 · 接入 ${fmt(dataset.streamApplied)} 条${dataset.streamUnmatched ? `（未匹配 ${fmt(dataset.streamUnmatched)}）` : ''}</div>`);
    if (dataset.generatedAt) lines.push(`<div>快照生成 ${esc(dataset.generatedAt)}</div>`);
    els.sourceList.innerHTML = lines.join('');
  }

  function renderSampleMeta() {
    const model = state.file;
    if (!model) {
      els.sampleMeta.innerHTML = '';
      els.sampleWarnings.innerHTML = '<div class="rr-warning is-info">请选择数据源</div>';
      return;
    }
    const tail = model.tail;
    const chips = [
      `玩家块 ${model.playerBlockCount}/10`,
      `名单 ${model.roster.length}`,
      `CMD ${fmt(model.commands.length)}`,
      `朝向 ${fmt(model.headings.length)}`,
      `事件 ${fmt(model.events.length)}`,
      model.buyEvents.length ? `BUY ${fmt(model.buyEvents.length)}` : '',
      model.skillEvents.length ? `SKILL ${fmt(model.skillEvents.length)}` : '',
      model.stream.length ? `流 ${fmt(model.stream.length)}` : '',
      tail && tail.secondFrames ? `尾部 ${fmt(tail.secondFrames)} 帧` : '无尾部帧',
    ].filter(Boolean);
    els.sampleMeta.innerHTML = chips.map((text) => `<span class="rr-chip">${esc(text)}</span>`).join('');

    const warnings = [];
    if (model.playerBlockCount < 10) {
      warnings.push(`玩家块仅 ${model.playerBlockCount}/10（可能漏检）；尾部名单补齐 ${model.roster.length} 个实体。`);
    }
    if (model.missingHero > 0) {
      warnings.push(`info:${model.missingHero} 个实体缺少英雄/皮肤映射（多为尾部补齐实体）。`);
    }
    if (model.commands.length && model.commandEntityCount < model.roster.length) {
      warnings.push(`坐标命令只覆盖 ${model.commandEntityCount}/${model.roster.length} 名选手；地图不补造其余位置。`);
    }
    if (!model.commands.length) warnings.push('该样本没有 0x2C 坐标命令。');
    if (!model.headings.length) warnings.push('无 0x2D 朝向样本（该段可能不是本地/被记录视角）。');
    if (model.synthetic) {
      warnings.push('info:该样本由 11/2 购买/加点 CSV 生成；没有坐标命令、朝向、队伍/分路数据，地图不补造位置。');
    }
    if (model.buyEvents.length) {
      warnings.push('info:BUYEQUIP 是购买/装备变化通知（含重复），去重标价和不是花费/收入；不展示 gold_event_total。');
    }
    if (model.stream.length) warnings.push(`info:已接入 ${fmt(model.stream.length)} 条 R1 事件流记录（BUYEQUIP / LEARNSKILL 已单独分类）。`);
    if (tail && tail.secondFrames) {
      warnings.push(`info:尾部第二段 ${tail.secondFrames} 帧（seq ${fmt(model.tailStart)}–${fmt(model.tailEnd)}）已并入时间轴。`);
    } else {
      warnings.push('info:该样本没有第二段帧流；尾部名单字段仍可查看。');
    }
    els.sampleWarnings.innerHTML = warnings.map((text) => {
      const info = text.startsWith('info:');
      return `<div class="rr-warning${info ? ' is-info' : ''}">${esc(info ? text.slice(5) : text)}</div>`;
    }).join('');
    els.mapSubtitle.textContent = model.synthetic
      ? `${model.label} · BUYEQUIP / LEARNSKILL 时间轴 · 该样本无坐标命令`
      : `${model.label} · 坐标目标点/瞄准点 · 仅画有 0x2C 命令的选手`;
  }

  // ---------------------------------------------------------------------------
  // lookup helpers
  // ---------------------------------------------------------------------------
  function lowerBound(rows, seq, index = 0) {
    let lo = 0;
    let hi = rows.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (rows[mid][index] < seq) lo = mid + 1; else hi = mid;
    }
    return lo;
  }
  function upperBound(rows, seq, index = 0) {
    let lo = 0;
    let hi = rows.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (rows[mid][index] <= seq) lo = mid + 1; else hi = mid;
    }
    return lo;
  }
  function latestDrawableCommand(entity, frame) {
    if (!state.file) return null;
    const rows = state.file.commandsByEntity.get(entity);
    if (!rows || !rows.length) return null;
    let index = upperBound(rows, frame) - 1;
    while (index >= 0) {
      if (!isCancelCommand(rows[index])) return rows[index];
      index--;
    }
    return null;
  }
  function latestHeading(entity, frame) {
    if (!state.file) return null;
    const rows = state.file.headingsByEntity.get(entity);
    if (!rows || !rows.length) return null;
    const index = upperBound(rows, frame) - 1;
    return index >= 0 ? rows[index] : null;
  }
  function latestStream(entity, frame) {
    if (!state.file) return null;
    const rows = state.file.streamByEntity.get(entity);
    if (!rows || !rows.length) return null;
    const index = upperBound(rows, frame) - 1;
    return index >= 0 ? rows[index] : null;
  }
  function playerLabel(entity) {
    const player = state.file && state.file.rosterByEntity.get(entity);
    if (player) return player.name;
    const streamName = state.file && state.file.raw.streamHeroNames && state.file.raw.streamHeroNames[entity];
    return streamName || (entity ? `#${entity}` : '全局/未知');
  }
  function playerOf(entity) {
    return state.file ? state.file.rosterByEntity.get(entity) : null;
  }

  // ---------------------------------------------------------------------------
  // map rendering
  // ---------------------------------------------------------------------------
  function drawMap() {
    const canvas = els.map;
    if (!canvas || !state.file) return;
    const w = state.mapSize.w || canvas.clientWidth || 800;
    const h = state.mapSize.h || canvas.clientHeight || 500;
    if (!w || !h) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const pixelW = Math.round(w * dpr);
    const pixelH = Math.round(h * dpr);
    if (canvas.width !== pixelW || canvas.height !== pixelH) {
      canvas.width = pixelW;
      canvas.height = pixelH;
    }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const pad = 24;
    const scale = Math.min((w - pad * 2) / (WORLD_HALF * 2), (h - pad * 2) / (WORLD_HALF * 2));
    const cx = w / 2;
    const cy = h / 2;
    const geometry = { w, h, pad, scale, cx, cy };
    state.mapGeom = geometry;
    const sx = (x) => cx + x * scale;
    const sy = (y) => cy - y * scale;

    drawMapBackdrop(ctx, geometry);

    const frame = Math.floor(state.time);
    const visible = visibleEntitySet();
    const historyWindow = state.layers.historyWindow;
    const hits = [];
    let historyCount = 0;
    let streamCount = 0;

    if (state.layers.history) {
      const grouped = new Map();
      state.file.commands.forEach((row) => {
        if (!visible.has(row[1]) || isCancelCommand(row) || row[0] > frame) return;
        if (historyWindow > 0 && row[0] < frame - historyWindow) return;
        const meta = commandMeta(row[3]);
        const key = meta.key;
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(row);
      });
      grouped.forEach((rows, key) => {
        const meta = CMD_META[Object.keys(CMD_META).find((type) => CMD_META[type].key === key) || 0x0300] || commandMeta(0x0300);
        rows.forEach((row) => {
          historyCount++;
          const age = frame - row[0];
          const windowSpan = historyWindow > 0 ? historyWindow : Math.max(1, frame - state.minSeq);
          const alpha = 0.10 + 0.48 * (1 - clamp(age / windowSpan, 0, 1));
          ctx.globalAlpha = alpha;
          ctx.fillStyle = meta.color;
          const radius = meta.key === 'cancel' ? 1.3 : 2.1;
          ctx.beginPath();
          ctx.arc(sx(row[5]), sy(row[6]), radius, 0, Math.PI * 2);
          ctx.fill();
        });
      });
      ctx.globalAlpha = 1;
    }

    const latest = [];
    state.file.roster.forEach((player) => {
      if (!visible.has(player.entity)) return;
      const row = latestDrawableCommand(player.entity, frame);
      if (!row) return;
      latest.push({ player, row, x: sx(row[5]), y: sy(row[6]), age: frame - row[0] });
    });

    // R1 event points (aim / point commands only; moves are not positions) are
    // drawn as diamonds, separate from 0x2C commands and bounded by the window.
    const pointLimit = 3000;
    (state.file.streamPoints || []).forEach((row) => {
      if (streamCount >= pointLimit) return;
      if (!visible.has(row[1]) || row[0] > frame) return;
      if (historyWindow > 0 && row[0] < frame - historyWindow) return;
      if (row[3] == null || row[4] == null) return;
      streamCount++;
      const x = sx(row[3]);
      const y = sy(row[4]);
      ctx.save();
      ctx.globalAlpha = 0.75;
      ctx.fillStyle = '#e879f9';
      ctx.translate(x, y);
      ctx.rotate(Math.PI / 4);
      ctx.fillRect(-2.6, -2.6, 5.2, 5.2);
      ctx.restore();
    });

    const labelCandidates = [];
    latest.forEach((item) => {
      const selected = item.player.entity === state.focusEntity;
      const age = item.age;
      const old = state.layers.historyWindow > 0 && age > state.layers.historyWindow;
      const meta = commandMeta(item.row[3]);

      if (selected) {
        const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 260);
        ctx.save();
        ctx.globalAlpha = 0.30 + 0.18 * pulse;
        ctx.strokeStyle = item.player.color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(item.x, item.y, 12 + pulse * 5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }

      ctx.save();
      ctx.globalAlpha = old ? 0.55 : 0.95;
      ctx.strokeStyle = item.player.color;
      ctx.lineWidth = selected ? 2 : 1.2;
      ctx.setLineDash(old ? [3, 3] : []);
      ctx.beginPath();
      ctx.arc(item.x, item.y, selected ? 7 : 5.2, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = meta.color;
      ctx.beginPath();
      ctx.arc(item.x, item.y, 2.8, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      hits.push({
        sx: item.x, sy: item.y, entity: item.player.entity, player: item.player,
        row: item.row, meta, age, radius: 12,
      });

      if (state.layers.labels) {
        labelCandidates.push({
          x: item.x, y: item.y, player: item.player, row: item.row, meta, age, old, selected,
        });
      }
    });

    if (state.layers.heading) {
      latest.forEach((item) => {
        const heading = latestHeading(item.player.entity, frame);
        if (!heading) return;
        const age = frame - heading[0];
        if (age > 300) return;
        drawHeadingArrow(ctx, item.x, item.y, heading[3], item.player.color, age, item.player.entity === state.focusEntity);
      });
    }

    if (state.layers.events) {
      const events = collectNearEvents(frame, 12, new Set(['skill', 'state']), visible, false);
      const seen = new Set();
      events.forEach((entry) => {
        if (seen.has(entry.entity)) return;
        seen.add(entry.entity);
        const item = latest.find((candidate) => candidate.player.entity === entry.entity);
        if (!item || item.age > 600) return;
        const meta = EVENT_META[entry.cat];
        const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 300 + entry.entity);
        ctx.save();
        ctx.globalAlpha = 0.35 + 0.35 * pulse;
        ctx.strokeStyle = meta.color;
        ctx.setLineDash([2, 2]);
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(item.x, item.y, 11 + pulse * 5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      });
    }

    if (state.layers.labels && labelCandidates.length) {
      labelCandidates.sort((a, b) => Number(a.selected) - Number(b.selected));
      drawMapLabels(ctx, geometry, labelCandidates);
    }

    // hit test
    state.mapHits = hits;
    let hovered = null;
    if (state.mouse.inside) {
      let best = Infinity;
      hits.forEach((hit) => {
        const distance = Math.hypot(hit.sx - state.mouse.x, hit.sy - state.mouse.y);
        if (distance < hit.radius && distance < best) { best = distance; hovered = hit; }
      });
      state.mouse.hit = hovered;
      canvas.style.cursor = hovered ? 'pointer' : 'default';
      if (hovered) drawMapTooltip(ctx, geometry, hovered);
    } else {
      state.mouse.hit = null;
      canvas.style.cursor = 'default';
    }

    state.mapStats = { commands: historyCount, visible: visible.size, stream: streamCount };
    els.mapVisible.textContent = `${visible.size} 人`;
    els.mapCmds.textContent = `${fmt(latest.length)} 目标 · ${fmt(historyCount)} 残影${streamCount ? ` · 流 ${fmt(streamCount)}` : ''}`;

    const showEmpty = latest.length === 0 && streamCount === 0;
    els.mapEmpty.hidden = !showEmpty;
    if (showEmpty) {
      const title = els.mapEmpty.querySelector('strong');
      const hint = els.mapEmpty.querySelector('span');
      if (!state.file.commands.length) {
        title.textContent = '该样本没有 0x2C 坐标命令';
        hint.textContent = '仍可查看名单、朝向和事件时间轴。';
      } else {
        title.textContent = '当前时点 / 筛选下没有可画命令';
        hint.textContent = '播放到有命令的帧段，或放宽选手筛选。';
      }
    }
  }

  function drawMapBackdrop(ctx, g) {
    const { w, h, pad, scale, cx, cy } = g;
    const sx = (x) => cx + x * scale;
    const sy = (y) => cy - y * scale;
    const left = sx(-WORLD_HALF);
    const right = sx(WORLD_HALF);
    const top = sy(WORLD_HALF);
    const bottom = sy(-WORLD_HALF);

    const background = ctx.createRadialGradient(cx, cy, 10, cx, cy, Math.max(w, h) * 0.7);
    background.addColorStop(0, 'rgba(15, 30, 49, .75)');
    background.addColorStop(0.62, 'rgba(8, 18, 31, .85)');
    background.addColorStop(1, 'rgba(5, 10, 18, .96)');
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, w, h);

    if (state.layers.map) {
      // lanes
      const lane = (points, width) => {
        ctx.beginPath();
        points.forEach(([x, y], index) => {
          const px = sx(x);
          const py = sy(y);
          if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        });
        ctx.lineWidth = width;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.stroke();
      };
      ctx.strokeStyle = 'rgba(97, 143, 200, .07)';
      lane([[-42000, -42000], [-42000, 42000], [42000, 42000]], Math.max(7, 10000 * scale));
      lane([[-42000, -42000], [42000, -42000], [42000, 42000]], Math.max(7, 10000 * scale));
      lane([[-42000, -42000], [42000, 42000]], Math.max(7, 10000 * scale));
      ctx.strokeStyle = 'rgba(138, 180, 235, .15)';
      ctx.setLineDash([5, 7]);
      lane([[-42000, -42000], [-42000, 42000], [42000, 42000]], 1.1);
      lane([[-42000, -42000], [42000, -42000], [42000, 42000]], 1.1);
      ctx.setLineDash([]);
      lane([[-42000, -42000], [42000, 42000]], 1.4);

      // river band on x + y = 0
      const riverA = [-WORLD_HALF, WORLD_HALF];
      const riverB = [WORLD_HALF, -WORLD_HALF];
      const dx = riverB[0] - riverA[0];
      const dy = riverB[1] - riverA[1];
      const length = Math.hypot(dx, dy);
      const halfWidth = 6200;
      const nx = (-dy / length) * halfWidth;
      const ny = (dx / length) * halfWidth;
      ctx.beginPath();
      ctx.moveTo(sx(riverA[0] + nx), sy(riverA[1] + ny));
      ctx.lineTo(sx(riverB[0] + nx), sy(riverB[1] + ny));
      ctx.lineTo(sx(riverB[0] - nx), sy(riverB[1] - ny));
      ctx.lineTo(sx(riverA[0] - nx), sy(riverA[1] - ny));
      ctx.closePath();
      const riverGradient = ctx.createLinearGradient(sx(riverA[0]), sy(riverA[1]), sx(riverB[0]), sy(riverB[1]));
      riverGradient.addColorStop(0, 'rgba(52, 130, 208, .10)');
      riverGradient.addColorStop(0.5, 'rgba(64, 156, 235, .16)');
      riverGradient.addColorStop(1, 'rgba(52, 130, 208, .10)');
      ctx.fillStyle = riverGradient;
      ctx.fill();
      ctx.strokeStyle = 'rgba(81, 170, 250, .20)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(sx(riverA[0] + nx), sy(riverA[1] + ny));
      ctx.lineTo(sx(riverB[0] + nx), sy(riverB[1] + ny));
      ctx.moveTo(sx(riverA[0] - nx), sy(riverA[1] - ny));
      ctx.lineTo(sx(riverB[0] - nx), sy(riverB[1] - ny));
      ctx.stroke();

      // bases
      drawBase(ctx, sx(-42000), sy(-42000), 7600 * scale, '#4ea1ff', 'TEAM 1');
      drawBase(ctx, sx(42000), sy(42000), 7600 * scale, '#ff6f82', 'TEAM 2');

      // objective pits
      drawObjective(ctx, sx(-14000), sy(14000), 3600 * scale);
      drawObjective(ctx, sx(14000), sy(-14000), 3600 * scale);

      ctx.save();
      ctx.fillStyle = 'rgba(160, 190, 225, .35)';
      ctx.font = '9px Consolas, monospace';
      ctx.fillText('示意地图 · 非游戏实景', left + 8, bottom - 9);
      ctx.restore();
    }

    // grid + border
    ctx.save();
    ctx.strokeStyle = 'rgba(126, 164, 220, .075)';
    ctx.lineWidth = 1;
    for (let x = -50000; x <= 50000; x += 10000) {
      ctx.beginPath();
      ctx.moveTo(sx(x), top);
      ctx.lineTo(sx(x), bottom);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(left, sy(x));
      ctx.lineTo(right, sy(x));
      ctx.stroke();
    }
    ctx.strokeStyle = 'rgba(126, 164, 220, .22)';
    ctx.strokeRect(left, top, right - left, bottom - top);
    ctx.fillStyle = 'rgba(150, 183, 220, .35)';
    ctx.font = '8.5px Consolas, monospace';
    ctx.fillText('+55k', right - 30, top + 12);
    ctx.fillText('-55k', left + 4, bottom - 5);
    ctx.fillText('0', sx(0) + 3, sy(0) - 4);
    ctx.restore();
  }

  function drawBase(ctx, x, y, radius, color, label) {
    ctx.save();
    ctx.globalAlpha = 0.75;
    const glow = ctx.createRadialGradient(x, y, 1, x, y, Math.max(radius, 22));
    glow.addColorStop(0, color + '55');
    glow.addColorStop(1, color + '00');
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(x, y, Math.max(radius, 22), 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = color + '88';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.arc(x, y, Math.max(radius * 0.55, 12), 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = color + 'cc';
    ctx.font = '8px Consolas, monospace';
    ctx.textAlign = 'center';
    ctx.fillText(label, x, y + Math.max(radius * 0.55, 12) + 11);
    ctx.restore();
  }

  function drawObjective(ctx, x, y, radius) {
    ctx.save();
    ctx.globalAlpha = 0.5;
    ctx.strokeStyle = 'rgba(244, 201, 93, .5)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y, Math.max(radius * 0.45, 8), 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, Math.max(radius * 0.45, 8) + 3, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  function drawHeadingArrow(ctx, x, y, degree, color, age, selected) {
    const radians = (degree * Math.PI) / 180;
    const length = selected ? 40 : 32;
    const endX = x + Math.sin(radians) * length;
    const endY = y - Math.cos(radians) * length;
    ctx.save();
    ctx.globalAlpha = age > 120 ? 0.5 : 0.9;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = selected ? 1.8 : 1.2;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(endX, endY);
    ctx.stroke();
    ctx.setLineDash([]);
    const angle = Math.atan2(endY - y, endX - x);
    ctx.beginPath();
    ctx.moveTo(endX, endY);
    ctx.lineTo(endX - Math.cos(angle - 0.45) * 7, endY - Math.sin(angle - 0.45) * 7);
    ctx.lineTo(endX - Math.cos(angle + 0.45) * 7, endY - Math.sin(angle + 0.45) * 7);
    ctx.closePath();
    ctx.fill();
    ctx.font = '8.5px Consolas, monospace';
    ctx.fillStyle = 'rgba(220, 235, 252, .8)';
    ctx.fillText(`${degree}°`, endX + 4, endY - 3);
    ctx.restore();
  }

  function drawMapLabels(ctx, g, candidates) {
    const occupied = [];
    candidates.forEach((candidate) => {
      const name = truncate(candidate.player.name, 10);
      const hero = candidate.player.heroName || '英雄未解析';
      const delta = candidate.age === 0 ? '同帧' : `Δ${fmt(candidate.age)}`;
      const line1 = `${name}`;
      const line2 = `${hero} · ${delta}`;
      ctx.font = '10px "Microsoft YaHei", "PingFang SC", sans-serif';
      const width1 = ctx.measureText(line1).width;
      ctx.font = '8.5px Consolas, monospace';
      const width2 = ctx.measureText(line2).width;
      const boxW = Math.max(width1, width2) + 14;
      const boxH = 29;
      const offsets = [[10, -34], [10, 8], [-boxW - 10, -34], [-boxW - 10, 8], [0, -boxH - 12], [0, 12]];
      let box = null;
      for (const [ox, oy] of offsets) {
        const bx = clamp(candidate.x + ox, 4, g.w - boxW - 4);
        const by = clamp(candidate.y + oy, 4, g.h - boxH - 4);
        const rect = { x: bx, y: by, w: boxW, h: boxH };
        if (!occupied.some((other) => intersects(rect, other))) { box = rect; break; }
      }
      if (!box) return;
      occupied.push(box);
      ctx.save();
      ctx.strokeStyle = candidate.selected ? '#9ed8ff' : 'rgba(126, 164, 220, .35)';
      ctx.lineWidth = candidate.selected ? 1.4 : 1;
      ctx.fillStyle = candidate.selected ? 'rgba(17, 35, 58, .94)' : 'rgba(6, 13, 24, .88)';
      roundRect(ctx, box.x, box.y, box.w, box.h, 6);
      ctx.fill();
      ctx.stroke();
      ctx.strokeStyle = candidate.player.color;
      ctx.globalAlpha = 0.75;
      ctx.beginPath();
      ctx.moveTo(candidate.x, candidate.y);
      ctx.lineTo(box.x + (candidate.x < box.x ? 0 : box.w), box.y + box.h / 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.textBaseline = 'top';
      ctx.font = '10px "Microsoft YaHei", "PingFang SC", sans-serif';
      ctx.fillStyle = candidate.selected ? '#e8f5ff' : candidate.player.color;
      ctx.fillText(line1, box.x + 7, box.y + 5);
      ctx.font = '8.5px Consolas, monospace';
      ctx.fillStyle = 'rgba(158, 184, 214, .82)';
      ctx.fillText(line2, box.x + 7, box.y + 17);
      ctx.restore();
    });
  }

  function intersects(a, b) {
    return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
  }

  function roundRect(ctx, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
    ctx.lineTo(x + radius, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
  }

  function drawMapTooltip(ctx, g, hit) {
    const lines = [
      `${hit.player.name} · ${hit.player.heroName || '英雄未解析'}`,
      `${hit.meta.label} ${hexLabel(hit.row[3])} · 帧 ${fmt(hit.row[0])} · Δ${fmt(hit.age)}`,
      `x ${fmt(hit.row[5])} / y ${fmt(hit.row[6])}`,
    ];
    ctx.save();
    ctx.font = '9.5px Consolas, monospace';
    const width = Math.max(...lines.map((line) => ctx.measureText(line).width)) + 18;
    const height = 50;
    const x = clamp(state.mouse.x + 14, 5, g.w - width - 5);
    const y = clamp(state.mouse.y - height - 10, 5, g.h - height - 5);
    ctx.fillStyle = 'rgba(5, 11, 20, .95)';
    ctx.strokeStyle = 'rgba(126, 164, 220, .45)';
    ctx.lineWidth = 1;
    roundRect(ctx, x, y, width, height, 6);
    ctx.fill();
    ctx.stroke();
    ctx.textBaseline = 'top';
    ctx.fillStyle = hit.player.color;
    ctx.font = '10px "Microsoft YaHei", "PingFang SC", sans-serif';
    ctx.fillText(lines[0], x + 9, y + 6);
    ctx.font = '9px Consolas, monospace';
    ctx.fillStyle = 'rgba(180, 205, 232, .9)';
    ctx.fillText(lines[1], x + 9, y + 20);
    ctx.fillStyle = 'rgba(145, 170, 200, .85)';
    ctx.fillText(lines[2], x + 9, y + 33);
    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // timeline rendering
  // ---------------------------------------------------------------------------
  function timelineGeometry(w, h) {
    const padL = 38;
    const padR = 14;
    const padT = 18;
    const padB = 24;
    return {
      w, h, padL, padR, padT, padB,
      plotW: Math.max(40, w - padL - padR),
      plotH: Math.max(40, h - padT - padB),
      min: state.minSeq,
      max: state.maxSeq,
    };
  }
  function seqToX(seq, g) {
    return g.padL + ((seq - g.min) / ((g.max - g.min) || 1)) * g.plotW;
  }
  function xToSeq(x, g) {
    return g.min + ((x - g.padL) / (g.plotW || 1)) * (g.max - g.min);
  }

  function buildTimelineCache(g) {
    const binCount = Math.max(80, Math.round(g.plotW / 2));
    const counts = {};
    TIMELINE_CATS.forEach((cat) => { counts[cat] = new Uint32Array(binCount); });
    const file = state.file;
    const add = (seq, cat) => {
      if (seq < g.min || seq > g.max) return;
      const index = clamp(Math.floor(((seq - g.min) / ((g.max - g.min) || 1)) * (binCount - 1)), 0, binCount - 1);
      const target = counts[cat] || counts.other;
      target[index]++;
    };
    file.events.forEach((row) => add(row[0], eventCategory(row)));
    file.stream.forEach((row) => add(row[0], streamCategory(row)));
    const headings = new Uint32Array(binCount);
    file.headings.forEach((row) => {
      if (row[0] < g.min || row[0] > g.max) return;
      const index = clamp(Math.floor(((row[0] - g.min) / ((g.max - g.min) || 1)) * (binCount - 1)), 0, binCount - 1);
      headings[index]++;
    });
    const maxes = {};
    TIMELINE_CATS.forEach((cat) => {
      let max = 0;
      counts[cat].forEach((value) => { if (value > max) max = value; });
      maxes[cat] = max;
    });
    let headingMax = 0;
    headings.forEach((value) => { if (value > headingMax) headingMax = value; });
    return { key: `${state.file.name}|${Math.round(g.w)}|${Math.round(g.h)}|${file.events.length}|${file.stream.length}|${file.headings.length}`, g, binCount, counts, maxes, headings, headingMax };
  }

  function drawTimeline() {
    const canvas = els.timeline;
    if (!canvas || !state.file) return;
    const w = state.timelineSize.w || canvas.clientWidth || 800;
    const h = state.timelineSize.h || canvas.clientHeight || 126;
    if (!w || !h) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const pixelW = Math.round(w * dpr);
    const pixelH = Math.round(h * dpr);
    if (canvas.width !== pixelW || canvas.height !== pixelH) {
      canvas.width = pixelW;
      canvas.height = pixelH;
    }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const g = timelineGeometry(w, h);
    if (!state.timelineCache || state.timelineCache.key !== `${state.file.name}|${Math.round(w)}|${Math.round(h)}|${state.file.events.length}|${state.file.stream.length}|${state.file.headings.length}`) {
      state.timelineCache = buildTimelineCache(g);
    }
    const cache = state.timelineCache;
    const sx = (seq) => seqToX(seq, g);

    const bg = ctx.createLinearGradient(0, 0, 0, h);
    bg.addColorStop(0, 'rgba(13, 24, 40, .6)');
    bg.addColorStop(1, 'rgba(7, 13, 23, .85)');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);

    // nice axis ticks
    const step = niceStep(g.max - g.min, 8);
    ctx.save();
    ctx.font = '8.5px Consolas, monospace';
    ctx.textBaseline = 'top';
    for (let seq = Math.ceil(g.min / step) * step; seq <= g.max + 1; seq += step) {
      const x = sx(seq);
      ctx.strokeStyle = 'rgba(126, 164, 220, .08)';
      ctx.beginPath();
      ctx.moveTo(x, g.padT);
      ctx.lineTo(x, g.padT + g.plotH);
      ctx.stroke();
      ctx.fillStyle = 'rgba(139, 163, 193, .65)';
      ctx.fillText(fmt(seq), x - 12, g.padT + g.plotH + 6);
    }
    ctx.restore();

    // tail band
    if (state.file.tailStart != null) {
      const x0 = sx(state.file.tailStart);
      const x1 = sx(state.file.tailEnd);
      ctx.save();
      ctx.fillStyle = 'rgba(242, 167, 255, .09)';
      ctx.fillRect(x0, g.padT, Math.max(1, x1 - x0), g.plotH);
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = 'rgba(242, 167, 255, .55)';
      ctx.beginPath();
      ctx.moveTo(x0, g.padT);
      ctx.lineTo(x0, g.padT + g.plotH);
      ctx.moveTo(x1, g.padT);
      ctx.lineTo(x1, g.padT + g.plotH);
      ctx.stroke();
      ctx.setLineDash([]);
      const label = `尾部 ${state.file.tail.secondFrames} 帧`;
      ctx.font = '9px Consolas, monospace';
      const labelWidth = ctx.measureText(label).width + 12;
      const labelX = clamp((x0 + x1) / 2 - labelWidth / 2, g.padL, w - g.padR - labelWidth);
      ctx.fillStyle = 'rgba(34, 15, 39, .9)';
      ctx.strokeStyle = 'rgba(242, 167, 255, .35)';
      roundRect(ctx, labelX, 2, labelWidth, 14, 4);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = 'rgba(248, 204, 255, .95)';
      ctx.textBaseline = 'top';
      ctx.fillText(label, labelX + 6, 5);
      ctx.restore();
    }

    // command ticks
    const visible = visibleEntitySet();
    ctx.save();
    state.file.commands.forEach((row) => {
      if (row[0] < g.min || row[0] > g.max) return;
      const meta = commandMeta(row[3]);
      const emphasis = visible.has(row[1]) ? 0.9 : 0.28;
      ctx.globalAlpha = isCancelCommand(row) ? emphasis * 0.4 : emphasis;
      ctx.fillStyle = meta.color;
      const x = sx(row[0]);
      ctx.fillRect(x, g.padT + 1, 1, 8);
    });
    ctx.restore();
    ctx.save();
    ctx.font = '8px Consolas, monospace';
    ctx.fillStyle = 'rgba(126, 164, 220, .55)';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillText('CMD', g.padL - 5, g.padT + 1);
    ctx.restore();

    // event lanes
    const laneTop = g.padT + 13;
    const laneHeight = 7.2;
    const laneGap = 1.2;
    TIMELINE_CATS.forEach((cat, index) => {
      const y = laneTop + index * (laneHeight + laneGap);
      if (y + laneHeight > g.padT + g.plotH - 20) return;
      ctx.fillStyle = 'rgba(126, 164, 220, .035)';
      ctx.fillRect(g.padL, y, g.plotW, laneHeight);
      const max = cache.maxes[cat] || 0;
      if (!max) return;
      const meta = EVENT_META[cat];
      ctx.save();
      ctx.fillStyle = meta.color;
      const binWidth = g.plotW / cache.binCount;
      for (let i = 0; i < cache.binCount; i++) {
        const value = cache.counts[cat][i];
        if (!value) continue;
        const height = Math.max(1, (value / max) * laneHeight);
        ctx.globalAlpha = 0.55;
        ctx.fillRect(g.padL + i * binWidth, y + laneHeight - height, Math.max(1, binWidth + 0.3), height);
      }
      ctx.restore();
      ctx.save();
      ctx.font = '7.5px Consolas, monospace';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = meta.color;
      ctx.globalAlpha = 0.8;
      ctx.fillText(meta.short, g.padL - 5, y + laneHeight / 2);
      ctx.restore();
    });

    // heading density
    const headY = laneTop + TIMELINE_CATS.length * (laneHeight + laneGap) + 2;
    if (headY + 9 < g.padT + g.plotH) {
      ctx.save();
      ctx.fillStyle = 'rgba(126, 164, 220, .035)';
      ctx.fillRect(g.padL, headY, g.plotW, 9);
      if (cache.headingMax) {
        ctx.strokeStyle = 'rgba(142, 231, 194, .55)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        const binWidth = g.plotW / cache.binCount;
        for (let i = 0; i < cache.binCount; i++) {
          const value = cache.headings[i];
          const height = (value / cache.headingMax) * 8;
          const x = g.padL + i * binWidth;
          const y = headY + 9 - height;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      ctx.font = '7.5px Consolas, monospace';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = 'rgba(142, 231, 194, .7)';
      ctx.fillText('2d', g.padL - 5, headY + 5);
      ctx.restore();
    }

    // hover line
    if (state.timelineHoverSeq != null) {
      const hx = sx(state.timelineHoverSeq);
      ctx.save();
      ctx.strokeStyle = 'rgba(220, 235, 252, .28)';
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(hx, g.padT);
      ctx.lineTo(hx, g.padT + g.plotH);
      ctx.stroke();
      ctx.restore();
    }

    // cursor
    const cx = sx(clamp(state.time, g.min, g.max));
    ctx.save();
    ctx.strokeStyle = 'rgba(98, 182, 255, .95)';
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    ctx.moveTo(cx, g.padT);
    ctx.lineTo(cx, g.padT + g.plotH);
    ctx.stroke();
    ctx.fillStyle = '#62b6ff';
    ctx.beginPath();
    ctx.moveTo(cx - 4, g.padT - 5);
    ctx.lineTo(cx + 4, g.padT - 5);
    ctx.lineTo(cx, g.padT + 2);
    ctx.closePath();
    ctx.fill();
    const frame = Math.floor(state.time);
    const bubble = `${fmt(frame)}`;
    ctx.font = '8.5px Consolas, monospace';
    const bw = ctx.measureText(bubble).width + 10;
    const bx = clamp(cx - bw / 2, g.padL, w - g.padR - bw);
    ctx.fillStyle = 'rgba(9, 21, 37, .94)';
    ctx.strokeStyle = 'rgba(98, 182, 255, .45)';
    roundRect(ctx, bx, 3, bw, 13, 4);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = 'rgba(200, 230, 255, .95)';
    ctx.textBaseline = 'top';
    ctx.textAlign = 'left';
    ctx.fillText(bubble, bx + 5, 5);
    ctx.restore();

    state.timelineGeom = g;
  }

  function niceStep(span, target) {
    const raw = span / Math.max(1, target);
    const power = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    const normalized = raw / power;
    const multiplier = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
    return Math.max(1, multiplier * power);
  }

  // ---------------------------------------------------------------------------
  // inspector
  // ---------------------------------------------------------------------------
  function renderInspector(force = false) {
    if (!els.inspectorBody) return;
    const now = performance.now();
    if (!force && !state.inspectorDirty) return;
    // The buy tab does not depend on the playhead; avoid re-rendering it every
    // 180 ms while playing. Tab switches, focus changes and explicit actions
    // pass force=true.
    if (!force && state.tab === 'buy') { state.inspectorDirty = false; return; }
    if (!force && now - state.lastInspectorAt < 180) return;
    state.lastInspectorAt = now;
    state.inspectorDirty = false;
    const scroll = els.inspectorBody.scrollTop;
    let html = '';
    if (!state.file) html = '<div class="rr-empty">尚未载入数据</div>';
    else if (state.tab === 'events') html = renderEventsTab();
    else if (state.tab === 'buy') html = renderBuyTab();
    else if (state.tab === 'commands') html = renderCommandsTab();
    else if (state.tab === 'tail') html = renderTailTab();
    else html = renderNowTab();
    els.inspectorBody.innerHTML = html;
    els.inspectorBody.scrollTop = scroll;
  }

  function renderNowTab() {
    const model = state.file;
    if (!model) return '';
    const frame = Math.floor(state.time);
    const visible = visibleEntitySet();
    const inWindow = countCommandsInWindow(visible, frame);
    const nearbyEvents = collectNearEvents(frame, 120, null, visible, false).length;
    const focus = state.focusEntity != null ? model.rosterByEntity.get(state.focusEntity) : null;
    const stats = [
      [fmt(inWindow), '窗口内命令'],
      [fmt(nearbyEvents), '±120 帧事件'],
      [fmt(visible.size), '可见选手'],
      [model.tailStart != null ? '是' : '否', '尾部第二段'],
    ];
    let html = `<section class="rr-section">
      <div class="rr-section-title">当前时点 <span class="rr-muted">帧 ${fmt(frame)} · ${fmtClock(frame)}</span></div>
      <div class="rr-stat-grid">${stats.map(([value, label]) => `<div class="rr-stat"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join('')}</div>
    </section>`;

    if (focus) {
      const local = focus.isLocal ? '<span class="rr-tag rr-tag-skill">LOCAL</span>' : '';
      const rating = focus.rating != null ? Number(focus.rating).toFixed(2) : '—';
      const cmd = latestDrawableCommand(focus.entity, frame);
      const heading = latestHeading(focus.entity, frame);
      const cmdText = cmd
        ? `${commandMeta(cmd[3]).label} ${hexLabel(cmd[3])} · 帧 ${fmt(cmd[0])} · Δ${fmt(frame - cmd[0])}`
        : '当前时点之前无坐标命令';
      const headingText = heading
        ? `${heading[3]}° · 帧 ${fmt(heading[0])} · Δ${fmt(frame - heading[0])}`
        : '无朝向样本';
      const tailValue = focus.tailValue != null ? `${(focus.tailValue / 100).toFixed(2)}（原始 ${fmt(focus.tailValue)}）` : '—';
      const purchase = model.purchaseByEntity.get(focus.entity);
      const buyUnique = purchase ? purchase.items.size : 0;
      const buySpend = purchase ? purchase.spendLowerBound : 0;
      const learnCount = purchase ? purchase.learnEvents : 0;
      html += `<section class="rr-section">
        <div class="rr-section-title">聚焦选手 <span class="rr-muted">#${focus.entity}</span></div>
        <div class="rr-player-card team-${focus.team || 0}">
          <h3>${esc(focus.name)} ${local}</h3>
          <div class="rr-player-hero">${esc(focus.heroName || '英雄未解析')}${focus.skinName ? ` · ${esc(focus.skinName)}` : ''}</div>
          <div class="rr-player-meta">entity #${focus.entity} · team ${focus.team || '?'} / slot ${focus.slot == null ? '?' : focus.slot} · rating ${esc(rating)}</div>
          <div class="rr-player-note">${esc(cmdText)}<br>${esc(headingText)}</div>
          <dl class="rr-kv" style="margin-top:7px">
            <dt>命令 / 朝向 / 事件 / 流</dt><dd>${fmt(focus.commandCount)} / ${fmt(focus.headingCount)} / ${fmt(focus.eventCount)} / ${fmt(focus.streamCount)}</dd>
            <dt>BUYEQUIP 去重 / 标价和</dt><dd>${purchase ? `${fmt(buyUnique)} 件 / ${fmt(buySpend)} 金（unique 标价和，不是花费/收入）` : '—'}</dd>
            <dt>LEARNSKILL / 尾部值</dt><dd>${purchase ? `${fmt(learnCount)} 次` : '—'} / ${esc(tailValue)}</dd>
          </dl>
        </div>
      </section>`;
    } else {
      html += `<section class="rr-section"><div class="rr-empty">未选中选手；从名单或地图点选。</div></section>`;
    }

    html += `<section class="rr-section">
      <div class="rr-section-title">可见选手最新目标 <span class="rr-muted">${visible.size} 人</span></div>
      <div class="rr-list">${renderLatestTargetRows(frame, visible)}</div>
    </section>`;

    html += `<section class="rr-section">
      <div class="rr-info-box">地图上的点 = 0x2C 命令目标/瞄准点，不是连续位置；R1 事件流只画瞄准/点类事件，不画 move 位置。BUYEQUIP 是购买/装备变化，不是金币收入；unique 标价和不是花费。不展示 gold_event_total。</div>
    </section>`;
    return html;
  }

  function renderLatestTargetRows(frame, visible) {
    const rows = [];
    state.file.roster.forEach((player) => {
      if (!visible.has(player.entity)) return;
      const row = latestDrawableCommand(player.entity, frame);
      if (!row) {
        rows.push(`<div class="rr-row"><span class="rr-row-seq">—</span><span class="rr-row-main"><span class="rr-row-title">${esc(player.name)} · ${esc(player.heroName || '英雄未解析')}</span><span class="rr-row-sub">当前时点前无命令</span></span><span class="rr-row-right">—</span></div>`);
        return;
      }
      const meta = commandMeta(row[3]);
      const delta = frame - row[0];
      rows.push(`<div class="rr-row${player.entity === state.focusEntity ? ' is-current' : ''}" data-seq="${row[0]}" data-entity="${player.entity}" tabindex="0">
        <span class="rr-row-seq">${fmt(row[0])}</span>
        <span class="rr-row-main">
          <span class="rr-row-title">${esc(player.name)} · ${esc(player.heroName || '英雄未解析')}</span>
          <span class="rr-row-sub"><span class="rr-tag ${meta.cls}">${esc(meta.short)}</span> ${hexLabel(row[3])} · x ${fmt(row[5])}, y ${fmt(row[6])}</span>
        </span>
        <span class="rr-row-right">${delta === 0 ? '同帧' : `Δ${fmt(delta)}`}</span>
      </div>`);
    });
    return rows.join('') || '<div class="rr-empty">没有可见选手</div>';
  }

  function countCommandsInWindow(visible, frame) {
    const window = state.layers.historyWindow;
    let count = 0;
    state.file.commands.forEach((row) => {
      if (!visible.has(row[1]) || isCancelCommand(row) || row[0] > frame) return;
      if (window > 0 && row[0] < frame - window) return;
      count++;
    });
    return count;
  }

  function renderEventsTab() {
    const model = state.file;
    const frame = Math.floor(state.time);
    const visible = visibleEntitySet();
    const chips = EVENT_CHIPS.map((key) => {
      const meta = EVENT_META[key];
      const count = model.eventCategoryCounts[key] || 0;
      return `<button type="button" class="rr-filter-chip${state.filters.eventCats.has(key) ? ' is-on' : ''}" data-event-cat="${key}">${esc(meta.label)} ${fmt(count)}</button>`;
    }).join('');
    const events = collectNearEvents(frame, 240, null, visible, state.filters.eventFocusOnly);
    const rows = events.slice(0, 300).map((entry) => {
      if (entry.kind === 'stream') {
        const row = entry.row;
        const meta = EVENT_META[entry.cat] || EVENT_META.stream;
        return `<div class="rr-row${row[0] === frame ? ' is-current' : ''}" data-seq="${row[0]}" data-entity="${row[1] || ''}" tabindex="0">
          <span class="rr-row-seq">${fmt(row[0])}</span>
          <span class="rr-row-main"><span class="rr-row-title"><span class="rr-tag ${meta.cls}">${esc(meta.short)}</span> ${esc(playerLabel(row[1]))}</span><span class="rr-row-sub">${esc(streamDetail(row))}</span></span>
          <span class="rr-row-right">${entry.delta === 0 ? '同帧' : `Δ${fmt(entry.delta)}`}</span>
        </div>`;
      }
      const row = entry.row;
      const meta = EVENT_META[entry.cat];
      return `<div class="rr-row${row[0] === frame ? ' is-current' : ''}" data-seq="${row[0]}" data-entity="${row[1] || ''}" tabindex="0">
        <span class="rr-row-seq">${fmt(row[0])}</span>
        <span class="rr-row-main"><span class="rr-row-title"><span class="rr-tag ${meta.cls}">${esc(meta.label)}</span> ${esc(playerLabel(row[1]))}</span><span class="rr-row-sub">${esc(eventDetail(row))}</span></span>
        <span class="rr-row-right">${entry.delta === 0 ? '同帧' : `Δ${fmt(entry.delta)}`}</span>
      </div>`;
    }).join('');
    return `<section class="rr-section">
      <div class="rr-section-title">事件筛选 <span class="rr-muted">±240 帧 · ${fmt(events.length)} 条</span></div>
      <div class="rr-filter-chips">${chips}</div>
      <label class="rr-check"><input type="checkbox" data-opt="eventFocusOnly" ${state.filters.eventFocusOnly ? 'checked' : ''}> 仅聚焦选手</label>
      <div class="rr-info-box">BUYEQUIP 是按帧的购买/装备变化通知（含重复），去重标价和只能当参考，不是花费/收入/余额；不展示 gold_event_total。LEARNSKILL 是技能加点。R1 的 move/beacon 等事件保留原始 kind，默认不在地图画位置；旧 gzip 里的 <code>death_candidate</code> 标签已撤回（0x81=USEDIRECTIONALSKILL），不表示死亡。beacon 0x03 数量大，可能需要关掉“R1 其他事件”。</div>
    </section>
    <div class="rr-list">${rows || '<div class="rr-empty">当前时点附近没有符合筛选的事件</div>'}</div>`;
  }

  function renderScreenshotCheck(model) {
    const checks = (state.dataset && state.dataset.screenshotChecks && state.dataset.screenshotChecks.length)
      ? state.dataset.screenshotChecks
      : (state.staticScreenshotChecks || []);
    const check = checks.find((item) => item.matchedFile === model.name
      || (item.identity && item.identity.matchedFile === model.name));
    if (!check) {
      if (!model.synthetic) return '';
      return `<section class="rr-section"><div class="rr-info-box">截图对拍：该样本没有对应截图目录或未匹配，结论为“截图不可用 / 未对拍”。</div></section>`;
    }
    const identity = check.identity || {};
    const ocr = check.ocr || {};
    const match = ocr.match || {};
    const equipment = check.equipment || {};
    const gold = check.goldAnalysis || {};
    const manual = check.equipmentManual || {};
    const priceBook = (state.dataset && state.dataset.equipPrices) || state.staticEquipPrices || {};
    const costOf = (entry) => {
      let cost = 0, known = 0, unknown = 0;
      (entry.items || []).forEach((item) => {
        const price = priceBook[String(item.itemId)];
        if (price && Number(price.buy)) { cost += Number(price.buy); known++; }
        else unknown++;
      });
      return { cost, known, unknown };
    };
    const score = match.score ? `${match.score.left == null ? '?' : match.score.left}:${match.score.right == null ? '?' : match.score.right}` : '—';
    const duration = match.durationSec ? `${Math.floor(match.durationSec / 60)}:${String(match.durationSec % 60).padStart(2, '0')}` : '—';
    const maxSim = equipment.maxSimilarity == null ? '—' : Number(equipment.maxSimilarity).toFixed(3);
    const resultText = equipment.result === 'unverified' ? '自动全库匹配未完成（unverified）'
      : equipment.result === 'partial' ? '自动全库匹配部分候选（仍需人工复核）' : '截图不可用 / 未对拍';
    const manualByPlayer = new Map(((manual && manual.players) || []).map((item) => [item.csvPlayer, item]));
    const costPlayers = ((manual && manual.players) || []).map((entry) => {
      const stats = costOf(entry);
      const panelGold = entry.panel && entry.panel.gold != null ? Number(entry.panel.gold) : null;
      const complete = entry.visible === 6 && entry.identified === 6 && stats.known === 6 && stats.unknown === 0;
      return {
        entry, stats, panelGold, complete,
        residual: panelGold == null ? null : panelGold - stats.cost,
      };
    });
    const completeCosts = costPlayers.filter((row) => row.complete).map((row) => row.stats.cost);
    const covers = costPlayers.filter((row) => row.residual != null && row.residual > 0).length;
    const minResidual = costPlayers.reduce((min, row) => row.residual == null ? min : Math.min(min, row.residual), Infinity);
    const rows = (identity.players || []).map((player) => {
      const side = player.side === 'left' ? '蓝' : player.side === 'right' ? '红' : '?';
      const name = player.csvPlayer || player.nickname || '—';
      const ocrName = player.nickname && player.csvPlayer && player.nickname !== player.csvPlayer
        ? `OCR ${player.nickname}` : '';
      const rating = player.rating == null ? '—' : Number(player.rating).toFixed(1);
      const panel = player.panel || {};
      const panelGold = panel.gold == null ? '—' : `${fmt(panel.gold)} 金`;
      const manualEntry = manualByPlayer.get(player.csvPlayer) || {};
      const manualText = manualEntry.visible
        ? `${fmt(manualEntry.identified)}/${fmt(manualEntry.visible)} 可辨`
        : '未对拍';
      const stats = costOf(manualEntry);
      const costText = stats.known ? `${fmt(stats.cost)} 金` : '—';
      const costSub = stats.known ? `已知 ${fmt(stats.known)} 格${stats.unknown ? ` · ${fmt(stats.unknown)} 未知` : ''}` : '无价格';
      const residual = panel.gold == null ? null : Number(panel.gold) - stats.cost;
      const residualText = residual == null ? '—' : `${residual > 0 ? '+' : ''}${fmt(residual)} ${residual > 0 ? '✅' : '❌'}`;
      return `<tr>
        <td class="mono">${esc(side)}${player.slot == null ? '?' : player.slot + 1}</td>
        <td>${esc(name)}<br><span class="rr-muted">${esc(panel.kda || '—')} · 评分 ${esc(rating)}${ocrName ? ` · ${esc(ocrName)}` : ''}</span></td>
        <td class="mono">${esc(panelGold)}</td>
        <td class="mono">${esc(costText)}<br><span class="rr-muted">${esc(costSub)}</span></td>
        <td class="mono">${esc(residualText)}</td>
        <td>${esc(manualText)}</td>
      </tr>`;
    }).join('');
    const manualDetails = ((manual && manual.players) || []).map((player) => {
      const items = (player.items || []).map((item) => `<tr>
        <td class="mono">${item.slot}</td>
        <td>${esc(item.name || '—')}</td>
        <td class="mono">${item.itemId ? esc(item.itemId) : '—'}</td>
        <td>${esc(item.confidence || '—')}</td>
        <td>${item.inBuySet === true ? '在 BUY 集合' : item.inBuySet === false ? '不在 BUY 集合' : '未知'}</td>
      </tr>`).join('');
      return `<details class="rr-details"><summary>${esc(player.csvPlayer || '—')} · ${fmt(player.identified || 0)}/${fmt(player.visible || 0)} 可辨 · 高置信 ${fmt(player.highConfidence || 0)}</summary>
        <div class="rr-muted">${esc(player.note || '')}</div>
        <table class="rr-tail-table"><thead><tr><th>格</th><th>人工判读</th><th>ID</th><th>置信</th><th>BUY 集合</th></tr></thead><tbody>${items}</tbody></table>
      </details>`;
    }).join('');
    return `<section class="rr-section">
      <div class="rr-section-title">截图对拍 <span class="rr-muted">人工 / OCR</span></div>
      <div class="rr-info-box">
        <div>截图：<code>${esc(check.image || '—')}</code> · ${esc(ocr.pageType || '未知页面')} · ${esc(match.date || '')} ${esc(match.time || '')} · 比分 ${esc(score)} · 时长 ${esc(duration)}</div>
        <div>OCR 同局：昵称 ${fmt(identity.nameHits || 0)}/${fmt(identity.ocrPlayers || 0)}（含模糊）、英雄 ${fmt(identity.heroHits || 0)}/${fmt(identity.ocrPlayers || 0)}、评分 ${fmt(identity.ratingHits || 0)}/${fmt(identity.ocrPlayers || 0)}。</div>
        <div>自动全库图标匹配：<strong>${esc(resultText)}</strong> · ${fmt(equipment.reliable || 0)}/${fmt(equipment.regions || 0)} 格达到 ${esc(String(equipment.threshold == null ? 0.94 : equipment.threshold))} 阈值 · 最高相似度 ${esc(maxSim)}。</div>
        <div>人工逐格对拍：${esc(manual.verdict || '截图装备不可用 / 未对拍')}</div>
        <div>${esc(equipment.reason || '')}</div>
      </div>
      <div class="rr-note-box"><strong>最终 6 件对拍：</strong>面板累计金币合计 ${esc(String(gold.panelGoldTotal == null ? '—' : fmt(gold.panelGoldTotal)))} 金；${fmt(completeCosts.length)} 名玩家 6/6 完整识别，最终装备成本 ${completeCosts.length ? `${fmt(Math.min(...completeCosts))}–${fmt(Math.max(...completeCosts))}` : '—'} 金；${fmt(covers)}/${fmt(costPlayers.length)} 人满足 <code>成本 &lt; 面板</code>，最低 ${esc(Number.isFinite(minResidual) ? `${minResidual > 0 ? '+' : ''}${fmt(minResidual)}` : '—')}。面板已含初始 300；玩家不可能把金币花到 0、装备价是整数，所以不加 300，也不把“差 2g”当校准。翳灵崽 4 格成本 6,130 &gt; 面板 5,828（−302g），是唯一异常，需查装备 ID/价格/面板读数或未记录的出售。<br>BUYEQUIP 去重标价和合计 ${esc(String(gold.buyUniqueSumTotal == null ? '—' : fmt(gold.buyUniqueSumTotal)))} 金，${fmt(gold.buySumGreaterCount || 0)}/${fmt(gold.playersCompared || 0)} 人大于面板；因为集合同时含合成件+成品+重复通知，不能当花费。${esc(gold.note || '')}<br>面板金币是赛后累计金币，不是当前余额；本页不展示 <code>gold_event_total</code>，不推断收入。</div>
      <div class="rr-note-box">截图只有装备图标、没有名称/ID 文本；自动全库匹配不可靠，人工结果已标注 high/medium/low。可辨认图标全部落在各自 BUYEQUIP 去重集合内，未发现面板装备超出购买集合；低置信格保留未知，不编造 equip_id。最终装备成本只累加已识别且有买价的格子，缺失格不补造；因此它是一致性检查（9/10 通过，296 异常），不是逐笔购买账本。</div>
      ${rows ? `<table class="rr-tail-table"><thead><tr><th>#</th><th>选手 / KDA</th><th>面板累计金币</th><th>最终装备成本</th><th>面板−成本</th><th>图标对拍</th></tr></thead><tbody>${rows}</tbody></table>` : ''}
      ${manualDetails}
    </section>`;
  }

  function renderBuyTab() {
    const model = state.file;
    if (!model) return '';
    const totals = { raw: 0, unique: 0, spend: 0, unknown: 0, learn: 0 };
    model.purchaseByEntity.forEach((entry) => {
      totals.raw += entry.rawNotifications;
      totals.unique += entry.items.size;
      totals.spend += entry.spendLowerBound;
      totals.unknown += entry.unknownPriceItems;
      totals.learn += entry.learnEvents;
    });
    let html = `<section class="rr-section">
      <div class="rr-section-title">购买 / 加点 <span class="rr-muted">BUYEQUIP · LEARNSKILL</span></div>
      <div class="rr-stat-grid">
        <div class="rr-stat"><b>${fmt(totals.raw)}</b><span>BUYEQUIP 通知</span></div>
        <div class="rr-stat"><b>${fmt(totals.unique)}</b><span>去重装备</span></div>
        <div class="rr-stat"><b>${fmt(totals.spend)}</b><span>去重标价和（不可当花费）</span></div>
        <div class="rr-stat"><b>${fmt(totals.learn)}</b><span>LEARNSKILL</span></div>
      </div>
      <div class="rr-note-box"><strong>BUYEQUIP 是购买/装备变化通知，不是金币收入，也不是逐笔花费账本。</strong> 购买通知含重复（同一玩家同一装备可能多帧重复），这里按 <code>(entity, equip_id)</code> 去重；去重集合同时含合成件与成品，所以标价和 10–15k 大于面板金币 5–9k，不能直接当累计花费。可对拍的是截图里的最终 6 格装备成本（见上方“最终 6 件对拍”）：5 名 6/6 完整识别玩家成本 6,175–9,130，全部严格小于面板累计金币；9/10 满足 <code>成本 &lt; 面板</code>。翳灵崽 4 格 6,130 &gt; 面板 5,828（−302g）是异常，需查装备 ID/价格/面板读数或出售，不能加 300 掩盖。面板金币是赛后累计金币（含初始 300），不是当前余额。本页不展示 <code>gold_event_total</code>，不推断收入/余额；卖出、合成与后续金币变化未还原。</div>
      ${totals.unknown ? `<div class="rr-warning">${fmt(totals.unknown)} 件装备未在价格表命中，按 0 计入去重标价和（不是花费）。</div>` : ''}
    </section>`;
    html += renderScreenshotCheck(model);

    const playerRows = [];
    model.roster.forEach((player) => {
      const entry = model.purchaseByEntity.get(player.entity);
      const official = (model.actions || []).find((row) => row[0] === player.entity);
      if (!entry && !official) return;
      const items = entry ? Array.from(entry.items.values()).sort((a, b) => a.firstFrame - b.firstFrame) : [];
      const learnRows = entry ? entry.learnRows.slice().sort((a, b) => a[0] - b[0]) : [];
      const itemRows = items.map((item) => `<tr>
        <td class="mono">${fmt(item.firstFrame)}</td>
        <td>${esc(item.name || '装备未识别')}</td>
        <td class="mono">${item.itemId == null ? '—' : item.itemId}</td>
        <td class="mono">${item.price ? `${fmt(item.price)} 金` : '未命中'}</td>
        <td class="mono">${fmt(item.notifications)}</td>
      </tr>`).join('');
      const learnText = learnRows.map((row) => `帧 ${fmt(row[0])} · 技能 ${row[2] == null ? '?' : row[2]} → ${row[3] == null ? '?' : row[3] + 1} 级`).join(' / ');
      playerRows.push(`<details class="rr-details"${player.entity === state.focusEntity ? ' open' : ''}>
        <summary><strong>${esc(player.name)}</strong> · ${esc(player.heroName || '英雄未解析')} · BUY ${fmt(items.length)} 件 · 去重标价和 ${fmt(entry ? entry.spendLowerBound : 0)} 金 · SKILL ${fmt(entry ? entry.learnEvents : 0)}</summary>
        ${official ? `<div class="rr-info-box">player_actions 汇总：raw BUYEQUIP ${fmt(official[4])}（含重复） · unique ${fmt(official[5])} · unique_equip_price_sum_unverified ${fmt(official[6])}（未验证标价和，不是累计花费/收入） · LEARNSKILL ${fmt(official[8])} · slots ${esc(official[9] || '—')} · score ${esc(official[3])} · move/attack ${fmt(official[10])}/${fmt(official[11])}（unit 高 5 位 → 槽位；文件总量 ${fmt(official[15])}/${fmt(official[16])}）</div>` : ''}
        ${itemRows ? `<table class="rr-tail-table"><thead><tr><th>首次帧</th><th>装备</th><th>ID</th><th>buy_price</th><th>通知</th></tr></thead><tbody>${itemRows}</tbody></table>` : '<div class="rr-empty">无 BUYEQUIP 记录</div>'}
        ${learnText ? `<div class="rr-muted" style="margin-top:5px">LEARNSKILL：${esc(learnText)}</div>` : ''}
      </details>`);
    });
    html += `<section class="rr-section">
      <div class="rr-section-title">按选手购买集合 <span class="rr-muted">去重 · 标价和（非花费）</span></div>
      <div class="rr-list">${playerRows.join('') || '<div class="rr-empty">该样本没有 BUYEQUIP / LEARNSKILL 记录</div>'}</div>
    </section>`;
    html += `<section class="rr-section"><div class="rr-info-box">帧号与回放 seq 一致（30 fps 仅为显示估算）。BUYEQUIP 的 <code>buy_price</code> 来自 <code>agent_equip_prices.csv</code> 的 battle_item；未命中价格按 0 计。去重标价和只是参考，不是累计花费、当前金币或收入；最终 6 格成本才是与面板对拍的量。</div></section>`;
    return html;
  }

  function renderCommandsTab() {
    const model = state.file;
    const frame = Math.floor(state.time);
    const visible = visibleEntitySet();
    const chips = COMMAND_CHIPS.map((key) => {
      const meta = key === 'cancel'
        ? { label: '取消', color: '#6b7a90' }
        : (Object.values(CMD_META).find((item) => item.key === key) || { label: key });
      const count = model.commandCategoryCounts[key] || 0;
      return `<button type="button" class="rr-filter-chip${state.filters.commandCats.has(key) ? ' is-on' : ''}" data-command-cat="${key}">${esc(meta.label)} ${fmt(count)}</button>`;
    }).join('');
    const commands = collectNearCommands(frame, 600, visible, state.filters.commandFocusOnly);
    const rows = commands.slice(0, 300).map((entry) => {
      const row = entry.row;
      const meta = entry.meta;
      const cancel = isCancelCommand(row);
      return `<div class="rr-row${row[0] === frame ? ' is-current' : ''}" data-seq="${row[0]}" data-entity="${row[1]}" tabindex="0">
        <span class="rr-row-seq">${fmt(row[0])}</span>
        <span class="rr-row-main"><span class="rr-row-title"><span class="rr-tag ${meta.cls}">${esc(meta.short)}</span> ${esc(playerLabel(row[1]))}</span><span class="rr-row-sub">${hexLabel(row[3])} · ${cancel ? '取消命令（不画点）' : `x ${fmt(row[5])}, y ${fmt(row[6])}`} · id ${fmt(row[4])}</span></span>
        <span class="rr-row-right">${entry.delta === 0 ? '同帧' : `Δ${fmt(entry.delta)}`}</span>
      </div>`;
    }).join('');
    return `<section class="rr-section">
      <div class="rr-section-title">命令筛选 <span class="rr-muted">±600 帧 · ${fmt(commands.length)} 条</span></div>
      <div class="rr-filter-chips">${chips}</div>
      <label class="rr-check"><input type="checkbox" data-opt="commandFocusOnly" ${state.filters.commandFocusOnly ? 'checked' : ''}> 仅聚焦选手</label>
      <div class="rr-info-box">取消命令（type 以 01 结尾 / x=y=0）只在列表出现，不在地图上画点；坐标是目标点，不是位置。</div>
    </section>
    <div class="rr-list">${rows || '<div class="rr-empty">当前时点附近没有符合筛选的命令</div>'}</div>`;
  }

  function renderTailTab() {
    const model = state.file;
    const tail = model.tail;
    let html = '';
    if (tail && tail.secondFrames) {
      html += `<section class="rr-section">
        <div class="rr-section-title">尾部第二段 <span class="rr-muted">${fmt(tail.secondFrames)} 帧</span></div>
        <div class="rr-stat-grid">
          <div class="rr-stat"><b>${fmt(model.tailStart)}–${fmt(model.tailEnd)}</b><span>seq 区间</span></div>
          <div class="rr-stat"><b>${fmt(model.tailCounts.commands)}</b><span>尾部命令</span></div>
          <div class="rr-stat"><b>${fmt(model.tailCounts.headings)}</b><span>尾部朝向</span></div>
          <div class="rr-stat"><b>${fmt(model.tailCounts.events)}</b><span>尾部事件</span></div>
        </div>
        <div class="rr-inline-actions" style="margin-top:8px">
          <button type="button" class="rr-button rr-button-small" data-action="tail-start">跳到尾部起点</button>
          <button type="button" class="rr-button rr-button-small" data-action="tail-end">跳到尾部终点</button>
        </div>
        <div class="rr-info-box">尾部是输入续流，不是状态快照；seq 与主段分开，已加 segment=1 标记。</div>
      </section>`;
    } else {
      html += `<section class="rr-section"><div class="rr-empty">该样本没有第二段 712 帧帧流</div></section>`;
    }

    html += `<section class="rr-section">
      <div class="rr-section-title">尾部名单 / 评分候选 <span class="rr-muted">${fmt(model.tailRoster.length)} 对</span></div>
      ${renderTailTable(model)}
      <div class="rr-note-box"><strong>字段名与语义：</strong><code>hero_skin_pairs</code> 的第二个值在 R1 复核中更像 rating×100，而不是 skin ID（如 1110 = 11.10）。本页把原始值单独列出，实际皮肤名来自 <code>agent_skin_ids.csv</code> 的 <code>derived_name</code>。</div>
    </section>`;

    if (tail) {
      html += `<section class="rr-section">
        <div class="rr-section-title">原始尾部字段</div>
        <dl class="rr-kv">
          <dt>last_main_seq</dt><dd class="mono">${fmt(tail.lastMainSeq)}</dd>
          <dt>second_frames</dt><dd class="mono">${fmt(tail.secondFrames)}</dd>
          <dt>tail_bytes</dt><dd class="mono">${fmt(tail.tailBytes)}</dd>
          <dt>footer_bytes</dt><dd class="mono">${fmt(tail.footerBytes)}</dd>
          <dt>footer_extra</dt><dd class="mono">${fmt(tail.footerExtra)}</dd>
          <dt>local_slot</dt><dd class="mono">${tail.localSlot == null ? '—' : fmt(tail.localSlot)}</dd>
          <dt>local_hero</dt><dd class="mono">${tail.localHero == null ? '—' : fmt(tail.localHero)}</dd>
        </dl>
        <details class="rr-details"><summary>展开原始 values / pairs</summary><pre class="rr-raw">${esc(tail.values || '')}\n${esc(tail.rawPairs || '')}</pre></details>
        <div class="rr-note-box">local_slot / local_hero 是尾部原始字段，可能与 is_local 推断不一致；这里只作证据展示，不当成本地玩家结论。</div>
      </section>`;
    }
    return html;
  }

  function renderTailTable(model) {
    if (!model.tailRoster.length) return '<div class="rr-empty">没有尾部名单对</div>';
    const rows = model.tailRoster.map((item) => {
      const player = item.player || {};
      const badge = player.verdict === 'mvp' ? '<span class="rr-role-badge">MVP</span>'
        : player.verdict === 'svp' ? '<span class="rr-role-badge svp">SVP</span>' : '';
      const rowClass = player.verdict === 'mvp' ? ' class="is-mvp"' : player.verdict === 'svp' ? ' class="is-svp"' : '';
      return `<tr${rowClass}>
        <td class="mono">${item.index + 1}</td>
        <td class="mono">${item.entity}</td>
        <td>${esc(player.name || '未知选手')}<br><span class="rr-muted">${esc(player.heroName || '英雄未解析')}${player.skinName ? ` · ${esc(player.skinName)}` : ''}</span></td>
        <td class="mono">${fmt(item.rawValue)}</td>
        <td class="mono">${item.rating.toFixed(2)}</td>
        <td>${badge}</td>
      </tr>`;
    }).join('');
    return `<table class="rr-tail-table"><thead><tr><th>#</th><th>entity</th><th>选手 / 英雄 / 皮肤</th><th>尾部值</th><th>评分候选</th><th>标记</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function collectNearEvents(frame, delta, cats, visible, focusOnly) {
    const model = state.file;
    if (!model) return [];
    const allowed = cats || state.filters.eventCats;
    const out = [];
    const start = lowerBound(model.events, frame - delta);
    const end = upperBound(model.events, frame + delta);
    for (let i = start; i < end; i++) {
      const row = model.events[i];
      if (!visible.has(row[1]) && row[1] !== 0) continue;
      if (focusOnly && state.focusEntity != null && row[1] !== state.focusEntity) continue;
      const cat = eventCategory(row);
      if (!allowed.has(cat)) continue;
      out.push({ kind: 'event', row, entity: row[1], cat, delta: row[0] - frame });
    }
    const streamStart = lowerBound(model.stream, frame - delta);
    const streamEnd = upperBound(model.stream, frame + delta);
    for (let i = streamStart; i < streamEnd; i++) {
      const row = model.stream[i];
      if (!visible.has(row[1]) && row[1] !== 0) continue;
      if (focusOnly && state.focusEntity != null && row[1] !== state.focusEntity) continue;
      const cat = streamCategory(row);
      if (!allowed.has(cat)) continue;
      out.push({ kind: 'stream', row, entity: row[1], cat, delta: row[0] - frame });
    }
    out.sort((a, b) => (Math.abs(a.delta) - Math.abs(b.delta)) || (a.row[0] - b.row[0]));
    return out;
  }

  function collectNearCommands(frame, delta, visible, focusOnly) {
    const model = state.file;
    if (!model) return [];
    const out = [];
    const start = lowerBound(model.commands, frame - delta);
    const end = upperBound(model.commands, frame + delta);
    for (let i = start; i < end; i++) {
      const row = model.commands[i];
      if (!visible.has(row[1])) continue;
      if (focusOnly && state.focusEntity != null && row[1] !== state.focusEntity) continue;
      const meta = commandMeta(row[3]);
      if (!state.filters.commandCats.has(meta.key)) continue;
      out.push({ row, entity: row[1], meta, delta: row[0] - frame });
    }
    out.sort((a, b) => (Math.abs(a.delta) - Math.abs(b.delta)) || (a.row[0] - b.row[0]));
    return out;
  }

  // ---------------------------------------------------------------------------
  // events / interaction
  // ---------------------------------------------------------------------------
  function focusEntity(entity, options = {}) {
    if (entity == null) return;
    state.focusEntity = entity;
    state.filters.hidden.delete(entity);
    if (options.seek && options.seq != null) {
      setTime(options.seq, { pause: true });
    }
    renderRoster();
    state.dirty = true;
    state.inspectorDirty = true;
    renderInspector(true);
  }

  function bindEvents() {
    els.sampleSelect.addEventListener('change', () => {
      loadFileByName(els.sampleSelect.value);
    });

    els.search.addEventListener('input', () => {
      state.filters.search = els.search.value;
      clearTimeout(state.searchTimer);
      state.searchTimer = setTimeout(applyFilters, 110);
    });
    els.teamFilter.addEventListener('change', () => {
      state.filters.team = els.teamFilter.value;
      applyFilters();
    });
    els.heroFilter.addEventListener('change', () => {
      state.filters.hero = els.heroFilter.value;
      applyFilters();
    });
    els.localOnly.addEventListener('change', () => {
      state.filters.localOnly = els.localOnly.checked;
      applyFilters();
    });
    els.btnResetFilters.addEventListener('click', () => {
      state.filters.search = '';
      state.filters.team = 'all';
      state.filters.hero = 'all';
      state.filters.localOnly = false;
      state.filters.hidden.clear();
      state.filters.eventCats = new Set(DEFAULT_EVENT_CATS);
      state.filters.commandCats = new Set(['attack', 'skill', 'signal', 'unknown']);
      state.filters.eventFocusOnly = false;
      state.filters.commandFocusOnly = false;
      els.search.value = '';
      els.teamFilter.value = 'all';
      els.localOnly.checked = false;
      populateHeroFilter();
      applyFilters();
      toast('筛选已重置');
    });
    els.btnAllPlayers.addEventListener('click', () => {
      matchingRoster().forEach((player) => state.filters.hidden.delete(player.entity));
      applyFilters();
    });
    els.btnNonePlayers.addEventListener('click', () => {
      matchingRoster().forEach((player) => state.filters.hidden.add(player.entity));
      applyFilters();
    });

    els.rosterList.addEventListener('change', (event) => {
      const checkbox = event.target.closest('input[type="checkbox"]');
      if (!checkbox) return;
      const entity = Number(checkbox.dataset.entity);
      if (checkbox.checked) state.filters.hidden.delete(entity); else state.filters.hidden.add(entity);
      renderRoster();
      state.dirty = true;
      state.inspectorDirty = true;
      renderInspector();
    });
    els.rosterList.addEventListener('click', (event) => {
      if (event.target.closest('input[type="checkbox"]')) return;
      const row = event.target.closest('.rr-player');
      if (row) focusEntity(Number(row.dataset.entity));
    });
    els.rosterList.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      if (event.target.closest('input')) return;
      const row = event.target.closest('.rr-player');
      if (!row) return;
      event.preventDefault();
      focusEntity(Number(row.dataset.entity));
    });

    ['layer-history', 'layer-labels', 'layer-heading', 'layer-events', 'layer-map'].forEach((id) => {
      els[toCamel(id)].addEventListener('change', () => {
        state.layers[{
          'layer-history': 'history', 'layer-labels': 'labels', 'layer-heading': 'heading',
          'layer-events': 'events', 'layer-map': 'map',
        }[id]] = els[toCamel(id)].checked;
        state.dirty = true;
      });
    });
    els.historyWindow.addEventListener('change', () => {
      state.layers.historyWindow = num(els.historyWindow.value, 1800);
      state.dirty = true;
      state.inspectorDirty = true;
      renderInspector();
    });

    els.btnPlay.addEventListener('click', togglePlay);
    els.btnStepBack100.addEventListener('click', () => stepTime(-100));
    els.btnStepBack1.addEventListener('click', () => stepTime(-1));
    els.btnStepFwd1.addEventListener('click', () => stepTime(1));
    els.btnStepFwd100.addEventListener('click', () => stepTime(100));
    els.btnTail.addEventListener('click', jumpTail);
    els.speedSelect.addEventListener('change', () => { state.speed = Number(els.speedSelect.value) || 1; });
    els.loopToggle.addEventListener('change', () => { state.loop = els.loopToggle.checked; });

    els.scrubber.addEventListener('input', () => {
      setTime(Number(els.scrubber.value), { pause: true });
    });

    els.map.addEventListener('mousemove', (event) => {
      const rect = els.map.getBoundingClientRect();
      state.mouse.x = event.clientX - rect.left;
      state.mouse.y = event.clientY - rect.top;
      state.mouse.inside = true;
      state.dirty = true;
    });
    els.map.addEventListener('mouseleave', () => {
      state.mouse.inside = false;
      state.mouse.hit = null;
      state.dirty = true;
    });
    els.map.addEventListener('click', () => {
      if (state.mouse.hit) focusEntity(state.mouse.hit.entity);
    });

    els.timeline.addEventListener('pointerdown', (event) => {
      els.timeline.setPointerCapture(event.pointerId);
      state.timelineDragging = true;
      setTimeFromTimeline(event, true);
      updateTimelineHover(event);
    });
    els.timeline.addEventListener('pointermove', (event) => {
      updateTimelineHover(event);
      if (state.timelineDragging) setTimeFromTimeline(event, false);
    });
    els.timeline.addEventListener('pointerup', (event) => {
      state.timelineDragging = false;
      try { els.timeline.releasePointerCapture(event.pointerId); } catch (error) { /* noop */ }
    });
    els.timeline.addEventListener('pointercancel', () => { state.timelineDragging = false; });
    els.timeline.addEventListener('pointerleave', () => {
      if (!state.timelineDragging) {
        state.timelineHoverSeq = null;
        els.timelineTooltip.hidden = true;
        state.dirty = true;
      }
    });

    els.tabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        state.tab = tab.dataset.tab;
        els.tabs.forEach((item) => {
          const active = item === tab;
          item.classList.toggle('is-active', active);
          item.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        els.inspectorBody.scrollTop = 0;
        state.inspectorDirty = true;
        renderInspector(true);
      });
    });

    els.inspectorBody.addEventListener('click', (event) => {
      const action = event.target.closest('[data-action]');
      if (action) {
        if (action.dataset.action === 'tail-start') setTime(state.file.tailStart, { pause: true });
        if (action.dataset.action === 'tail-end') setTime(state.file.tailEnd, { pause: true });
        return;
      }
      const eventChip = event.target.closest('[data-event-cat]');
      if (eventChip) {
        toggleSetValue(state.filters.eventCats, eventChip.dataset.eventCat);
        state.inspectorDirty = true;
        renderInspector(true);
        return;
      }
      const commandChip = event.target.closest('[data-command-cat]');
      if (commandChip) {
        toggleSetValue(state.filters.commandCats, commandChip.dataset.commandCat);
        state.inspectorDirty = true;
        renderInspector(true);
        return;
      }
      const row = event.target.closest('[data-seq]');
      if (row) {
        const seq = Number(row.dataset.seq);
        const entity = row.dataset.entity != null && row.dataset.entity !== '' ? Number(row.dataset.entity) : null;
        setTime(seq, { pause: true });
        if (entity != null) focusEntity(entity);
      }
    });
    els.inspectorBody.addEventListener('change', (event) => {
      const option = event.target.closest('[data-opt]');
      if (!option) return;
      if (option.dataset.opt === 'eventFocusOnly') state.filters.eventFocusOnly = option.checked;
      if (option.dataset.opt === 'commandFocusOnly') state.filters.commandFocusOnly = option.checked;
      state.inspectorDirty = true;
      renderInspector(true);
    });

    document.addEventListener('keydown', (event) => {
      if (event.target.closest('input, select, textarea, button, a')) return;
      if (event.key === ' ') { event.preventDefault(); togglePlay(); return; }
      if (event.key === 'ArrowLeft') { event.preventDefault(); stepTime(event.shiftKey ? -100 : -1); return; }
      if (event.key === 'ArrowRight') { event.preventDefault(); stepTime(event.shiftKey ? 100 : 1); return; }
      if (event.key === 'Home') { event.preventDefault(); setTime(state.minSeq, { pause: true }); return; }
      if (event.key === 'End') { event.preventDefault(); setTime(state.maxSeq, { pause: true }); return; }
      if (event.key === 't' || event.key === 'T') { event.preventDefault(); jumpTail(); }
    });

    els.btnReload.addEventListener('click', () => {
      if (state.file) state.pendingSample = state.file.name;
      loadBundleDataset(true);
    });
    els.btnFolder.addEventListener('click', () => els.folderInput.click());
    els.folderInput.addEventListener('change', () => loadFolderFiles(els.folderInput.files));
    els.btnGzip.addEventListener('click', () => els.gzipInput.click());
    els.gzipInput.addEventListener('change', () => {
      const file = els.gzipInput.files && els.gzipInput.files[0];
      if (file) loadGzipStream(file, file.name);
      els.gzipInput.value = '';
    });
    els.btnPath.addEventListener('click', () => loadFromPath());

    const resize = new ResizeObserver((entries) => {
      entries.forEach((entry) => {
        const rect = entry.contentRect;
        if (entry.target.classList.contains('rr-map-wrap')) {
          state.mapSize = { w: rect.width, h: rect.height };
        } else {
          state.timelineSize = { w: rect.width, h: rect.height };
          state.timelineCache = null;
        }
      });
      state.dirty = true;
    });
    resize.observe(document.querySelector('.rr-map-wrap'));
    resize.observe(document.querySelector('.rr-timeline-wrap'));
    window.addEventListener('resize', () => { state.dirty = true; state.timelineCache = null; });
  }

  function toggleSetValue(set, value) {
    if (set.has(value)) set.delete(value); else set.add(value);
  }

  function updateTimelineHover(event) {
    if (!state.timelineGeom) return;
    const rect = els.timeline.getBoundingClientRect();
    const x = clamp(event.clientX - rect.left, state.timelineGeom.padL, state.timelineGeom.padL + state.timelineGeom.plotW);
    const seq = Math.round(xToSeq(x, state.timelineGeom));
    state.timelineHoverSeq = seq;
    const cache = state.timelineCache;
    let commandCount = 0;
    let eventCount = 0;
    if (cache) {
      const binCount = cache.binCount;
      const bin = clamp(Math.floor(((seq - state.minSeq) / ((state.maxSeq - state.minSeq) || 1)) * (binCount - 1)), 0, binCount - 1);
      for (let i = Math.max(0, bin - 1); i <= Math.min(binCount - 1, bin + 1); i++) {
        TIMELINE_CATS.forEach((cat) => { eventCount += cache.counts[cat][i]; });
      }
      const span = Math.max(1, state.maxSeq - state.minSeq);
      const delta = span / 500;
      const start = lowerBound(state.file.commands, seq - delta);
      const end = upperBound(state.file.commands, seq + delta);
      commandCount = end - start;
    }
    els.timelineTooltip.hidden = false;
    els.timelineTooltip.textContent = `帧 ${fmt(seq)} · ${fmtClock(seq)} · 命令 ${fmt(commandCount)} · 事件 ${fmt(eventCount)}`;
    const left = clamp(event.clientX - rect.left, 70, rect.width - 70);
    els.timelineTooltip.style.left = `${left}px`;
    els.timelineTooltip.style.top = `${Math.max(12, event.clientY - rect.top - 6)}px`;
    state.dirty = true;
  }

  function setTimeFromTimeline(event, pause) {
    if (!state.timelineGeom) return;
    const rect = els.timeline.getBoundingClientRect();
    const x = clamp(event.clientX - rect.left, state.timelineGeom.padL, state.timelineGeom.padL + state.timelineGeom.plotW);
    setTime(xToSeq(x, state.timelineGeom), { pause });
  }

  // ---------------------------------------------------------------------------
  // loading
  // ---------------------------------------------------------------------------
  function loadBundleDataset(announce = false) {
    try {
      const bundle = window.REPLAY_REVIEW_BUNDLE;
      if (!bundle || !Array.isArray(bundle.files)) throw new Error('未找到内置快照 replay-review-data.js');
      const dataset = buildDatasetFromBundle(bundle);
      state.pendingSample = state.pendingSample || null;
      setDataset(dataset);
      if (announce) toast(`已重载内置快照：${dataset.files.length} 个样本`);
    } catch (error) {
      els.sourceBadge.textContent = '内置快照不可用';
      els.sourceBadge.classList.add('is-error');
      toast(error.message || '内置快照加载失败', true, 8000);
    }
  }

  function supportsGzipStream() {
    return typeof DecompressionStream !== 'undefined';
  }

  async function readGzipJsonl(source, onRecord, onProgress) {
    if (!supportsGzipStream()) {
      throw new Error('当前浏览器不支持 DecompressionStream(gzip)；请使用新版 Chrome / Edge。');
    }
    const stream = source instanceof Response
      ? source.body
      : (source && typeof source.stream === 'function' ? source.stream() : null);
    if (!stream) throw new Error('无法读取 gzip 流');
    const decompressed = stream.pipeThrough(new DecompressionStream('gzip'));
    const textStream = typeof TextDecoderStream !== 'undefined' ? decompressed.pipeThrough(new TextDecoderStream()) : null;
    const reader = (textStream || decompressed).getReader();
    const decoder = textStream ? null : new TextDecoder();
    let buffer = '';
    let lines = 0;
    let lastReport = 0;
    const consume = (text) => {
      buffer += text;
      let index;
      while ((index = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, index);
        buffer = buffer.slice(index + 1);
        const trimmed = line.trim();
        if (!trimmed) continue;
        lines++;
        try { onRecord(JSON.parse(trimmed)); } catch (error) { onRecord(null); }
        if (onProgress && lines - lastReport >= 20000) {
          lastReport = lines;
          onProgress(lines);
        }
      }
    };
    try {
      for (;;) {
        const chunk = await reader.read();
        if (chunk.done) break;
        consume(decoder ? decoder.decode(chunk.value, { stream: true }) : chunk.value);
      }
      if (decoder) consume(decoder.decode());
      if (buffer.trim()) {
        lines++;
        try { onRecord(JSON.parse(buffer.trim())); } catch (error) { onRecord(null); }
      }
    } finally {
      try { reader.releaseLock(); } catch (error) { /* noop */ }
    }
    return lines;
  }

  async function loadGzipStream(source, label) {
    if (!state.dataset) {
      loadBundleDataset(false);
      if (!state.dataset) return false;
    }
    if (!supportsGzipStream()) {
      toast('当前浏览器不支持 DecompressionStream(gzip)；请用新版 Chrome/Edge，或先构建 bundle。', true, 8000);
      return false;
    }
    const rawMap = new Map(state.dataset.files.map((raw) => [raw.name, raw]));
    const keys = Array.from(rawMap.keys());
    const equipPrices = state.dataset.equipPrices || state.staticEquipPrices || {};
    const heroNames = state.dataset.heroNames || state.staticHeroNames || {};
    const beforeFiles = new Set(keys);
    const affected = new Set();
    let applied = 0;
    let unmatched = 0;
    let lines = 0;
    state.streamStatus = { status: 'loading', name: label, lines: 0, applied: 0, unmatched: 0 };
    renderSourceList();
    toast(`正在流式解压 ${label}…`, false, 12000);
    try {
      lines = await readGzipJsonl(source, (record) => {
        if (!record) { unmatched++; return; }
        const result = applyStreamRecord(rawMap, record, equipPrices, heroNames, keys);
        if (result.applied) {
          applied++;
          affected.add(result.file);
        } else {
          unmatched++;
        }
      }, (count) => {
        state.streamStatus.lines = count;
        state.streamStatus.applied = applied;
        state.streamStatus.unmatched = unmatched;
        renderSourceList();
        if (count % 100000 === 0) toast(`gzip 解压中：${fmt(count)} 条事件…`, false, 4000);
      });
    } catch (error) {
      state.streamStatus = {
        status: 'error', name: label, lines, applied, unmatched,
        error: error && error.message ? error.message : String(error),
      };
      renderSourceList();
      updateSourceBadge();
      toast(`gzip 读取失败：${state.streamStatus.error}`, true, 10000);
      return false;
    }

    affected.forEach((name) => {
      const raw = rawMap.get(name);
      if (raw) sortRaw(raw);
    });
    const newFiles = [];
    rawMap.forEach((raw, name) => { if (!beforeFiles.has(name)) newFiles.push(raw); });
    if (newFiles.length) {
      state.dataset.files.push(...newFiles);
      state.dataset.files.sort((a, b) => String(b.label).localeCompare(String(a.label)));
    }
    // update dataset-level counts without touching bundle CSVs
    const counts = state.dataset.counts || {};
    counts.files = state.dataset.files.length;
    counts.players = state.dataset.files.reduce((sum, raw) => sum + raw.players.length, 0);
    counts.stream = state.dataset.files.reduce((sum, raw) => sum + raw.stream.length, 0);
    counts.buyEvents = state.dataset.files.reduce((sum, raw) => sum + (raw.buyEvents || []).length, 0);
    counts.skillEvents = state.dataset.files.reduce((sum, raw) => sum + (raw.skillEvents || []).length, 0);
    state.dataset.counts = counts;
    state.streamStatus = { status: 'done', name: label, lines, applied, unmatched };
    state.dataset.streamStatus = state.streamStatus;
    renderSampleOptions();
    renderSourceList();
    affected.forEach((name) => state.modelCache.delete(name));
    newFiles.forEach((raw) => state.modelCache.delete(raw.name));

    const current = state.file ? state.file.name : null;
    if (current && rawMap.has(current)) {
      const raw = rawMap.get(current);
      const oldMax = state.maxSeq;
      state.file = getModel(raw);
      state.maxSeq = state.file.maxSeq;
      state.timelineCache = null;
      state.time = clamp(state.time, state.minSeq, state.maxSeq);
      if (state.focusEntity != null && !state.file.rosterByEntity.has(state.focusEntity)) {
        state.focusEntity = state.file.roster[0] ? state.file.roster[0].entity : null;
      }
      if (els.scrubber) {
        els.scrubber.max = String(state.maxSeq);
        els.scrubber.value = String(Math.floor(state.time));
      }
      populateHeroFilter();
      renderSampleMeta();
      renderRoster();
      updateTimeUI();
      state.inspectorDirty = true;
      state.lastInspectorAt = 0;
      renderInspector(true);
      state.dirty = true;
      const suffix = unmatched ? `，未匹配 ${fmt(unmatched)}` : '';
      toast(`gzip 已接入 ${fmt(lines)} 条（匹配 ${fmt(applied)}${suffix}）${oldMax !== state.maxSeq ? ` · 时间轴扩展到 ${fmt(state.maxSeq)} 帧` : ''}`, !!unmatched, 8000);
    } else {
      const suffix = unmatched ? `，未匹配 ${fmt(unmatched)}` : '';
      toast(`gzip 已接入 ${fmt(lines)} 条（匹配 ${fmt(applied)}${suffix}）`, !!unmatched, 8000);
    }
    updateSourceBadge();
    if (newFiles.length) toast(`gzip 新增 ${newFiles.length} 个仅事件流样本`, false, 6000);
    return true;
  }

  async function loadFolderFiles(fileList) {
    if (!fileList || !fileList.length) return;
    const wanted = new Set(DATASET_FILES.map((name) => name.toLowerCase()));
    const gzipWanted = new Set(GZIP_STREAM_FILES.map((name) => name.toLowerCase()));
    const texts = {};
    const tasks = [];
    let gzipFile = null;
    for (const file of Array.from(fileList)) {
      const name = String(file.name || '').toLowerCase();
      if (wanted.has(name)) {
        tasks.push(file.text().then((text) => { texts[name] = text; }));
      } else if (!gzipFile && gzipWanted.has(name)) {
        gzipFile = file;
      }
    }
    if (!tasks.length && !gzipFile) {
      els.folderInput.value = '';
      toast('文件夹里没有找到 replay_*.csv / 11-2 CSV / replay_event_stream_events.jsonl.gz', true, 7000);
      return;
    }
    try {
      if (tasks.length) {
        toast(`正在读取 ${tasks.length} 个数据文件…`, false, 8000);
        await Promise.all(tasks);
        const dataset = buildDatasetFromTexts(texts, 'folder', `文件夹 · ${tasks.length} 文件`);
        setDataset(dataset);
        toast(`已读取 ${tasks.length} 个文件：${dataset.files.length} 个样本`, false, 6000);
      } else if (state.dataset) {
        toast('仅发现 gzip 事件流；将接入当前数据集', false, 5000);
      }
      if (gzipFile) await loadGzipStream(gzipFile, gzipFile.name);
    } catch (error) {
      toast(error.message || '文件夹读取失败', true, 8000);
    } finally {
      els.folderInput.value = '';
    }
  }

  async function loadFromBase(base, source, label) {
    const texts = {};
    await Promise.all(DATASET_FILES.map(async (name) => {
      try {
        const response = await fetch(base + name, { cache: 'no-store' });
        if (response.ok) texts[name.toLowerCase()] = await response.text();
      } catch (error) { /* optional file */ }
    }));
    if (Object.keys(texts).length) {
      const dataset = buildDatasetFromTexts(texts, source, `${label} · ${Object.keys(texts).length} 文件`);
      setDataset(dataset);
      toast(`已从 ${label} 读取 ${Object.keys(texts).length} 个文件：${dataset.files.length} 个样本`, false, 6000);
    } else {
      toast(`未从 ${label} 读到 CSV；保留当前数据集`, true, 6000);
      if (!state.dataset) loadBundleDataset(false);
    }
    for (const name of GZIP_STREAM_FILES) {
      try {
        const response = await fetch(base + name, { cache: 'no-store' });
        if (response.ok) {
          await loadGzipStream(response, name);
          break;
        }
      } catch (error) { /* optional gzip */ }
    }
  }

  async function loadFromPath() {
    if (location.protocol === 'file:') {
      toast('file:// 页面不能 fetch 本地路径；请用“打开数据文件夹”或内置快照。', true, 7000);
      return;
    }
    const bases = [
      '../data/replays/_analysis/datasets/',
      'data/replays/_analysis/datasets/',
      './data/replays/_analysis/datasets/',
      '../../data/replays/_analysis/datasets/',
    ];
    let base = null;
    for (const candidate of bases) {
      for (const probe of ['replay_players.csv', '20261102_buy_events.csv', 'agent_equip_prices.csv']) {
        try {
          const response = await fetch(candidate + probe, { cache: 'no-store' });
          if (response.ok) { base = candidate; break; }
        } catch (error) { /* try next */ }
      }
      if (base) break;
    }
    if (!base) {
      toast('未找到 data/replays/_analysis/datasets/；请用“打开数据文件夹”。', true, 7000);
      return;
    }
    toast(`正在从 ${base} 读取 CSV 与 gzip 事件流…`, false, 8000);
    try {
      await loadFromBase(base, 'path', 'data/ 路径');
    } catch (error) {
      toast(error.message || 'data/ 路径读取失败', true, 8000);
    }
  }

  // ---------------------------------------------------------------------------
  // animation loop
  // ---------------------------------------------------------------------------
  function tick(timestamp) {
    if (!state.lastTs) state.lastTs = timestamp;
    const dt = Math.min(0.1, (timestamp - state.lastTs) / 1000);
    state.lastTs = timestamp;

    if (state.playing) {
      const next = state.time + dt * FPS_ASSUMED * state.speed;
      if (next >= state.maxSeq) {
        if (state.loop) {
          state.time = state.minSeq;
        } else {
          state.time = state.maxSeq;
          setPlaying(false);
        }
      } else {
        state.time = next;
      }
      updateTimeUI();
      state.dirty = true;
      state.inspectorDirty = true;
    }

    if (state.dirty && timestamp - state.lastRenderAt > 33) {
      drawMap();
      drawTimeline();
      state.lastRenderAt = timestamp;
      state.dirty = false;
    }
    if (state.inspectorDirty && timestamp - state.lastInspectorAt > 180) {
      renderInspector();
    }
    requestAnimationFrame(tick);
  }

  // ---------------------------------------------------------------------------
  // init
  // ---------------------------------------------------------------------------
  function init() {
    cacheEls();
    bindEvents();
    const params = new URLSearchParams(location.search);
    state.pendingSample = params.get('sample');
    state.pendingTime = params.get('t');
    state.pendingEntity = params.get('entity');
    // initial size measurement
    const mapWrap = document.querySelector('.rr-map-wrap');
    const timelineWrap = document.querySelector('.rr-timeline-wrap');
    if (mapWrap) state.mapSize = { w: mapWrap.clientWidth, h: mapWrap.clientHeight };
    if (timelineWrap) state.timelineSize = { w: timelineWrap.clientWidth, h: timelineWrap.clientHeight };
    loadBundleDataset(false);
    if (params.get('data')) {
      toast('检测到 ?data= 参数；将尝试读取 CSV 与 gzip 事件流。', false, 5000);
      loadFromPathFromBase(params.get('data'));
    }
    const gzipParam = params.get('gzip');
    if (gzipParam) {
      toast('检测到 ?gzip= 参数；将尝试流式解压事件流。', false, 5000);
      (async () => {
        try {
          const response = await fetch(gzipParam, { cache: 'no-store' });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          await loadGzipStream(response, gzipParam.split('/').pop() || 'gzip');
        } catch (error) {
          toast(`?gzip= 读取失败：${error.message || error}`, true, 8000);
        }
      })();
    }
    window.REPLAY_REVIEW_DEBUG = {
      snapshot() {
        return {
          source: state.dataset ? state.dataset.source : null,
          files: state.dataset ? state.dataset.files.length : 0,
          file: state.file ? state.file.name : null,
          maxSeq: state.maxSeq,
          streamStatus: state.streamStatus,
          counts: state.dataset ? state.dataset.counts : null,
          categories: state.file ? state.file.eventCategoryCounts : null,
          buyEvents: state.file ? state.file.buyEvents.length : 0,
          skillEvents: state.file ? state.file.skillEvents.length : 0,
          streamRows: state.file ? state.file.stream.length : 0,
          rawPlayers: state.file ? state.file.raw.players.length : 0,
          rosterPlayers: state.file ? state.file.roster.length : 0,
          playerSetSize: state.file && state.file.raw._playerSet instanceof Set ? state.file.raw._playerSet.size : null,
          rawPlayerSample: state.file ? state.file.raw.players.slice(0, 30) : null,
          screenshotChecks: state.dataset && state.dataset.screenshotChecks
            ? state.dataset.screenshotChecks.length
            : (state.staticScreenshotChecks || []).length,
        };
      },
    };
    requestAnimationFrame(tick);
  }

  async function loadFromPathFromBase(baseValue) {
    try {
      const base = baseValue.endsWith('/') ? baseValue : baseValue + '/';
      await loadFromBase(base, 'path', '?data=');
    } catch (error) {
      toast(error.message || '?data= 读取失败，保留内置快照', true, 7000);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
