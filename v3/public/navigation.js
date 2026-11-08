
/* 部署在子路径（如 /v3）时，接口前缀随页面前缀走；根路径下为空串。 */
const API_BASE = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
export const topicGroups = {
  matches: [
    ['time_cross_match','训练节奏','比较训练时段与整体表现'], ['time_events','资源与事件','观察事件发生的时间分布'],
    ['time_kill_rhythm','击杀节奏','查看首杀、团战与交战时间'], ['death_point_economy','掉点与经济','回看单局掉点前后的经济变化'],
  ],
  teams: [],
  players: [
    ['cs_conversion','补刀与产出','比较补刀、经济和输出'], ['cross_resource_output','经济投入与输出','查看选手的投入与产出分布'],
    ['compare_baseline','同位置参照','与同位置样本进行比较'], ['lane_matchup','分路对位','查看同分路对手与经济差'],
    ['compare_camp','蓝红阵营对照','检查不同阵营的样本偏差'],
  ],
  heroes: [
    ['cross_lane_hero','分路与英雄','查看不同位置的英雄表现'], ['equip_matrix','终局装备分布','查看各位置的装备携带情况'],
    ['equip_impact','装备与表现','比较终局装备对应的表现'], ['stability','英雄表现波动','观察英雄表现的分布'],
  ],
  bp: [['resource_bp','禁选与资源','查看禁选名单和资源情况']],
};
export const studyGroups = {
  matches: [['tempo','阶段经济','比较前期、中期与后期经济'],['swing_windows','经济变化窗口','找到值得回看的经济波动'],['session_summary','训练组汇总','按训练组查看对局与结果']],
  teams: [['hero_combos','阵容组合','观察阵容共现与基准']],
  players: [['player_form','选手状态','对比近期表现与长期分布'],['player_pairs','选手搭档','查看稳定身份下的双人搭档'],['resource_efficiency','经济与产出','比较资源投入和伤害转化']],
  heroes: [['hero_benchmark','选手英雄参照','同位置同英雄样本比较'],['hero_pool','选手英雄池','观察英雄使用集中度']],
  bp: [],
};
export function groupFor(type,id) { const groups=type==='topic'?topicGroups:studyGroups; return Object.keys(groups).find(k=>groups[k].some(item=>item[0]===id))||'matches'; }
export const groupLabel={matches:'对局',teams:'战队',players:'选手',heroes:'英雄',bp:'BP'};
