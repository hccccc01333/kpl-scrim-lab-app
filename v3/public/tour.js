/** 分步教程：从采集、补录到复盘，跟着点一遍就会用。 */

/* 教程目录只在第一次打开时自动弹出；进度按课保存，可以单独重看。 */
const SEEN_KEY = 'training-tour-complete-v3';
const PROGRESS_KEY = 'training-tour-v3-progress';

const NAV_HREF = { setup: '#plan', players: '#playerarchive' };
const navHref = (key) => NAV_HREF[key] || '#' + key;
/* 顶部导航在窄屏收进菜单：先高亮菜单按钮，点开后再高亮菜单里的那一项。 */
function navTarget(key) {
  return () => {
    const desktop = document.querySelector(`.main-nav [data-nav="${key}"]`);
    if (desktop?.getClientRects().length) return desktop;
    const item = document.querySelector(`.mobile-menu a[href="${navHref(key)}"]`);
    if (item?.getClientRects().length) return item;
    return document.querySelector('.menu-button');
  };
}
const navAdvance = (key) => [`.main-nav [data-nav="${key}"]`, `.mobile-menu a[href="${navHref(key)}"]`];

const LESSONS = [
  {
    id: 'collect',
    title: '把一局训练赛拉进来',
    lede: '授权一次、绑一个每场都上的选手，之后每天只点两下',
    time: '3 分钟',
    steps: [
      {
        target: '[data-tour="collect-hero"]',
        route: '#ingest',
        title: '今天该做哪一步，只看这张卡',
        text: '深色卡永远只给一个动作：没授权就扫码，没绑定就填营地 ID，都好了就拉对局。第一次用，跟着右边的按钮走就行。',
      },
      {
        target: '[data-tour="camp-connect"]',
        title: '扫码授权：一次就够',
        text: '用教练自己的王者营地 App 扫码，凭证只存在这台电脑上。过期时这里会变红，点「补充授权」重扫一次，已经入库的局不受影响。',
      },
      {
        target: '[data-tour="camp-players"]',
        title: '绑定一个每场都上的选手',
        text: '不用全队都绑。挑队长这种场场都在的号，把他的营地链接粘进来即可 —— 一局详情自带双方十人面板，一个号就能覆盖全队。',
      },
      {
        target: '[data-tour="camp-link"]',
        open: '[data-tour="camp-link"]',
        title: '这条链接从哪来',
        text: '营地打开这一局结算页 → 右上「…」→「分享」到微信 → 长按卡片选「用默认浏览器打开」→ 复制地址栏整条链接。'
          + '链接里 <code>userId=</code> 才是营地 ID，<code>roleId=</code> 不是；小程序卡片打不开，必须走浏览器。'
          + '展开的步骤里有三张实拍图，走完这一课再回来对照着做。',
      },
      {
        target: '[data-tour="camp-pull"]',
        title: '拉取对局',
        text: '点「拉取对局」，读出选手最近打过哪些局，按局去重后列出来。勾上今天练的，再点「同步所选」。',
      },
      {
        target: '[data-tour="camp-flow"]',
        title: '只有缺失值才需要审查',
        text: '同步完成后，无缺失值的对局会直接进入正式统计；下面只列有缺失值的局。点进去核对十人面板，补不齐也可以确认缺失后保存。',
      },
    ],
  },
  {
    id: 'fields',
    key: true,
    title: '补录字段：把缺的数据填上',
    lede: '版本、规则、十人面板的数值，缺的都在这里补齐',
    time: '4 分钟',
    steps: [
      {
        target: '[data-sx-scope="pending"]',
        route: '#pending',
        title: '缺哪些字段，先看这张表',
        text: '每局采集完都会跑一遍预填：版本、规则、训练组、选用顺序这些拿不准的，会挂到「确认队列」上。上面的统计就是还缺多少项、分布在几局。',
      },
      {
        target: '.sx-pending-card',
        title: '一局一张卡',
        text: '每张卡是一局，只列这局缺的字段。字段名下面写着来源和把握 —— 看到「自动生成 · 低可信」，就是要你亲自看一眼的那种。',
      },
      {
        target: '.sx-pending-card .sx-pending-fields',
        title: '选好值，点「确认」',
        text: '版本、规则从词表里选；训练组可以直接输入新值，保存后进词表，下次不用再打一遍。确认一项就写回这局，并标成人工来源。',
      },
      {
        target: '.sx-pending-card .sx-pending-foot',
        title: '一局填完就「全部确认」',
        text: '同一张卡确认完，点这里一次过；左下角显示还剩几项。这批对局的口径，就是在这里定下来的。',
      },
      {
        target: '.chan-row',
        route: '#ingest',
        click: true,
        title: '十人面板的数值在「缺失值审查」里改',
        text: '缺失值审查里点任意一局，改十个人的击杀、经济、输出这些具体数字；补完再保存到正式统计。现在点第一行试试。',
      },
      {
        target: '.ed-main',
        title: '每个数字都能改',
        text: '十人数据表：击杀 / 死亡 / 助攻 / 经济 / 输出 / 承伤 / 参团 / 评分，英雄名也能改。改完先点右上角「保存修改」，草稿才留住。',
      },
      {
        target: '.ed-aside section:nth-of-type(2)',
        title: '填备注，标记复核',
        text: '右侧「复核」里填一句备注，比如「按营地十人面板核对，输出以营地总伤害为准」。点「标记为已复核」，这一步是给这份数据背书，也是保存到正式统计的前提。',
      },
      {
        target: '.ed-top-actions',
        title: '四步的顺序不能颠倒',
        text: '右上角两个按钮：改完先「保存修改」；复核之后「保存到正式统计」才会亮（已经存过的局会显示「已进正式统计」）。顺序固定：改数字 → 保存修改 → 标记复核 → 保存到正式统计，中间任何一次改动都会让复核失效。有缺失值时，标记复核前会再确认一次。',
      },
    ],
  },
  {
    id: 'replay',
    title: '复盘一局：先读结论',
    lede: '从比分一路读到第几分钟出了问题',
    time: '3 分钟',
    steps: [
      {
        target: navTarget('matches'),
        advanceOn: navAdvance('matches'),
        click: true,
        title: '复盘从「对局」进',
        text: '所有训练赛都在这儿，一行就是一局：比分、时长、双方阵容。',
      },
      {
        target: '.match-row',
        click: true,
        title: '点一行，进这一局',
        text: '随便点一场。演练时用演示数据，十一局都能点开。',
      },
      {
        target: '#match-verdict',
        title: '先读这一句结论',
        text: '深色卡用一句话说清这局怎么走的，下面才是比分和经济差。开复盘会先念这句，再决定往哪看。',
      },
      {
        target: '#match-totals',
        title: '总量：这一局谁多谁少',
        text: '经济、击杀、输出、承伤四组数字，金色是本队、青色是对手。来源是营地十人面板，五个人加总，不是估算。',
      },
      {
        target: '#match-pulse',
        title: '比赛脉搏：拐点在第几分钟',
        text: '拖动或点曲线，任意时刻的经济差都会跟出来；菱形是资源、方块是建筑。曲线突然掉下去的那一分钟，就是复盘要讲的节点。',
      },
      {
        target: '#match-timeline',
        title: '关键节点：能落到分钟',
        text: '按时间排好，写清第几分钟、发生了什么、当时经济差多少。这几行可以直接抄进复盘记录。',
      },
    ],
  },
  {
    id: 'detail',
    title: '复盘一局：再看对位',
    lede: '十个人逐项对照，谁这条线赢了、压到哪',
    time: '3 分钟',
    steps: [
      {
        target: '.match-row',
        route: '#matches',
        click: true,
        title: '再点开一局',
        text: '这一课看的是人和位置。先随便点一场。',
      },
      {
        target: '#match-profiles',
        title: '十人面板：逐人对位',
        text: '两队十个人放在一张表里，同分路的两个人归一比较。谁这条线赢了，条形一眼看出来；有位置数据时还多一列「入侵」。',
      },
      {
        target: '#match-heat',
        title: '对位热区：这一路怎么走的',
        text: '选一路，看这两个人在 90 秒窗口里的移动；拖时间轴或点播放。金色是本队、青色是对手。',
      },
      {
        target: '#match-duel',
        title: '对位纵深：压得深不深',
        text: '一格约十秒，方块越多说明在对方半区待得越久。深区是推进到 66% 以上，半区是过河道 —— 训练里说的「压得深」就是这张图。',
      },
      {
        target: '#match-bp',
        title: '本局 BP',
        text: '双方终局阵容和禁用都在这里，选用按序号排。营地面板只给终局名单，手序需要补时进校对页填。',
      },
    ],
  },
  {
    id: 'cross',
    title: '把十几局放在一起看',
    lede: '单局看过程，跨局看规律',
    time: '4 分钟',
    steps: [
      {
        target: '.secondary-nav a[href="#cross"]',
        advanceOn: ['.secondary-nav a[href="#cross"]'],
        route: '#matches',
        click: true,
        title: '换一个看法',
        text: '点「跨局分析」，把当前范围内的每一局放在一起比。',
      },
      {
        target: '.cx-hero',
        title: '先读这一句',
        text: '深色头卡是整批对局的结论，数字直接写进标题；下面四个指标给它兜底。再往下一排小图是一局一块，点一块就聚焦那一局。',
      },
      {
        target: '.cx-toolbar',
        title: '范围由你定',
        text: '搜对手、换排序、改每页条数。这里的口径是当前筛选范围的全量对局，不是只算这一屏。',
      },
      {
        target: '.cx-viz-index',
        title: '十张分析，点名字直达',
        text: '分层基准、波动来源、下限风险……点任意一个名字，直接跳到那张图，不用从头往下滚。',
      },
      {
        target: '.cx-find',
        title: '一张卡只回答一个问题',
        text: '大数字是答案，图是证据，最下面「训练安排」是明天就能排进课表的动作。每张卡都标了依据多少局，样本少会自己降级说法。',
      },
      {
        target: '.cx-find [data-cx-view-btn="b"]',
        click: true,
        title: '每张图都有两个看法',
        text: '比如「典型水平 / 按对手看」。同一个数字换一种切法，回答的是不同问题。点一下试试。',
      },
      {
        target: '.cx-find .cx-cf-foot',
        title: '答案下面还有动作',
        text: '右边按钮把这批相关的局圈出来，跳到逐局对照。想直接看某一局，点圈定后那一行最右边的箭头。',
      },
    ],
  },
  {
    id: 'heroes',
    title: '英雄与 BP',
    lede: '哪些英雄真能赢，打谁该 ban 谁',
    time: '3 分钟',
    steps: [
      {
        target: navTarget('heroes'),
        advanceOn: navAdvance('heroes'),
        click: true,
        title: '先看英雄榜',
        text: '按胜率分档列出本队用过的英雄，S 档是胜率 55% 以上。',
      },
      {
        target: '.hero-board',
        title: '先设样本门槛',
        text: '左边搜索和分路筛选，右边是当前结果数。出场少会掉到 C 档，两局的样本别拿来下结论。',
      },
      {
        target: '.hero-insight-card',
        click: true,
        title: '点一个英雄进去',
        text: '里面是这个英雄的各位置表现、常用搭档、常见出装、同位置对位和最近出场，一块一行。',
      },
      {
        target: navTarget('bp'),
        advanceOn: navAdvance('bp'),
        click: true,
        title: 'BP 在另一个入口',
        text: '顶部「BP」把选用、禁用、针对 ban 和胜负放在一起看。',
      },
      {
        target: '[data-tour="bp-profile"]',
        title: '先筛条件，再看画像',
        text: '对手、训练日、阵营、赛果都能筛，下面的画像跟着重算。想知道打某支队伍该 ban 谁，就把对手换成他。',
      },
    ],
  },
  {
    id: 'people',
    title: '选手与对手',
    lede: '谁在打、谁状态在变、对手什么风格',
    time: '3 分钟',
    steps: [
      {
        target: navTarget('players'),
        advanceOn: navAdvance('players'),
        click: true,
        title: '选手档案',
        text: '这里按营地记录汇总每个昵称：胜率、KDA、MVP、参团。',
      },
      {
        target: '[data-pa-leaders]',
        title: '先看这一行点名',
        text: '这一行把当前筛选里最突出的几个人直接点出来：KDA 领跑、MVP 最多、输出占比最高、胜率最高。想细看谁，就点下面的卡片。',
      },
      {
        target: '.pa-card',
        click: true,
        title: '点卡片看个人页',
        text: '个人页只讲一个人：同位置分位、打法画像、逐局表现、同局对位、关键局。',
      },
      {
        target: navTarget('teams'),
        advanceOn: navAdvance('teams'),
        click: true,
        title: '对手在「战队」里',
        text: '战队档案、战队风格、阵容和训练量都在这一组；对手教练也在这里录。',
      },
      {
        target: '.tm-grid',
        title: '一张卡是一支对手',
        text: '得分由对手胜率和分均数据合成，点进去看交手记录。打之前先看这里，比记印象可靠。',
      },
    ],
  },
  {
    id: 'plan',
    title: '排训练、存报告',
    lede: '把采集、分析、复盘串成一个周期',
    time: '4 分钟',
    steps: [
      {
        target: navTarget('setup'),
        advanceOn: navAdvance('setup'),
        click: true,
        title: '从「赛训」进',
        text: '训练计划、数据准备、复盘与报告三件事，都在这一组。',
      },
      {
        target: '[data-sx-anchor="plan-form"]',
        title: '先把计划排上',
        text: '登记日期、对手、赛制。排上之后，当天拉进来的局会自动挂到这次训练上。',
      },
      {
        target: '[data-sx-anchor="plan-list"]',
        title: '计划列表',
        text: '点一行能改时间、对手和状态；训练结束后在这里标记完成，训练量统计才会准。',
      },
      {
        target: '.secondary-nav a[href="#setup"]',
        advanceOn: ['.secondary-nav a[href="#setup"]'],
        route: '#plan',
        click: true,
        title: '把人和队补齐',
        text: '「数据准备」里先给营地的游戏ID起名、归队（身份对照），再录本队资料与战队主数据。名字补齐后，所有分析显示真人名，不再显示昵称。',
      },
      {
        target: '.secondary-nav a[href="#reports"]',
        advanceOn: ['.secondary-nav a[href="#reports"]'],
        route: '#setup',
        click: true,
        title: '最后存成报告',
        text: '「复盘与报告」能把分析结论存成快照，也能一键生成训练周报；报告里保留当时的数据范围和口径。',
      },
    ],
  },
];
/* 课号按顺序生成，增删课程不用回来改编号。 */
LESSONS.forEach((item, index) => { item.no = String(index + 1).padStart(2, '0'); });

const COUNT_WORD = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十'];

function readProgress() {
  try {
    const value = JSON.parse(localStorage.getItem(PROGRESS_KEY) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch {
    return {};
  }
}

export function createTour() {
  let progress = readProgress();
  let mode = 'idle';          // idle | hub | lesson | done
  let lessonIndex = -1;
  let stepIndex = -1;
  let seen = Boolean(localStorage.getItem(SEEN_KEY));
  let runToken = 0;
  /* 教程自己把目标滚进视野时，别再触发一次重画。 */
  let programmatic = false;
  let scrollTimer = null;
  /* 记录已经自动滚过的步骤，避免反复重排。 */
  let scrolledStep = '';
  /* 上一步量到的说明卡高度：用来给页面留出卡片的落位空间。 */
  let lastCardH = 0;
  const layer = document.createElement('div');
  layer.className = 'tour-layer';
  layer.hidden = true;
  document.body.append(layer);

  const active = () => mode === 'hub' || mode === 'lesson' || mode === 'done';
  const lesson = () => LESSONS[lessonIndex] || null;
  const step = () => lesson()?.steps?.[stepIndex] || null;
  const doneCount = () => LESSONS.filter((x) => progress[x.id]).length;

  /* ── 公共小件 ─────────────────────────────────────────── */
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const badge = (id) => progress[id] ? '<i class="tour-state is-done">已完成</i>'
    : (lessonIndex >= 0 && LESSONS[lessonIndex].id === id ? '<i class="tour-state is-now">进行中</i>' : '<i class="tour-state">未开始</i>');
  const find = (selector) => { try { return document.querySelector(selector); } catch { return null; } };
  const visible = (node) => Boolean(node && node.getClientRects().length);
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function close() {
    mode = 'idle';
    lessonIndex = -1;
    stepIndex = -1;
    runToken += 1;
    layer.hidden = true;
    layer.innerHTML = '';
  }

  function hub() {
    runToken += 1;
    mode = 'hub';
    lessonIndex = -1;
    stepIndex = -1;
    layer.hidden = false;
    const done = doneCount();
    const percent = Math.round(done / LESSONS.length * 100);
    layer.innerHTML = `<div class="tour-full"></div><div class="tour-hub" role="dialog" aria-modal="true" aria-labelledby="tour-hub-title">
      <div class="tour-hub-head">
        <span class="tour-eyebrow">使用教程</span>
        <button class="tour-x" data-tour="close" aria-label="关闭教程">×</button>
        <h2 id="tour-hub-title">${COUNT_WORD[LESSONS.length]}堂课，从采集到复盘</h2>
        <p>按顺序做一遍；第二课「补录字段」是最关键的一步 —— 缺的字段都在那里补齐。之后每天重复前三课：采集、补录、复盘。</p>
        <div class="tour-progress"><i style="width:${percent}%"></i><span>已完成 ${done} / ${LESSONS.length}</span></div>
      </div>
      <ol class="tour-lessons">${LESSONS.map((item) => `<li>
        <button type="button" class="tour-lesson" data-lesson="${item.id}">
          <span class="tour-lesson-no">${item.no}</span>
          <span class="tour-lesson-copy"><b>${esc(item.title)}</b><small>${esc(item.lede)}</small></span>
          <span class="tour-lesson-meta"><b>${item.steps.length} 步 · ${esc(item.time)}</b><span class="tour-tags">${item.key ? '<i class="tour-key">最关键</i>' : ''}${badge(item.id)}</span></span>
        </button></li>`).join('')}</ol>
      <div class="tour-hub-foot">
        <p>教程只讲操作，不会改动任何数据。</p>
        <div class="tour-hub-actions">
          <button class="tour-quiet" data-tour="close">下次再说</button>
          <button class="primary" data-tour="start-first">从第一课开始</button>
        </div>
      </div>
    </div>`;
    seen = true;
    localStorage.setItem(SEEN_KEY, '1');
  }

  function cardHtml({ kicker, title, text, actions, progress: bar }) {
    return `<div class="tour-card" role="dialog" aria-live="polite" aria-label="使用教程">
      <div class="tour-card-top"><span>${kicker}</span><button class="tour-x" data-tour="close" aria-label="关闭教程">×</button></div>
      <h2>${title}</h2><p>${text}</p>
      <div class="tour-actions">${actions}</div>
      ${bar === null || bar === undefined ? '' : `<div class="tour-progress"><i style="width:${bar}%"></i></div>`}
    </div>`;
  }

  function startLesson(id) {
    const index = LESSONS.findIndex((item) => item.id === id);
    if (index < 0) return;
    lessonIndex = index;
    stepIndex = 0;
    mode = 'lesson';
    scrolledStep = '';
    draw();
  }

  function advance() {
    if (mode !== 'lesson') return;
    stepIndex += 1;
    if (stepIndex >= lesson().steps.length) { finishLesson(); return; }
    draw();
  }

  function finishLesson() {
    const item = lesson();
    progress = { ...progress, [item.id]: true };
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(progress));
    mode = 'done';
    runToken += 1;
    const next = LESSONS[lessonIndex + 1];
    layer.hidden = false;
    layer.innerHTML = `<div class="tour-full"></div>${cardHtml({
      kicker: `第 ${item.no} 课 · ${esc(item.title)}`,
      title: '这一课走完了',
      text: next ? `下一课：${esc(next.title)}。${esc(next.lede)}。` : `${COUNT_WORD[LESSONS.length]}堂课都走完了。之后每天从「采集」开始，遇到问题再点右上角问号回来看。`,
      actions: `<button class="tour-quiet" data-tour="hub">回到目录</button>${next
        ? `<button class="primary" data-tour="next-lesson">下一课 →</button>`
        : '<button class="primary" data-tour="close">开始使用</button>'}`,
      progress: 100,
    })}`;
  }

  /* 目标可能还没渲染出来（换页、异步取数），等一会儿再画。 */
  async function waitFor(target, token) {
    const start = performance.now();
    while (performance.now() - start < 15000) {
      if (token !== runToken) return null;
      const node = typeof target === 'function' ? target() : find(target);
      if (visible(node)) return node;
      /* 页面已经读完还是没有这个区块：不必干等，直接给可跳过的说明。 */
      if (performance.now() - start > 2400 && !document.querySelector('.loading')) return null;
      await sleep(120);
    }
    return null;
  }

  async function draw() {
    if (mode !== 'lesson') return;
    const token = ++runToken;
    const item = lesson();
    const current = step();
    if (!item || !current) return;
    layer.hidden = false;

    /* 需要换页时先给一张轻提示，别让教练面对空屏。 */
    if (current.route && location.hash !== current.route) {
      layer.innerHTML = `<div class="tour-full"></div><div class="tour-toast">正在打开「${esc(current.title)}」…</div>`;
      location.hash = current.route;
    }
    /* 页面还在取数时也留一句提示，避免目录弹窗僵在那里。 */
    const waiting = setTimeout(() => {
      if (token === runToken) layer.innerHTML = `<div class="tour-full"></div><div class="tour-toast">正在读取这一页…</div>`;
    }, 320);

    const target = await waitFor(current.target, token);
    clearTimeout(waiting);
    if (token !== runToken) return;
    /* 这一步要展开的折叠块，等页面渲染出来再打开，尺寸才量得准。 */
    if (current.open && target) {
      const fold = find(current.open);
      if (fold && 'open' in fold && !fold.open) { fold.open = true; await sleep(80); }
    }
    if (token !== runToken) return;
    const body = stepIndex;
    const total = item.steps.length;
    const percent = Math.round((body + 1) / total * 100);
    const kicker = `第 ${item.no} 课 · ${esc(item.title)}<b>${body + 1} / ${total}</b>`;
    const actions = target && current.click
      ? '<button class="tour-quiet" data-tour="hub">退出这一课</button><span class="tour-hint">点高亮区域继续</span>'
      : '<button class="tour-quiet" data-tour="hub">退出这一课</button><button class="primary" data-tour="next">下一步 →</button>';
    const panel = cardHtml({ kicker, title: esc(current.title), text: current.text, actions, progress: percent });

    if (!target) {
      layer.innerHTML = `<div class="tour-full"></div>${panel}`;
      return;
    }

    let r = target.getBoundingClientRect();
    /* 说明卡固定在右下不挪窝，所以先把目标顶到卡片上方，别让卡片压住它。 */
    const cardH = lastCardH || (innerWidth < 700 ? 300 : 276);
    /* 每一步只自动滚一次；否则「滚到位→再量」会互相触发，页面一直重排。 */
    const stepKey = `${lessonIndex}:${stepIndex}`;
    if (scrolledStep !== stepKey && (r.top < 80 || r.bottom > innerHeight - cardH - 44)) {
      scrolledStep = stepKey;
      programmatic = true;
      target.scrollIntoView({ block: 'start', inline: 'nearest', behavior: 'instant' });
      window.scrollBy(0, -84);
      r = target.getBoundingClientRect();
      setTimeout(() => { programmatic = false; }, 360);
    }
    const pad = 6;
    const x = Math.max(0, r.left - pad);
    const y = Math.max(0, r.top - pad);
    const w = Math.min(innerWidth - x, r.width + pad * 2);
    /* 太高的区块只框住上半段，否则整个视口都被罩住，说明卡没地方放。 */
    const full = r.height + pad * 2;
    let h = Math.min(innerHeight - y, full, Math.round(innerHeight * 0.52));
    const blocker = (left, top, width, height) => `<div class="tour-blocker" style="left:${left}px;top:${top}px;width:${Math.max(0, width)}px;height:${Math.max(0, height)}px"></div>`;
    const paint = (height) => {
      /* 区块比框高：底边改虚线，表示「这一段还在往下延伸」。 */
      const tail = height < full - 4 ? ' is-tall' : '';
      layer.innerHTML = blocker(0, 0, innerWidth, y) + blocker(0, y, x, height)
        + blocker(x + w, y, innerWidth - x - w, height) + blocker(0, y + height, innerWidth, innerHeight - y - height)
        + `<div class="tour-outline${tail}" style="left:${x}px;top:${y}px;width:${w}px;height:${height}px"></div>${panel}`;
      return layer.querySelector('.tour-card');
    };
    let panelNode = paint(h);
    let rect = panelNode.getBoundingClientRect();
    /* 长区块的上半段也可能压到说明卡：把高亮收在卡片上沿之上。 */
    const room = Math.round(rect.top - y - 14);
    if (room >= 180 && room < h) { h = room; panelNode = paint(h); rect = panelNode.getBoundingClientRect(); }

    /* 说明卡默认停在右下（窄屏停在底部）；只有目标已经贴到屏幕最下、
       卡片会整块盖住它时，才临时挪到顶部 —— 很少发生。 */
    const overlap = !(rect.bottom < y || rect.top > y + h) && !(rect.right < x || rect.left > x + w);
    const pinch = Math.min(innerHeight - y, full);
    if (overlap && pinch < 150 && y > rect.height + 24) { panelNode.style.top = '16px'; panelNode.style.bottom = 'auto'; }
    lastCardH = Math.round(rect.height);
  }

  /* 点偏了：卡片轻轻亮一下，让人知道该看哪儿，而不是以为页面卡住。 */
  function nudge() {
    const card = layer.querySelector('.tour-card');
    if (!card) return;
    card.classList.remove('is-nudge');
    void card.offsetWidth;
    card.classList.add('is-nudge');
    setTimeout(() => card.classList.remove('is-nudge'), 480);
  }

  /* ── 事件 ─────────────────────────────────────────────── */
  layer.addEventListener('click', (event) => {
    const action = event.target.closest('[data-tour]')?.dataset.tour;
    if (!action) {
      if (mode === 'lesson' && event.target.closest('.tour-blocker, .tour-full')) nudge();
      return;
    }
    event.preventDefault();
    if (action === 'close') { close(); return; }
    if (action === 'hub') { hub(); return; }
    if (action === 'start-first') { startLesson(LESSONS[0].id); return; }
    if (action === 'next') { advance(); return; }
    if (action === 'next-lesson') { startLesson(LESSONS[lessonIndex + 1]?.id); return; }
  });
  layer.addEventListener('click', (event) => {
    const id = event.target.closest('[data-lesson]')?.dataset.lesson;
    if (id) startLesson(id);
  });

  /* ── 背景锁定 ─────────────────────────────────────────
     教程开着的时候页面是锁的：滚轮、触摸、翻页键都不动页面，
     高亮区外面点不动（点一下卡片会亮起提示）。程序化滚动不受影响。 */
  const locked = () => mode === 'lesson' || mode === 'hub' || mode === 'done';

  /* 目录里的课程列表本来就该滚，别把它一起锁了。 */
  function scrollableIn(node, boundary) {
    let el = node instanceof Element ? node : null;
    while (el && el !== boundary) {
      const style = getComputedStyle(el);
      if (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight - el.clientHeight > 2) return true;
      el = el.parentElement;
    }
    return false;
  }

  function guardScroll(event) {
    if (!locked()) return;
    const hub = layer.querySelector('.tour-hub');
    if (hub && hub.contains(event.target) && scrollableIn(event.target, hub)) return;
    if (event.cancelable) event.preventDefault();
  }
  window.addEventListener('wheel', guardScroll, { passive: false, capture: true });
  window.addEventListener('touchmove', guardScroll, { passive: false, capture: true });
  document.addEventListener('keydown', (event) => {
    if (!locked() || event.metaKey || event.ctrlKey || event.altKey) return;
    if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) return;
    /* 焦点在教程自己的按钮上时，空格要能把按钮按下去。 */
    if (event.key === ' ' && layer.contains(event.target)) return;
    event.preventDefault();
  }, true);

  /* 高亮区里可以照常操作（粘贴链接、点按钮、看图）；
     只有会把页面带走的锚点要按住，免得教程跟着跑到别的页。 */
  document.addEventListener('click', (event) => {
    if (mode !== 'lesson') return;
    if (layer.contains(event.target)) return;
    const current = step();
    if (!current) return;
    const selectors = current.click
      ? (current.advanceOn || (typeof current.target === 'string' ? [current.target] : []))
      : [];
    const hit = selectors.some((selector) => {
      try { return Boolean(event.target.closest(selector)); } catch { return false; }
    });
    if (hit) { advance(); return; }
    /* 窄屏先点菜单按钮：这一下要放行，菜单打开后重画再落到菜单项上。 */
    if (current.click && typeof current.target === 'function' && event.target.closest('.menu-button')) {
      setTimeout(draw, 90);
      return;
    }
    const link = event.target.closest('a[href^="#"]');
    if (link && link.getAttribute('href') !== '#') {
      event.preventDefault();
      event.stopPropagation();
      nudge();
    }
  }, true);

  document.addEventListener('keydown', (event) => { if (active() && event.key === 'Escape') close(); });
  window.addEventListener('resize', () => { if (mode === 'lesson') draw(); });
  window.addEventListener('scroll', () => {
    if (mode !== 'lesson' || programmatic || scrollTimer) return;
    scrollTimer = setTimeout(() => { scrollTimer = null; if (!programmatic) draw(); }, 180);
  }, { passive: true });

  return {
    start() { hub(); },
    open() { hub(); },
    afterRender() {
      if (mode === 'lesson') { setTimeout(draw, 60); return; }
      if (mode !== 'idle') return;
      if (!seen) { seen = true; localStorage.setItem(SEEN_KEY, '1'); setTimeout(hub, 420); }
    },
  };
}
