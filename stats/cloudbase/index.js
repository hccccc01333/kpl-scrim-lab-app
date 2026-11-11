/**
 * KPL 赛训工作台 · 匿名使用统计云函数（腾讯云 CloudBase，作者自部署）
 *
 * 由「云函数 HTTP 访问服务」触发，实现与 stats/server.py 相同的接口：
 *   POST /api/ping     客户端心跳（无需 token）
 *   GET  /api/summary  汇总数字（Bearer token 或 ?token=）
 *   GET  /api/health   存活探针
 *
 * 数据落在云数据库集合 usage_installs（文档 _id = installId）：
 *   first_seen / last_seen（毫秒时间戳）、first_version、version、
 *   os、os_version、arch、pings。
 *
 * 环境变量（云函数配置 → 环境变量）：
 *   STATS_TOKEN       查询令牌，必填；不配则查询接口拒绝服务
 *   STATS_COLLECTION  集合名，默认 usage_installs
 *
 * 只保存客户端上报的匿名字段；不记录 IP、UA、来源地域。
 */
'use strict';

const crypto = require('crypto');
const cloudbase = require('@cloudbase/node-sdk');

const app = cloudbase.init({ env: cloudbase.SYMBOL_CURRENT_ENV });
const db = app.database();
const _ = db.command;

const SCHEMA = 1;
const COLLECTION = process.env.STATS_COLLECTION || 'usage_installs';
const TOKEN = process.env.STATS_TOKEN || '';
const INSTALL_ID_RE = /^[0-9A-Za-z._-]{1,64}$/;
const MAX_FIELD = 128;
const DAY_MS = 24 * 3600 * 1000;
const PAGE_SIZE = 1000;
const MAX_PAGES = 20;

function text(value, limit) {
  return String(value === undefined || value === null ? '' : value).trim().slice(0, limit || MAX_FIELD);
}

function iso(ms) {
  if (!ms) return null;
  return new Date(Number(ms)).toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function json(statusCode, data) {
  return {
    statusCode,
    headers: { 'content-type': 'application/json; charset=utf-8' },
    body: JSON.stringify(data),
  };
}

function html(statusCode, body) {
  return {
    statusCode,
    headers: { 'content-type': 'text/html; charset=utf-8' },
    body,
  };
}

function parseRequest(event) {
  const headers = {};
  const rawHeaders = event.headers || {};
  Object.keys(rawHeaders).forEach((key) => {
    headers[String(key).toLowerCase()] = rawHeaders[key];
  });
  const http = (event.requestContext && (event.requestContext.http || event.requestContext)) || {};
  const method = String(event.httpMethod || http.method || 'GET').toUpperCase();
  let path = event.path || http.path || '/';
  path = String(path).split('?')[0];
  const query = event.queryStringParameters || event.queryString || {};
  let body = event.body || '';
  if (event.isBase64Encoded && body) {
    body = Buffer.from(String(body), 'base64').toString('utf8');
  }
  return { method, path, headers, query, body };
}

/** 把 `/api/ping`、`/ping`、带尾斜杠等形式归一到 `/ping`。 */
function routeOf(path) {
  let route = String(path || '/').replace(/\/+$/, '');
  if (!route) route = '/';
  route = route.replace(/^\/api(?=\/|$)/, '');
  return route || '/';
}

function safeEqual(left, right) {
  const a = Buffer.from(String(left));
  const b = Buffer.from(String(right));
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function authorized(req) {
  if (!TOKEN) return false;
  const header = req.headers.authorization || '';
  const candidates = [];
  if (String(header).toLowerCase().startsWith('bearer ')) {
    candidates.push(String(header).slice(7).trim());
  }
  if (req.query && req.query.token) candidates.push(String(req.query.token).trim());
  return candidates.some((candidate) => safeEqual(candidate, TOKEN));
}

async function recordPing(payload) {
  const rawInstallId = payload.installId;
  const installId = String(rawInstallId === undefined || rawInstallId === null ? '' : rawInstallId).trim();
  // 先看原始长度再校验：不能截断后当合法 ID，否则超长串会被静默接受。
  if (installId.length > 64 || !INSTALL_ID_RE.test(installId)) {
    const error = new Error('installId 无效');
    error.statusCode = 400;
    throw error;
  }
  const now = Date.now();
  const version = text(payload.version, 64);
  const osName = text(payload.os, 64);
  const osVersion = text(payload.osVersion);
  const arch = text(payload.arch, 64);
  const collection = db.collection(COLLECTION);
  const updateFields = {
    last_seen: now,
    version,
    os: osName,
    os_version: osVersion,
    arch,
    pings: _.inc(1),
  };
  let updated = 0;
  try {
    const result = await collection.doc(installId).update({ data: updateFields });
    updated = (result && result.updated) || 0;
  } catch (err) {
    updated = 0;
  }
  if (updated) return;
  try {
    await collection.doc(installId).set({
      data: {
        first_seen: now,
        last_seen: now,
        first_version: version,
        version,
        os: osName,
        os_version: osVersion,
        arch,
        pings: 1,
      },
    });
  } catch (err) {
    // 并发首插：另一个请求已经创建了文档，退回更新即可。
    await collection.doc(installId).update({ data: updateFields });
  }
}

async function countWhere(collection, condition) {
  let query = collection;
  if (condition) query = query.where(condition);
  const result = await query.count();
  return (result && result.total) || 0;
}

async function collectSummary() {
  const now = Date.now();
  const cut24h = now - DAY_MS;
  const cut7d = now - 7 * DAY_MS;
  const cut30d = now - 30 * DAY_MS;
  const collection = db.collection(COLLECTION);

  const [totalInstalls, active24h, active7d, active30d, newLast7d] = await Promise.all([
    countWhere(collection, null),
    countWhere(collection, { last_seen: _.gte(cut24h) }),
    countWhere(collection, { last_seen: _.gte(cut7d) }),
    countWhere(collection, { last_seen: _.gte(cut30d) }),
    countWhere(collection, { first_seen: _.gte(cut7d) }),
  ]);

  // 版本分布：只统计近 30 天活跃的安装。规模很小（安装级数据），
  // 分页拉取比聚合管道更省心，也不会受聚合 API 版本差异影响。
  const byVersion = {};
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await collection
      .where({ last_seen: _.gte(cut30d) })
      .field({ version: true })
      .orderBy('last_seen', 'desc')
      .skip(page * PAGE_SIZE)
      .limit(PAGE_SIZE)
      .get();
    const rows = (result && result.data) || [];
    rows.forEach((row) => {
      const key = text(row.version, 64) || '未知';
      byVersion[key] = (byVersion[key] || 0) + 1;
    });
    if (rows.length < PAGE_SIZE) break;
  }

  let lastPingAt = null;
  try {
    const latest = await collection.orderBy('last_seen', 'desc').limit(1).get();
    const row = ((latest && latest.data) || [])[0];
    lastPingAt = iso(row && row.last_seen);
  } catch (err) {
    lastPingAt = null;
  }

  return {
    ok: true,
    schema: SCHEMA,
    generatedAt: iso(now),
    totalInstalls,
    active24h,
    active7d,
    active30d,
    newLast7d,
    byVersion,
    lastPingAt,
  };
}

function dashboardHtml(summary) {
  const esc = (value) => String(value === undefined || value === null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  const num = (value) => Number(value || 0).toLocaleString('en-US');
  const rows = Object.keys(summary.byVersion || {}).map((version) => (
    `<tr><td>${esc(version)}</td><td class="num">${num(summary.byVersion[version])}</td></tr>`
  )).join('') || '<tr><td colspan="2">近 30 天暂无活跃安装</td></tr>';
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KPL 赛训工作台 · 使用统计</title>
<style>
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;margin:0;background:#0f1420;color:#e6e9f0}
main{max-width:760px;margin:40px auto;padding:0 20px}
h1{font-size:20px;font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0 28px}
.card{background:#171e2e;border:1px solid #263149;border-radius:10px;padding:14px 16px}
.card .label{color:#8b97ad;font-size:12px}
.card .value{font-size:26px;font-weight:700;margin-top:4px}
table{width:100%;border-collapse:collapse;background:#171e2e;border:1px solid #263149;border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:10px 14px;border-bottom:1px solid #263149;font-size:14px}
th{color:#8b97ad;font-weight:500}
td.num,th.num{text-align:right}
tr:last-child td{border-bottom:none}
.foot{color:#66718a;font-size:12px;margin-top:18px;line-height:1.7}
</style></head><body><main>
<h1>KPL 赛训工作台 · 匿名使用统计</h1>
<div class="grid">
<div class="card"><div class="label">累计安装</div><div class="value">${num(summary.totalInstalls)}</div></div>
<div class="card"><div class="label">24 小时活跃</div><div class="value">${num(summary.active24h)}</div></div>
<div class="card"><div class="label">7 天活跃</div><div class="value">${num(summary.active7d)}</div></div>
<div class="card"><div class="label">30 天活跃</div><div class="value">${num(summary.active30d)}</div></div>
<div class="card"><div class="label">近 7 天新增</div><div class="value">${num(summary.newLast7d)}</div></div>
</div>
<table><thead><tr><th>版本（近 30 天活跃）</th><th class="num">安装数</th></tr></thead>
<tbody>${rows}</tbody></table>
<p class="foot">最近心跳：${esc(summary.lastPingAt || '—')}<br>
页面生成：${esc(summary.generatedAt || '')}<br>
数据来自客户端匿名心跳，不含主机名 / 用户名 / 路径 / 战队或对局内容。</p>
</main></body></html>`;
}

exports.main = async (event) => {
  const req = parseRequest(event || {});
  const route = routeOf(req.path);

  if (req.method === 'OPTIONS') {
    return { statusCode: 204, headers: {}, body: '' };
  }

  if (route === '/health' && (req.method === 'GET' || req.method === 'HEAD')) {
    return json(200, { ok: true, schema: SCHEMA });
  }

  if (route === '/ping' && req.method === 'POST') {
    let payload;
    try {
      payload = JSON.parse(req.body || '{}');
    } catch (err) {
      return json(400, { ok: false, detail: '心跳 JSON 无效' });
    }
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      return json(400, { ok: false, detail: '心跳 JSON 无效' });
    }
    try {
      await recordPing(payload);
    } catch (err) {
      return json(err.statusCode || 500, { ok: false, detail: err.message || '落库失败' });
    }
    return json(200, { ok: true });
  }

  if (route === '/summary' && req.method === 'GET') {
    if (!TOKEN) {
      return json(500, { ok: false, detail: '云函数未配置 STATS_TOKEN 环境变量' });
    }
    if (!authorized(req)) {
      return json(401, { ok: false, detail: '访问令牌无效' });
    }
    try {
      return json(200, await collectSummary());
    } catch (err) {
      return json(500, { ok: false, detail: err.message || '汇总查询失败' });
    }
  }

  if (route === '/' && req.method === 'GET') {
    if (!TOKEN) {
      return html(500, '<h1>云函数未配置 STATS_TOKEN 环境变量</h1>');
    }
    if (!authorized(req)) {
      return html(401, '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        + '<title>需要访问令牌</title></head><body style="font-family:sans-serif;padding:40px">'
        + '<h1>需要访问令牌</h1><p>在地址后加 <code>?token=你的令牌</code>。</p></body></html>');
    }
    try {
      return html(200, dashboardHtml(await collectSummary()));
    } catch (err) {
      return html(500, `<h1>汇总查询失败</h1><pre>${String(err.message || err)}</pre>`);
    }
  }

  return json(404, { ok: false, detail: '接口不存在' });
};
