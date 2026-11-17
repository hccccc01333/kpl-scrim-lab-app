/* 板块与二级页签清单。
   外壳（导航、面包屑、页签）和 features.js 共用同一份；单独成文件是为了让 app.js
   在不 import 整个 features.js（连带十个页面模块）的情况下也能拿到它。 */
export const featureSections = {
  ingest: [['ingest','营地同步']],
  matches: [['matches','对局档案'], ['cross','跨局分析'], ['biggame','大场分析'], ['featured','精选对局'], ['versions','版本对比'], ['series-builder','系列赛编组']],
  teams: [['teams','战队分析'], ['teamtraining','战队训练']],
  players: [['playerarchive','选手档案'], ['playercompare','选手对比']],
  heroes: [['heroes','英雄榜'], ['herocompare','英雄对比'], ['combos','英雄组合']],
  bp: [['bp','BP 概览'], ['coach','教练档案']],
  setup: [['plan','比赛与训练'], ['setup','数据准备'], ['reports','复盘与报告']],
};
