/* 板块与二级页签清单。
   外壳（导航、面包屑、页签）和 features.js 共用同一份；单独成文件是为了让 app.js
   在不 import 整个 features.js（连带十个页面模块）的情况下也能拿到它。 */
export const featureSections = {
  ingest: [['ingest','营地同步']],
  matches: [['matches','对局档案'], ['featured','重点关注']],
  teams: [['teams','战队分析'], ['teamtraining','交手记录']],
  players: [['playerarchive','选手分析'], ['playercompare','选手对比'], ['metrics-observe','指标观察']],
  heroes: [['heroes','英雄榜'], ['herocompare','英雄对比']],
  bp: [['bp','BP 概览'], ['coach','教练档案']],
  setup: [['competitions','赛事与训练'], ['setup','数据准备'], ['official-entry','正式比赛录入'], ['match-notes','赛后笔记'], ['reports','复盘与报告'], ['combo-pool','组合池设置'], ['grade-rules','规则设置'], ['lineup-tags','阵容标签']],
};
