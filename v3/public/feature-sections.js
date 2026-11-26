/* 板块与二级页签清单。
   外壳（导航、面包屑、页签）和 features.js 共用同一份；单独成文件是为了让 app.js
   在不 import 整个 features.js（连带十个页面模块）的情况下也能拿到它。

   2026-11-24 赛事驱动流程重整：
   - 「赛事与训练」从总容器里独立成顶层「赛事」；原容器改叫「赛训」，只留赛后笔记/复盘报告；
   - 「正式比赛录入」并入「采集」；组合池/规则/阵容标签并入「规则中心」；「数据准备」不再做顶层页。 */
export const featureSections = {
  ingest: [['ingest','营地同步']],
  matches: [['matches','单局分析'], ['featured','重点关注']],
  teams: [['teams','战队分析'], ['teamtraining','交手记录']],
  players: [['playerarchive','选手分析'], ['playercompare','选手对比'], ['metrics-observe','指标观察']],
  heroes: [['heroes','英雄榜'], ['herocompare','英雄对比'], ['teamheroes','本队英雄详情'], ['lanemetrics','分路英雄指标'], ['comboperf','英雄组合表现']],
  bp: [['bp','BP 概览'], ['coach','教练档案']],
  setup: [['match-notes','赛后笔记'], ['reports','复盘与报告']],
  rules: [['rules','规则中心'], ['combo-pool','组合池设置'], ['grade-rules','规则设置'], ['lineup-tags','阵容标签']],
  /* 先匹配（选手 / 战队 / 红蓝方），再把同一对手的几局编成系列赛。 */
  matching: [['matching','匹配'], ['series-builder','系列赛编组']],
};
