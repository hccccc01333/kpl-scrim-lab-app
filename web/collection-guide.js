const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const response = await fetch('/assets/capture-guide/requirements.json');
if (!response.ok) throw Error('采集规范读取失败，请刷新重试');
export const collectionRequirements = await response.json();


export function realCaptureExample(file,label,kind='postgame') {
 const boxes=[];
 if(kind==='postgame')for(const x of [22.8,66.4])for(let i=0;i<5;i++)boxes.push([x,19.7+i*12,9.8,3.5]);
 if(kind==='loading')for(let i=0;i<5;i++)for(const y of [33.8,88.3])boxes.push([19.4+i*12.5,y,11.3,3.8]);
 if(kind==='panel'){for(const x of [4.9,90])for(let i=0;i<5;i++)boxes.push([x,31.4+i*12.55,9,3.8]);boxes.push([48.5,29.5,6,3.3],[4.8,96,12,3.8]);}
 return `<span class="real-capture-example ${kind}"><img src="/assets/capture-guide/${esc(file)}" alt="${esc(label)} · 真实采集画面" loading="lazy">${boxes.map(([x,y,w,h])=>`<i class="capture-name-mask" aria-hidden="true" style="left:${x}%;top:${y}%;width:${w}%;height:${h}%"></i>`).join('')}</span>`;
}
const exampleLink=(file,label,kind)=>`<a class="real-capture-link" href="/assets/collection-example.html?image=${encodeURIComponent(file)}&kind=${kind}&label=${encodeURIComponent(label)}" target="_blank" rel="noopener">${realCaptureExample(file,label,kind)}<strong>${esc(label)} · 点击放大 ↗</strong></a>`;

const steps = items => `<ol class="collection-instructions">${items.map(item=>`<li>${item}</li>`).join('')}</ol>`;
const downloads = `<div class="collection-downloads"><a class="button primary" download href="/assets/capture-guide/match-template.xlsx">下载 Excel 模板</a><a class="button" download href="/assets/capture-guide/match-template.csv">空白 CSV</a><a class="button" download href="/assets/capture-guide/match-example.csv">虚构示例 CSV</a></div>`;

function officialGuide() {
  return `<p>必须是<strong>本局</strong>的王者营地网页回放链接。点击“提取并关联”成功后才算已提交，只有粘贴网址不算完成。</p>
  ${steps([
    '打开王者营地并登录本局所用的游戏账号，进入<strong>战绩</strong>，找到对应日期、英雄和比分的这一局。',
    '打开该局详情，进入<strong>对局回顾 / 复盘</strong>，先核对确实是同一局。',
    '在回顾页面的<strong>分享 / 更多</strong>里查找“复制链接”或“在浏览器打开”；如能在浏览器打开，复制地址栏里的完整网页网址。菜单名称可能随版本变化。',
    '把完整网址粘贴到本局“王者营地”输入框，点击<strong>提取并关联</strong>，核对解析出的比赛信息。不要手工删除或补写网址参数。',
  ])}
  ${exampleLink('camp-replay.png','已打开的营地网页回放；右上角为分享图标','camp')}
  <div class="collection-path-example" aria-label="链接获取路径示意"><span>战绩</span><b>→</b><span>本局详情</span><b>→</b><span>对局回顾</span><b>→</b><span>分享网页链接</span></div>
  <p class="note">最快的方式：在该局详情点<strong>分享</strong>转发到微信，复制 <code>cu.qq.com/…</code> 短链直接粘贴，短链会自动展开成回放参数，不需要打开小程序。上方路径图为示意，并非某一版本 App 的真实按钮截图。</p>
  <div class="collection-link-example"><strong>正确格式示例（占位符，不可提取）</strong><code>https://camp.qq.com/h5/webdist/battle-replay/index.html?gameseq=对局编号&amp;gamesvrentity=服务器编号&amp;relaysvrentity=转播编号&amp;playerid=玩家编号</code><p>个人回放需保留 gameseq、gamesvrentity、relaysvrentity、playerid；赛事链接保留分享时自带的全部参数。</p><strong>不能用</strong><p>只有战绩截图、营地首页、视频分享链接，或 <code>#小程序://王者营地/…</code> 这类纯文本卡片（参数不在文本里，只能由微信打开）。<code>cu.qq.com</code> 短链可以使用，粘贴后会自动展开。</p></div>
  <p class="note">官方链接用于约 30 秒经济点、事件和位置来源；逐秒位置不等于逐秒金币。审核还需营地十人面板，或七张截图与一段录屏作为兜底。</p>`;
}

function videoGuide() {
  return `<p><strong>兜底路径：一局只录一段完整视频，包含双方十人团队信息。</strong>若本局已导入营地十人面板，录屏不是必需的；只在走传统兜底路径时才需要。</p>
  ${steps([
    '<strong>从哪里开始：</strong>进入该局回放前就开始录屏，至少包含十名英雄和昵称的<strong>加载页</strong>，画面清晰后保留约 5 秒；继续录到局内 00:00。不要只从中途或高光片段开始。',
    '<strong>对局中保持：</strong>横屏、原比例、简体中文，建议 1080p / 30 fps、1 倍速；不裁切顶部比赛时钟、双方击杀和团队累计金币。不要剪辑、拖进度条或用倍速跳过过程。',
    '<strong>打开团队面板：</strong>使用显示<strong>双方各五人的 K/D/A 和累计金币</strong>的团队面板，尽量整局保持可见。单英雄技能/属性面板、底部可用金币不能替代十人团队面板。',
    '<strong>补记分板：</strong>开局约 00:30、之后约每 5 分钟，以及结束前有条件时打开十人记分板，保持完整昵称、KDA 和累计经济清楚显示，停留至少 5 秒，再关闭继续录制。不要用记分板长时间遮住主要 HUD。',
    '<strong>到哪里结束：</strong>持续录到水晶结束、胜利/失败动画，再进入本局赛后战绩页停留约 5 秒，最后停止录屏。七张赛后截图另外保存，不用把七张截图用视频替代。',
    '<strong>怎样提交：</strong>在“录屏采集”上传这一个 mp4 / mov / mkv / webm 文件（上限 2 GB）；识别完成导出一份 JSON 报告，再回本局关联。单份报告代表一段录像；仍需人工确认是否录完整。',
  ])}
  <div class="collection-real-video">${exampleLink('recording-loading.png','开始：十人加载页','loading')}${exampleLink('recording-panel.png','过程：顶部 HUD 与底部团队面板','panel')}${exampleLink('01-score-equipment.jpg','结束：赛后战绩页','postgame')}</div><p class="note">以上取自本项目实际录屏与截图，昵称区域用遮罩隐藏；录屏帧仅作面板位置说明。提交时使用原始完整视频，保证文字可读。</p>
  <div class="collection-path-example"><span>加载页约 5 秒</span><b>→</b><span>00:00 至整局结束</span><b>→</b><span>赛后战绩页约 5 秒</span></div>`;
}

function screenshotGuide() {
  return `<p><strong>兜底路径：同一局七张，七种页面各一张。</strong>若本局已导入营地十人面板，七张截图不是必需的。其中战绩要拍两种显示方式，所以“战绩、数据、输出、生存、发育、团队”六个页签最终是七张图。</p><p>在完整赛后结算页切换页面，保留顶部比分、双方全部十人、列名和底部页签；用原图，不裁剪、不拼图、不盖住数值。先拍战绩装备型，再切到战绩 KDA 占比型。</p>
  <div class="collection-seven">${collectionRequirements.screenshotPages.map((page,i)=>`<a href="/assets/collection-example.html?image=${encodeURIComponent(page.file)}&amp;kind=postgame&amp;label=${encodeURIComponent(page.label)}" target="_blank" rel="noopener">${realCaptureExample(page.file,page.label,'postgame')}<strong>${String(i+1).padStart(2,'0')} ${esc(page.label)}</strong><small>${String(i+1).padStart(2,'0')}-${esc(page.label)}.png</small></a>`).join('')}</div>
  <p class="note">以上七张来自项目内同一局真实结算画面，昵称区域以遮罩隐藏，数据与页签保留原样。七张必须来自同一局；七张“数据”页不算七种页面齐全。不同局不会因为数量够七张就自动合并。上传后检查分组、比分、时长、阵容，再关联到本局。</p>`;
}

function tableGuide() {
  return `<p><strong>表格选填。</strong>仅用于补充或校正字段。使用本项目单局十人表，一行一人，blue 五人、red 五人；每方五个分路各一人。多局或跨局汇总表走“批量导入”，不要放进本局附件。</p>${downloads}
  <p>Excel 第一张“填写模板”用于上传，第二张是明确标注的虚构示例，第三张为字段说明。把真实十人数据填入第一张；不要把虚构示例原样提交。模板表头全部保留，列可调序；不要增加标题行、合计行、合并单元格或一行多名选手。</p>
  <div class="table-scroll"><table class="data-table"><thead><tr><th>列名</th><th>值是否必填</th><th>约束与例子</th></tr></thead><tbody>${collectionRequirements.sheet.columns.map(col=>`<tr><td>${esc(col.name)}</td><td>${col.required?'必填':'未知可空'}</td><td>${esc(col.rule)}</td></tr>`).join('')}</tbody></table></div>
  <div class="collection-link-example"><strong>虚构示例片段（完整十行请下载示例）</strong><code>对局ID,日期,对手,阵营,分路,选手,英雄,击杀,死亡,助攻,经济,输出,承伤,参团率,评分,时长,胜负\nEXAMPLE-请替换,2026-11-04,示例对手,blue,对抗路,示例蓝1,吕布,1,1,3,8000,40000,30000,26.7,7.5,900,胜</code></div><p class="note">未知数值留空，不能填零冒充已测值。参团率按 62.5 表示 62.5%，不是 0.625；时长用秒。上传校验表头、十人行数、阵营/分路、日期、数值和跨局混入，错误会指出对应行列。与截图不一致时保留冲突，不静默替换截图真值。</p>`;
}

function campSyncGuide() {
  return `<p><strong>教练一个账号授权后，选手零操作</strong>：训练赛数据（BP、十人面板、出装）按选手自动增量入库，与截图数字互相校验。</p>
  ${steps([
    '<strong>准备教练号：</strong>一个能登录王者营地的账号（绑定过游戏大区角色）；在营地里<strong>添加全部选手为好友/关注</strong>，确认能打开选手的营地主页。',
    '<strong>选手战绩对教练可见：</strong>选手可以不对外公开——在营地隐私设置里把教练的账号加入可见白名单即可（或直接保持公开）。判据是同步能拉到数据。',
    '<strong>收集一个稳定上场选手的营地 ID：</strong>让这位选手（如队长）随手分享任意一局战绩到微信并复制链接，链接里 <code>userId=</code> 后面的数字就是他的营地 ID。一局详情自带<strong>双方十人面板</strong>（含对手），所以一个每场必上的号就是全队数据入口；阵容轮换大可以多配一个兜底。',
    '<strong>扫码授权：</strong>在工作台完成一次微信扫码，凭证只存本机；失效后重新扫码即可，历史数据不受影响。',
    '<strong>每天同步：</strong>点“同步营地战绩”，每位选手只拉上次之后的新局，通常一两页请求。',
  ])}
  <div class="collection-link-example"><strong>营地 ID 和角色 ID 不要混淆</strong><p>分享链接里 <code>userId=540599032</code> 是<strong>营地 ID</strong>（查询用）；<code>roleId=2081911312</code> 是<strong>游戏角色 ID</strong>（每局自动带上，不需要收集）。填错了会报“用户ID不存在”。</p>
  <strong>故障速查</strong><p>提示登录态失效（-30003）/ 登录态参数不全（-30314）/ 安全参数被拒 → token 过期，重新扫码。<br>用户ID不存在 → 营地 ID 填错，可能填成了角色 ID。<br>获取用户角色信息失败 → 角色 ID 不匹配，重试一次，持续失败反馈开发。<br>列表为空但选手打过 → 该营地账号未绑定游戏大区角色。<br>报“召唤师隐藏了个人战绩” → 选手把教练加入可见白名单，或恢复战绩公开。</p></div>
  <p class="note">只采集授权选手清单内的营地账号（通常 1–2 个稳定上场选手），凭证与数据都保存在本机；一局详情含对手阵营十人，仅随局入库。完整部署说明见 <code>docs/camp_setup.md</code>。</p>`;
}

export function renderCollectionGuide(section='all', open=false) {
  const guides = [
    ['official','王者营地链接','唯一必采 · 提取并关联本局网页回放',officialGuide],
    ['camp-sync','营地数据自动采集','推荐主路径 · 教练号授权，每天增量拉取 BP 与十人面板',campSyncGuide],
    ['video','完整录屏','兜底路径 · 与七张截图一起凑齐审核门槛',videoGuide],
    ['screenshots','七张赛后截图','兜底路径 · 与一段录屏一起凑齐审核门槛',screenshotGuide],
    ['table','标准表格','选填 · 下载模板，按字段填写',tableGuide],
  ];
  return `<section class="collection-handbook" aria-label="采集要求与示例">${guides.filter(([key])=>section==='all'||key===section).map(([key,title,subtitle,render])=>`<details class="collection-guide-panel" data-guide="${key}"${open?' open':''}><summary><span><strong>${title}</strong><small>${subtitle}</small></span><b aria-hidden="true">＋</b></summary><div class="collection-guide-body">${render()}</div></details>`).join('')}</section>`;
}
