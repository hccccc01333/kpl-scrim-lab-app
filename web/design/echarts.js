/* 平台 ECharts 层：懒加载库 + 统一主题 + 挂载管理。
   颜色全部来自 tokens.css 的同名令牌（十六进制写死，画布读不到 CSS 变量）。
   用法：
     import {mountEChart, econOption} from '/assets/design/echarts.js';
     await mountEChart(box, econOption(points, markers)); */
import {esc} from '/assets/design/ui.js';

export const C = {
  accent: '#2563eb', accentStrong: '#1d4ed8',
  sideBlue: '#2f6db0', sideRed: '#b4513c',
  pos: '#0d7a5f', neg: '#b42318', warn: '#b45309',
  ink: '#16181d', ink2: '#3f4652', ink3: '#697080', ink4: '#9aa1ae',
  line: '#e6e9ee', lineSoft: '#eef0f4', surface: '#ffffff',
  fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
};

let libPromise = null;
function loadLib() {
  if (window.echarts) return Promise.resolve(window.echarts);
  if (!libPromise) {
    libPromise = new Promise((resolve, reject) => {
      const tag = document.createElement('script');
      tag.src = '/assets/vendor/echarts.min.js';
      tag.onload = () => resolve(window.echarts);
      tag.onerror = () => { libPromise = null; reject(new Error('ECharts 加载失败')); };
      document.head.appendChild(tag);
    });
  }
  return libPromise;
}

/* 挂载：同一容器复用实例，切数据走 setOption 全量替换；容器卸载由页面负责 disposeAll */
export async function mountEChart(el, option, {merge = false} = {}) {
  if (!el) return null;
  const echarts = await loadLib();
  let chart = echarts.getInstanceByDom(el);
  if (!chart || chart.isDisposed()) {
    el.innerHTML = '';
    chart = echarts.init(el, null, {renderer: 'canvas'});
    if (!el.__echRO) {
      el.__echRO = new ResizeObserver(() => {
        if (!chart.isDisposed()) chart.resize();
      });
      el.__echRO.observe(el);
    }
  }
  chart.setOption(option, !merge);
  return chart;
}

export function disposeECharts(root) {
  const echarts = window.echarts;
  if (!echarts || !root) return;
  root.querySelectorAll('[_echarts_instance_]').forEach(el => {
    const chart = echarts.getInstanceByDom(el);
    if (chart && !chart.isDisposed()) chart.dispose();
  });
}

/* ---------------- 主题碎片 ---------------- */
export const fmtCompact = value => {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1000) return `${(value / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return String(Math.round(value));
};
export const fmtFull = value => Number.isFinite(value)
  ? `${value > 0 ? '+' : ''}${Math.round(value).toLocaleString('zh-CN')}` : '—';
export const fmtClock = seconds =>
  `${Math.floor(seconds / 60)}:${String(Math.floor(Math.abs(seconds) % 60)).padStart(2, '0')}`;

export const axisX = ({clock = false} = {}) => ({
  type: 'value', min: 'dataMin', max: 'dataMax',
  axisLine: {show: false}, axisTick: {show: false},
  axisLabel: {
    color: C.ink4, fontSize: 10.5, fontFamily: C.fontFamily, hideOverlap: true,
    formatter: clock ? value => fmtClock(value) : null,
  },
  splitLine: {show: false},
});

export const axisY = ({compact = true} = {}) => ({
  type: 'value',
  axisLine: {show: false}, axisTick: {show: false},
  axisLabel: {
    color: C.ink4, fontSize: 10.5, fontFamily: C.fontFamily,
    formatter: compact ? value => fmtCompact(value) : null,
  },
  splitLine: {lineStyle: {color: C.lineSoft, width: 1}},
});

export const darkTip = {
  backgroundColor: 'rgba(22, 24, 29, .94)', borderWidth: 0,
  padding: [7, 11], borderRadius: 6,
  textStyle: {color: '#fff', fontSize: 12, fontWeight: 600, fontFamily: C.fontFamily},
  extraCssText: 'box-shadow: 0 6px 18px rgba(22,24,29,.25); backdrop-filter: blur(2px);',
};

export const zoomSlider = {
  type: 'slider', height: 16, bottom: 4,
  borderColor: 'transparent', backgroundColor: C.lineSoft,
  fillerColor: 'rgba(37, 99, 235, .10)',
  handleStyle: {color: C.surface, borderColor: '#c3ccd8'},
  moveHandleStyle: {color: '#c3ccd8'},
  emphasis: {handleStyle: {borderColor: C.accent}},
  dataBackground: {lineStyle: {color: '#d6dbe3'}, areaStyle: {color: '#e6e9ee'}},
  selectedDataBackground: {lineStyle: {color: C.accent}, areaStyle: {color: 'rgba(37,99,235,.12)'}},
  textStyle: {color: C.ink4, fontSize: 9},
  brushSelect: false,
};

/* 合并重叠的转折窗口 */
export function mergeMarkers(markers) {
  const merged = [];
  (markers || []).slice().sort((a, b) => a.start - b.start).forEach(marker => {
    const last = merged[merged.length - 1];
    if (last && marker.start <= last.end) {
      last.end = Math.max(last.end, marker.end);
      last.delta = Math.abs(marker.delta) > Math.abs(last.delta) ? marker.delta : last.delta;
      return;
    }
    merged.push({...marker});
  });
  return merged;
}

/* ---------------- 经济差走势（样板图） ----------------
   领先方分色：visualMap 按值切，蓝上红下；转折带内嵌结论；终点值胶囊 */
export function econOption(points, markers, {unit = '经济差（蓝 − 红）', zoom = true} = {}) {
  const data = points.map(point => [point.x, point.y]);
  const last = points[points.length - 1];
  const merged = mergeMarkers(markers);
  const pillText = fmtFull(last.y);
  return {
    color: [C.accent],
    animationDuration: 650,
    animationEasing: 'cubicOut',
    grid: {left: 10, right: 16, top: 30, bottom: zoom ? 34 : 12, containLabel: true},
    graphic: [{type: 'text', right: 10, top: 6,
      style: {text: unit, fill: C.ink4, fontSize: 10.5, fontFamily: C.fontFamily}}],
    tooltip: {
      trigger: 'axis', axisPointer: {type: 'line', lineStyle: {color: C.ink4, type: 'dashed'}},
      ...darkTip,
      formatter: params => {
        const p = params.find(item => item.seriesName === '经济差') || params[params.length - 1];
        return `${fmtClock(p.value[0])} · ${fmtFull(p.value[1])}`;
      },
    },
    xAxis: {...axisX({clock: true}), axisLabel: {...axisX({clock: true}).axisLabel, margin: 10}},
    yAxis: axisY({compact: true}),
    dataZoom: zoom ? [{type: 'inside'}, zoomSlider] : [{type: 'inside'}],
    series: [...splitAreaSeries(data), {
      type: 'line', name: '经济差', data, smooth: 0.42, showSymbol: false, symbol: 'circle', symbolSize: 6, z: 5,
      lineStyle: {width: 2.4, shadowColor: 'rgba(22, 24, 29, .08)', shadowBlur: 8, shadowOffsetY: 4},
      emphasis: {disabled: true},
      markArea: merged.length ? {
        data: merged.map(marker => [
          {
            xAxis: marker.start,
            itemStyle: {color: marker.delta > 0 ? 'rgba(47, 109, 176, .07)' : 'rgba(180, 81, 60, .07)'},
            label: {
              show: true, position: 'insideTopLeft', offset: [5, 3],
              color: marker.delta > 0 ? C.sideBlue : C.sideRed,
              fontSize: 10, fontWeight: 600, fontFamily: C.fontFamily,
              formatter: `转折 ${marker.delta > 0 ? '+' : ''}${fmtCompact(marker.delta)}`,
            },
          },
          {xAxis: marker.end},
        ]),
      } : undefined,
      markPoint: {
        silent: true,
        symbol: 'circle', symbolSize: 7,
        itemStyle: {color: C.accent, borderColor: '#fff', borderWidth: 1.5},
        label: {
          show: true, position: 'left', distance: 10,
          backgroundColor: 'rgba(22, 24, 29, .92)', borderRadius: 5, padding: [4, 9],
          color: '#fff', fontSize: 11, fontWeight: 700, fontFamily: C.fontFamily,
          formatter: () => pillText,
        },
        data: [{coord: [last.x, last.y]}],
      },
    }],
  };
}

/* 领先方分色：把曲线在零点处插值切开，正段蓝面积、负段红面积。
   主线系列只画线；两个面积系列 line 透明、area 填到零线（areaStyle origin 默认 auto）。 */
export function splitAreaSeries(data) {
  const pos = [], neg = [];
  const push = (arr, x, y) => arr.push([Number(x.toFixed(2)), y]);
  for (let i = 0; i < data.length; i += 1) {
    const [x, y] = data[i];
    if (y >= 0) { push(pos, x, y); push(neg, x, 0); }
    else { push(pos, x, 0); push(neg, x, y); }
    if (i < data.length - 1) {
      const [nx, ny] = data[i + 1];
      if ((y >= 0) !== (ny >= 0)) {
        const t = Math.abs(y) / (Math.abs(y) + Math.abs(ny) || 1);
        const xm = x + (nx - x) * t;
        push(pos, xm, 0); push(neg, xm, 0);
      }
    }
  }
  const ghost = {
    type: 'line', smooth: 0.42, showSymbol: false, silent: true, connectNulls: false,
    lineStyle: {width: 0, opacity: 0}, emphasis: {disabled: true}, z: 2,
  };
  return [
    {...ghost, id: 'area-neg', name: '对方领先段', data: neg, areaStyle: {color: C.sideRed, opacity: .09}},
    {...ghost, id: 'area-pos', name: '我方领先段', data: pos, areaStyle: {color: C.sideBlue, opacity: .11}},
  ];
}
