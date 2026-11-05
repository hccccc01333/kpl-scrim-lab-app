// 功能开关：.abc / .ope 回放文件暂不开放（升级版功能）。
// 前端所有回放入口由这里控制；把 replay 改为 true 即恢复（后端路由与解析代码始终保留）。
export const FEATURES = {replay: false};
