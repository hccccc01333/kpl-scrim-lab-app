/**
 * 决策台 / 概览页 客户端截图与冒烟。
 *
 * 前置：
 *   python server.py（或 TRAINING_PORT=8790 python server.py）已启动真实/演示数据
 *   cd client && npm run build
 *
 * 用法：
 *   node scripts/shot_client_decision.mjs
 *   KPL_BASE=http://127.0.0.1:8790 KPL_OUT=.screenshots/decision node scripts/shot_client_decision.mjs
 *
 * 产物：KPL_OUT（默认 .screenshots/decision）下的 png + summary.txt
 */
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..')
const require = createRequire(join(ROOT, 'client', 'package.json'))
const { _electron: electron } = require('playwright-core')
const BASE = process.env.KPL_BASE || 'http://127.0.0.1:8790'
const OUT = resolve(ROOT, process.env.KPL_OUT || '.screenshots/decision')
const ELECTRON = process.env.KPL_ELECTRON || join(ROOT, 'client/node_modules/electron/dist/electron.exe')
const MAIN = join(ROOT, 'client/out/main/index.js')

const TABS = [
  ['overview', '#/', '概览'],
  ['review', '#/decision?tab=review', '赛后复盘'],
  ['prep', '#/decision?tab=prep', '赛前备战'],
  ['player', '#/decision?tab=player', '选手研究'],
  ['training', '#/decision?tab=training', '训练验证']
]

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))


/** Electron 自己截图：避免 Playwright 在 zoomFactor != 1 时按 CSS 尺寸裁图 */
async function capture(app, file) {
  const base64 = await app.evaluate(async ({ BrowserWindow }) => {
    const win = BrowserWindow.getAllWindows()[0]
    if (!win) return ''
    const image = await win.webContents.capturePage()
    return image.toPNG().toString('base64')
  })
  if (!base64) throw new Error('capturePage 返回空图')
  writeFileSync(file, Buffer.from(base64, 'base64'))
}

async function main() {
  mkdirSync(OUT, { recursive: true })
  if (!ELECTRON) throw new Error('找不到 Electron 可执行文件')
  const userData = mkdtempSync(join(tmpdir(), 'kpl-client-'))
  writeFileSync(join(userData, 'settings.json'), JSON.stringify({
    baseUrl: BASE, theme: 'light', density: 'comfortable',
    minimizeToTray: false, workbenchPath: '', zoom: 1.15
  }), 'utf8')

  const childEnv = { ...process.env, KPL_CLIENT_USER_DATA: userData }
  // 当前会话可能继承 ELECTRON_RUN_AS_NODE=1（例如宿主本身是 Electron），
  // 那会让 electron.exe 退化成纯 Node，必须在子进程里去掉。
  delete childEnv.ELECTRON_RUN_AS_NODE
  const app = await electron.launch({
    executablePath: ELECTRON,
    args: [MAIN, ...(process.env.KPL_START_URL ? [process.env.KPL_START_URL] : [])],
    env: childEnv,
    timeout: 120000
  })
  const logs = []
  const page = await app.firstWindow()
  page.on('console', (msg) => {
    if (msg.type() === 'error') logs.push(`console.error: ${msg.text()}`)
  })
  page.on('pageerror', (error) => logs.push(`pageerror: ${error.message}`))

  try {
    await page.waitForSelector('.rail-nav', { timeout: 90000 })
    await sleep(2000)
  } catch (error) {
    logs.push(`连接失败：${error.message}`)
    await capture(app, join(OUT, 'connect.png'))
    writeFileSync(join(OUT, 'summary.txt'), logs.join('\n'), 'utf8')
    await app.close()
    throw error
  }

  const initialHash = await page.evaluate(() => location.hash)
  const results = [`initial\t${initialHash || '(空)'}`]
  for (const [name, hash, label] of TABS) {
    await page.evaluate((value) => { location.hash = value }, hash)
    await sleep(name === 'overview' ? 2500 : 1600)
    const text = (await page.evaluate(() => document.body.innerText || '')).trim()
    const hasLabel = name === 'overview' || text.includes(label)
    const overflow = await page.evaluate(() => {
      const doc = document.documentElement
      const work = document.querySelector('.workspace')
      return {
        doc: doc.scrollWidth > window.innerWidth,
        work: work ? work.scrollWidth > work.clientWidth + 1 : false,
        innerWidth: window.innerWidth,
        dpr: window.devicePixelRatio
      }
    })
    results.push(`${name}\t${hasLabel ? 'ok' : '缺少标题'}\t${text.length} 字\t${page.url()}\toverflow=${JSON.stringify(overflow)}`)
    await capture(app, join(OUT, `${name}.png`))
    // 应用壳内部是滚动容器，fullPage 只拍首屏；按 860px 步进补拍内容区。
    if (name !== 'overview') {
      const height = await page.evaluate(() => {
        const el = document.querySelector('.workspace')
        return el ? el.scrollHeight : document.body.scrollHeight
      })
      const steps = Math.min(6, Math.max(1, Math.ceil(height / 860)))
      for (let step = 0; step < steps; step += 1) {
        await page.evaluate((top) => {
          const el = document.querySelector('.workspace')
          if (el) el.scrollTop = top
          else window.scrollTo(0, top)
        }, step * 860)
        await sleep(500)
        await capture(app, join(OUT, `${name}-${step + 1}.png`))
      }
      await page.evaluate(() => {
        const el = document.querySelector('.workspace')
        if (el) el.scrollTop = 0
      })
    }
  }

  // 概览首屏应出现「今天先看这几件事」；决策台应出现覆盖条与问题卡
  await page.evaluate(() => { location.hash = '#/' })
  await sleep(2000)
  const overviewText = await page.evaluate(() => document.body.innerText || '')
  await page.evaluate(() => { location.hash = '#/decision?tab=review' })
  await sleep(2200)
  const decisions = await page.evaluate(() => document.body.innerText || '')
  const checks = {
    overviewBriefing: /今天先看这几件事|暂时没有足够证据/.test(overviewText),
    decisionTitle: /赛训决策台/.test(decisions),
    coverage: /完整回放|终局面板/.test(decisions),
    sample: /样本|局/.test(decisions),
    lossSection: /经济|关键链|复盘/.test(decisions)
  }
  writeFileSync(join(OUT, 'summary.txt'),
    [...results, '', 'checks:', JSON.stringify(checks, null, 2), '', 'browser errors:',
      ...(logs.length ? logs : ['(none)'])].join('\n'), 'utf8')
  console.log(results.join('\n'))
  console.log('checks', checks)
  console.log(logs.length ? `浏览器错误 ${logs.length} 条（见 summary.txt）` : '无控制台错误')
  await app.close()
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
