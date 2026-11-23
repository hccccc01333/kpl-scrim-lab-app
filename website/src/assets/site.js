/* ==========================================================================
   雨乐赛训 · 官网交互层
   音效（Web Audio 合成，0 个音频文件）、悬浮操作坞、滚动进度、目录轨、
   示例简报（合成数据）、折叠档案板、首访说明。
   纯原生，无依赖；所有区块以“页面上存在该元素”为前提，可复用到任何一页。
   ========================================================================== */
(function () {
  'use strict';

  var doc = document;
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  var finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');

  function pref(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
      return value;
    } catch (error) {
      return null;
    }
  }

  /* ---------- 音效：全部合成 ---------- */

  var sfx = (function () {
    var ctx = null;
    var master = null;
    var on = pref('yl-sound') !== 'off';
    var lastHover = 0;

    function tone(o) {
      if (!ctx || !master) return;
      var t0 = ctx.currentTime + (o.delay || 0);
      var dur = o.dur || 0.08;
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.type = o.type || 'sine';
      osc.frequency.setValueAtTime(o.from, t0);
      if (o.to && o.to !== o.from) {
        osc.frequency.exponentialRampToValueAtTime(o.to, t0 + dur);
      }
      gain.gain.setValueAtTime(0.0001, t0);
      gain.gain.exponentialRampToValueAtTime(o.gain || 0.06, t0 + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      osc.connect(gain);
      gain.connect(master);
      osc.start(t0);
      osc.stop(t0 + dur + 0.03);
    }

    var voices = {
      hover: function () { tone({ from: 2750, to: 2450, dur: 0.05, gain: 0.03 }); },
      click: function () {
        tone({ from: 1250, to: 900, dur: 0.06, gain: 0.05 });
        tone({ from: 720, to: 520, dur: 0.06, gain: 0.025, type: 'triangle', delay: 0.01 });
      },
      open: function () {
        tone({ from: 240, to: 520, dur: 0.13, gain: 0.05 });
        tone({ from: 480, to: 880, dur: 0.12, gain: 0.02, type: 'triangle', delay: 0.02 });
      },
      close: function () { tone({ from: 520, to: 240, dur: 0.12, gain: 0.04 }); },
      on: function () { tone({ from: 640, to: 960, dur: 0.09, gain: 0.045 }); },
      off: function () { tone({ from: 960, to: 640, dur: 0.09, gain: 0.04 }); },
      success: function () {
        [523.25, 659.25, 783.99].forEach(function (freq, i) {
          tone({ from: freq, to: freq, dur: 0.16, gain: 0.05, delay: i * 0.075 });
        });
      },
      copy: function () {
        tone({ from: 1300, to: 1300, dur: 0.035, gain: 0.028, type: 'square' });
        tone({ from: 1650, to: 1650, dur: 0.035, gain: 0.024, type: 'square', delay: 0.055 });
      },
      error: function () {
        tone({ from: 320, to: 160, dur: 0.18, gain: 0.05, type: 'sawtooth' });
      }
    };

    function unlock() {
      if (ctx) return;
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      try {
        ctx = new AC();
        master = ctx.createGain();
        master.gain.value = 0.5;
        master.connect(ctx.destination);
      } catch (error) {
        ctx = null;
      }
    }

    return {
      play: function (name) {
        if (!on || !ctx) return;
        if (ctx.state === 'suspended') ctx.resume();
        var voice = voices[name];
        if (voice) voice();
      },
      hover: function () {
        if (!on || !ctx || !finePointer.matches) return;
        var now = Date.now();
        if (now - lastHover < 80) return;
        lastHover = now;
        if (ctx.state === 'suspended') ctx.resume();
        voices.hover();
      },
      unlock: unlock,
      isOn: function () { return on; },
      set: function (next) {
        on = next;
        pref('yl-sound', on ? 'on' : 'off');
        if (on) unlock();
        if (on) voices.on(); else voices.off();
      }
    };
  })();

  doc.addEventListener('pointerdown', function () { sfx.unlock(); }, { capture: true, passive: true });
  doc.addEventListener('keydown', function () { sfx.unlock(); }, { capture: true });

  if (finePointer.matches) {
    doc.addEventListener('pointerover', function (event) {
      var el = event.target.closest('a, button, .seg label, .board-tab');
      if (!el || el.hasAttribute('data-sfx-skip')) return;
      if (event.relatedTarget && el.contains(event.relatedTarget)) return;
      sfx.hover();
    }, { passive: true });
  }

  doc.addEventListener('click', function (event) {
    var el = event.target.closest('a, button, .seg label, summary');
    if (!el || el.hasAttribute('data-sfx') || el.hasAttribute('data-sfx-skip')) return;
    sfx.play('click');
  });

  /* ---------- 悬浮操作坞 ---------- */

  var ICONS = {
    soundOn: '<svg class="icon-on" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6.5 9H3v6h3.5L11 19z"/><path d="M15.4 8.6a5 5 0 0 1 0 6.8"/><path d="M18.4 6a9 9 0 0 1 0 12"/></svg>',
    soundOff: '<svg class="icon-off" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6.5 9H3v6h3.5L11 19z"/><path d="m16 9.5 4.5 5M20.5 9.5l-4.5 5"/></svg>',
    download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11m0 0 4-4m-4 4-4-4"/><path d="M5 17v2a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2"/></svg>',
    top: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5m0 0-6 6m6-6 6 6"/></svg>'
  };

  var dock = doc.createElement('div');
  dock.className = 'dock';
  dock.innerHTML =
    '<button class="dock-btn" type="button" data-sound aria-pressed="' + (sfx.isOn() ? 'true' : 'false') + '"' +
    ' data-on="' + (sfx.isOn() ? 'true' : 'false') + '" aria-label="界面音效：' + (sfx.isOn() ? '开' : '关') + '"' +
    ' title="界面音效">' + ICONS.soundOn + ICONS.soundOff + '</button>' +
    '<a class="dock-btn" data-dock-download href="download.html" aria-label="下载 Windows 版" title="下载 Windows 版">' + ICONS.download + '</a>' +
    '<button class="dock-btn" type="button" data-top aria-label="回到顶部" title="回到顶部">' + ICONS.top + '</button>';
  doc.body.appendChild(dock);

  var soundBtn = dock.querySelector('[data-sound]');
  var topBtn = dock.querySelector('[data-top]');

  if (soundBtn) {
    soundBtn.setAttribute('data-sfx-skip', '');
    soundBtn.addEventListener('click', function () {
      var next = !sfx.isOn();
      sfx.set(next);
      soundBtn.setAttribute('aria-pressed', next ? 'true' : 'false');
      soundBtn.setAttribute('data-on', next ? 'true' : 'false');
      soundBtn.setAttribute('aria-label', '界面音效：' + (next ? '开' : '关'));
    });
  }

  if (topBtn) {
    topBtn.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: reduce.matches ? 'auto' : 'smooth' });
    });
  }

  /* ---------- 滚动条宽度：给首屏出血用 ---------- */

  function syncScrollbar() {
    var width = window.innerWidth - doc.documentElement.clientWidth;
    doc.documentElement.style.setProperty('--sbw', Math.max(0, width) + 'px');
  }

  syncScrollbar();
  window.addEventListener('resize', syncScrollbar, { passive: true });

  /* ---------- 首屏截图视差 ---------- */

  (function () {
    var frame = doc.querySelector('.hero-visual .frame');
    if (!frame || reduce.matches) return;
    var ticking = false;
    function shift() {
      ticking = false;
      var y = window.pageYOffset || doc.documentElement.scrollTop;
      if (y > window.innerHeight * 1.2) return;
      frame.style.translate = '0 ' + (y * -0.06).toFixed(1) + 'px';
    }
    window.addEventListener('scroll', function () {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(shift);
    }, { passive: true });
  })();

  /* ---------- 滚动：进度条、吸顶阴影、回顶按钮 ---------- */

  var topbar = doc.querySelector('.topbar');
  var progressBar = doc.querySelector('.topbar-progress i');
  var ticking = false;

  function onScroll() {
    var y = window.pageYOffset || doc.documentElement.scrollTop;
    var max = doc.documentElement.scrollHeight - window.innerHeight;
    if (progressBar) {
      progressBar.style.setProperty('--progress', max > 0 ? Math.min(1, y / max).toFixed(4) : 0);
    }
    if (topbar) topbar.classList.toggle('is-stuck', y > 4);
    dock.classList.toggle('is-scrolled', y > 520);
    syncSpy(y);
  }

  window.addEventListener('scroll', function () {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(function () {
      ticking = false;
      onScroll();
    });
  }, { passive: true });

  window.addEventListener('resize', onScroll, { passive: true });

  /* ---------- 目录轨：当前分区 ---------- */

  var spyLinks = Array.prototype.slice.call(doc.querySelectorAll('[data-spy]'));
  var spyIds = [];
  spyLinks.forEach(function (link) {
    var id = link.getAttribute('data-spy');
    if (id && spyIds.indexOf(id) === -1) spyIds.push(id);
  });
  var spySections = spyIds.map(function (id) { return doc.getElementById(id); }).filter(Boolean);
  var lastSpy = null;

  function syncSpy(y) {
    if (!spySections.length) return;
    var active = null;
    var line = y + 160;
    spySections.forEach(function (section) {
      if (section.offsetTop <= line) active = section.id;
    });
    if (active === lastSpy) return;
    lastSpy = active;
    spyLinks.forEach(function (link) {
      if (active && link.getAttribute('data-spy') === active) {
        link.setAttribute('aria-current', 'location');
      } else {
        link.removeAttribute('aria-current');
      }
    });
  }

  /* ---------- 滚动渐显 ---------- */

  (function () {
    var items = doc.querySelectorAll('[data-reveal]');
    if (!items.length) return;
    if (reduce.matches || !('IntersectionObserver' in window)) {
      Array.prototype.forEach.call(items, function (el) { el.classList.add('is-in'); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        io.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -6% 0px' });
    Array.prototype.forEach.call(items, function (el) { io.observe(el); });

    var pending = Array.prototype.slice.call(items);
    function sweep() {
      if (!pending.length) return;
      var bottom = window.innerHeight;
      pending = pending.filter(function (el) {
        if (el.getBoundingClientRect().top < bottom) {
          el.classList.add('is-in');
          io.unobserve(el);
          return false;
        }
        return true;
      });
      if (!pending.length) window.removeEventListener('scroll', sweep);
    }
    window.addEventListener('scroll', sweep, { passive: true });
  })();

  /* ---------- 移动端菜单 ---------- */

  (function () {
    var dialog = doc.getElementById('site-menu');
    var toggle = doc.querySelector('.nav-toggle');
    if (!dialog || !toggle) return;
    var close = dialog.querySelector('.menu-close');
    toggle.addEventListener('click', function () {
      dialog.showModal();
      toggle.setAttribute('aria-expanded', 'true');
      sfx.play('open');
    });
    if (close) close.addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener('close', function () {
      toggle.setAttribute('aria-expanded', 'false');
    });
    dialog.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () { dialog.close(); });
    });
  })();

  /* ---------- 复制终端命令 ---------- */

  (function () {
    doc.querySelectorAll('.copy-btn').forEach(function (btn) {
      btn.setAttribute('data-sfx-skip', '');
      btn.addEventListener('click', function () {
        var code = btn.closest('.terminal') && btn.closest('.terminal').querySelector('code');
        if (!code) return;
        var text = code.textContent;
        function done() {
          btn.textContent = '已复制';
          btn.classList.add('is-done');
          sfx.play('success');
          setTimeout(function () {
            btn.textContent = '复制';
            btn.classList.remove('is-done');
          }, 1600);
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, done);
        } else {
          var area = doc.createElement('textarea');
          area.value = text;
          area.style.position = 'fixed';
          area.style.opacity = '0';
          doc.body.appendChild(area);
          area.select();
          try { doc.execCommand('copy'); } catch (error) {}
          doc.body.removeChild(area);
          done();
        }
      });
    });
  })();

  /* ---------- 复制仓库地址 / 邮箱等 ---------- */

  (function () {
    function copyText(text, done) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, done);
        return;
      }
      var area = doc.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      doc.body.appendChild(area);
      area.select();
      try { doc.execCommand('copy'); } catch (error) {}
      doc.body.removeChild(area);
      done();
    }

    doc.querySelectorAll('[data-copy]').forEach(function (btn) {
      btn.setAttribute('data-sfx-skip', '');
      btn.addEventListener('click', function () {
        var text = btn.getAttribute('data-copy');
        if (!text) return;
        var original = btn.textContent;
        copyText(text, function () {
          btn.textContent = btn.getAttribute('data-copied') || '已复制';
          btn.classList.add('is-done');
          sfx.play('success');
          window.setTimeout(function () {
            btn.textContent = original;
            btn.classList.remove('is-done');
          }, 1800);
        });
      });
    });
  })();

  /* ---------- 示例简报 ---------- */

  (function () {
    var root = doc.querySelector('[data-brief]');
    if (!root) return;

    var svg = root.querySelector('[data-chart-svg]');
    var plot = root.querySelector('.chart-plot');
    var tip = root.querySelector('[data-chart-tip]');
    var cap = root.querySelector('[data-chart-cap]');
    var kpiMain = root.querySelector('[data-kpi-main]');
    var kpiUnit = root.querySelector('[data-kpi-unit]');
    var kpiGap = root.querySelector('[data-kpi-gap]');
    var kpiTrend = root.querySelector('[data-kpi-trend]');
    var kpiLabel = root.querySelector('[data-kpi-label]');
    var kpiGames = root.querySelector('[data-kpi-games]');
    var kpiPrev = root.querySelector('[data-kpi-prev]');
    var metaGames = root.querySelector('[data-meta-games]');
    var metaShots = root.querySelector('[data-meta-shots]');
    var metaReplay = root.querySelector('[data-meta-replay]');

    var PERIODS = {
      week: { games: 6, prev: '上周' },
      month: { games: 9, prev: '上月' },
      season: { games: 12, prev: '上赛季' }
    };

    var METRICS = {
      gold: { title: '分均经济', unit: 'k', dec: 1, base: [3.04, 2.82], spread: 0.2, min: 0 },
      tower: { title: '场均推塔', unit: '座', dec: 1, base: [8.6, 6.9], spread: 1.3, min: 0 },
      fight: { title: '参团率', unit: '%', deltaUnit: 'pt', dec: 0, base: [71, 65], spread: 6, min: 0, max: 100 },
      vision: { title: '视野得分', unit: '分', dec: 0, base: [176, 158], spread: 17, min: 0 }
    };

    function rng(seed) {
      return function () {
        seed |= 0;
        seed = (seed + 0x6d2b79f5) | 0;
        var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    }

    function hash(text) {
      var h = 0;
      for (var i = 0; i < text.length; i += 1) h = (h * 31 + text.charCodeAt(i)) | 0;
      return Math.abs(h);
    }

    function clamp(value, min, max) {
      if (value < min) return min;
      if (max !== undefined && value > max) return max;
      return value;
    }

    function build(periodKey, metricKey, salt) {
      var period = PERIODS[periodKey];
      var metric = METRICS[metricKey];
      var rand = rng(period.games * 97 + hash(metricKey) + hash(periodKey) * 13 + (salt || 0));
      var a = [];
      var b = [];

      for (var i = 0; i < period.games; i += 1) {
        a.push(clamp(metric.base[0] + (rand() - 0.5) * 2 * metric.spread, metric.min, metric.max));
        b.push(clamp(metric.base[1] + (rand() - 0.5) * 2 * metric.spread, metric.min, metric.max));
      }

      return {
        a: a,
        b: b,
        n: period.games,
        meanA: mean(a),
        meanB: mean(b)
      };
    }

    function mean(list) {
      return list.reduce(function (sum, v) { return sum + v; }, 0) / list.length;
    }

    function decimals(metric, value) {
      if (metric.dec === 0) return String(Math.round(value));
      return value.toFixed(1);
    }

    function withUnit(metric, value) {
      return decimals(metric, value) + metric.unit;
    }

    function signed(metric, value) {
      var unit = metric.deltaUnit || metric.unit;
      var magnitude = decimals(metric, Math.abs(value));
      var sign = parseFloat(magnitude) === 0 ? '' : value > 0 ? '+' : '−';
      return sign + magnitude + unit;
    }

    var state = { period: 'week', metric: 'gold' };
    var shown = { main: 0, gap: 0, trend: 0 };

    function formatAxis(value) {
      if (Math.abs(value) >= 100) return String(Math.round(value));
      if (Math.abs(value) >= 10) return value.toFixed(0);
      return value.toFixed(1);
    }

    var W = 760;
    var H = 300;
    var PAD = { l: 46, r: 16, t: 18, b: 32 };

    function render() {
      var metric = METRICS[state.metric];
      var data = build(state.period, state.metric, 0);
      var prev = build(state.period, state.metric, 911);

      /* 以容器实际宽度作坐标系，1 单位 = 1 像素：手机上轴标签不会被缩成 5px */
      var measured = plot ? plot.clientWidth : 0;
      W = Math.max(280, Math.round(measured || 760));
      H = W < 520 ? 210 : Math.round(Math.min(300, W * 0.43));
      PAD = { l: W < 520 ? 38 : 46, r: W < 520 ? 40 : 54, t: 18, b: 32 };
      svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);

      var all = data.a.concat(data.b);
      var lo = Math.min.apply(null, all);
      var hi = Math.max.apply(null, all);
      var pad = (hi - lo) * 0.22 || Math.abs(hi) * 0.08 || 1;
      lo -= pad;
      hi += pad;
      if (metric.min !== undefined) lo = Math.max(metric.min, lo);
      if (metric.max !== undefined) hi = Math.min(metric.max, hi);

      var innerW = W - PAD.l - PAD.r;
      var innerH = H - PAD.t - PAD.b;
      var step = innerW / (data.n - 1);

      function px(i) { return PAD.l + step * i; }
      function py(v) { return PAD.t + innerH * (1 - (v - lo) / (hi - lo)); }

      function line(values) {
        return values.map(function (v, i) {
          return (i ? 'L' : 'M') + px(i).toFixed(1) + ' ' + py(v).toFixed(1);
        }).join(' ');
      }

      var parts = ['<defs><clipPath id="brief-clip"><rect class="ch-wipe" x="0" y="0" width="' + W + '" height="' + H + '"/></clipPath></defs>'];

      for (var g = 0; g < 4; g += 1) {
        var value = lo + ((hi - lo) * g) / 3;
        var y = py(value);
        parts.push('<line class="ch-grid" x1="' + PAD.l + '" x2="' + (W - PAD.r) + '" y1="' + y.toFixed(1) + '" y2="' + y.toFixed(1) + '"/>');
        parts.push('<text class="ch-axis" x="' + (PAD.l - 10) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end">' + formatAxis(value) + '</text>');
      }

      var labelEvery = data.n > 8 ? 2 : 1;
      for (var i = 0; i < data.n; i += 1) {
        if (i % labelEvery !== 0 && i !== data.n - 1) continue;
        parts.push('<text class="ch-axis" x="' + px(i).toFixed(1) + '" y="' + (H - 10) + '" text-anchor="middle">G' + (i + 1) + '</text>');
      }

      parts.push('<g clip-path="url(#brief-clip)">');
      parts.push('<path class="ch-line ch-line--a" d="' + line(data.a) + '"/>');
      parts.push('<path class="ch-line ch-line--b" d="' + line(data.b) + '"/>');
      parts.push('</g>');

      /* 线尾直接标注：不放图例框 */
      var tagY = py(data.a[data.n - 1]);
      var tagYb = py(data.b[data.n - 1]);
      if (Math.abs(tagY - tagYb) < 13) {
        if (tagY <= tagYb) { tagY -= 7; tagYb += 7; } else { tagY += 7; tagYb -= 7; }
      }
      var tagX = (W - PAD.r + 7).toFixed(1);
      parts.push('<text class="ch-tag ch-tag--a" x="' + tagX + '" y="' + (tagY + 3.5).toFixed(1) + '">我方</text>');
      parts.push('<text class="ch-tag ch-tag--b" x="' + tagX + '" y="' + (tagYb + 3.5).toFixed(1) + '">对手</text>');

      parts.push('<line class="ch-cursor" x1="0" x2="0" y1="' + PAD.t + '" y2="' + (H - PAD.b) + '"/>');
      parts.push('<circle class="ch-dot ch-dot--a" r="4.5" cx="0" cy="0"/>');
      parts.push('<circle class="ch-dot ch-dot--b" r="4.5" cx="0" cy="0"/>');

      svg.innerHTML = '<title>' + metric.title + '走势（合成示例）</title>' + parts.join('');

      kpiLabel.textContent = metric.title;
      kpiGames.textContent = data.n;
      if (metaGames) metaGames.textContent = data.n;
      if (metaShots) metaShots.textContent = Math.ceil(data.n * 0.6);
      if (metaReplay) metaReplay.textContent = data.n - Math.ceil(data.n * 0.6);

      var gap = data.meanA - data.meanB;
      var trend = data.meanA - prev.meanA;

      animate(kpiMain, 'main', data.meanA, metric);
      animate(kpiGap, 'gap', gap, metric, true);
      animate(kpiTrend, 'trend', trend, metric, true);

      kpiUnit.textContent = metric.unit;
      kpiPrev.textContent = PERIODS[state.period].prev;

      kpiGap.setAttribute('data-tone', gap >= 0 ? 'up' : 'down');
      kpiTrend.setAttribute('data-tone', trend >= 0 ? 'up' : 'down');

      var summary = data.n + ' 局均值 · 我方 ' + withUnit(metric, data.meanA) + ' / 对手 ' +
        withUnit(metric, data.meanB) + ' · 环比 ' + signed(metric, trend);
      cap.textContent = summary;
      svg.setAttribute('aria-label', metric.title + '走势：' + summary);

      plot.classList.remove('is-drawn');
      if (reduce.matches) {
        plot.classList.add('is-drawn');
      } else {
        void plot.offsetWidth;
        plot.classList.add('is-drawn');
      }
      chartData = {
        data: data, metric: metric, px: px, py: py, step: step,
        lo: lo, hi: hi, w: W, h: H, pad: PAD
      };
      hideTip();
    }

    var chartData = null;

    function animate(el, key, target, metric, sign) {
      var from = shown[key] || 0;
      shown[key] = target;
      var fmt = sign ? signed : function (m, v) { return decimals(m, v); };
      if (reduce.matches) {
        el.textContent = fmt(metric, target);
        return;
      }
      var start = performance.now();
      var duration = 520;
      function tick(now) {
        var t = Math.min(1, (now - start) / duration);
        var eased = 1 - Math.pow(1 - t, 3);
        el.textContent = fmt(metric, from + (target - from) * eased);
        if (t < 1) window.requestAnimationFrame(tick);
      }
      window.requestAnimationFrame(tick);
    }

    function hideTip() {
      if (!tip) return;
      tip.hidden = true;
      plot.classList.remove('is-hover');
    }

    function showTipAt(index) {
      if (!chartData || !tip) return;
      var d = chartData;
      var rect = svg.getBoundingClientRect();
      if (!rect.width) return;
      var scale = rect.width / d.w;
      var x = d.px(index) * scale;
      var yA = d.py(d.data.a[index]) * scale;
      var yB = d.py(d.data.b[index]) * scale;

      var cursor = svg.querySelector('.ch-cursor');
      var dotA = svg.querySelector('.ch-dot--a');
      var dotB = svg.querySelector('.ch-dot--b');
      if (cursor) {
        cursor.setAttribute('x1', d.px(index));
        cursor.setAttribute('x2', d.px(index));
      }
      if (dotA) { dotA.setAttribute('cx', d.px(index)); dotA.setAttribute('cy', d.py(d.data.a[index])); }
      if (dotB) { dotB.setAttribute('cx', d.px(index)); dotB.setAttribute('cy', d.py(d.data.b[index])); }

      tip.innerHTML = '<b>G' + (index + 1) + '</b>' +
        '<span><i class="tip-a">我方</i>' + withUnit(d.metric, d.data.a[index]) + '</span>' +
        '<span><i class="tip-b">对手</i>' + withUnit(d.metric, d.data.b[index]) + '</span>';
      var offset = Math.min(Math.max(x, 76), Math.max(76, rect.width - 76));
      tip.style.left = offset + 'px';
      tip.style.top = Math.min(yA, yB) + 'px';
      tip.hidden = false;
      plot.classList.add('is-hover');
    }

    if (plot) {
      plot.addEventListener('pointermove', function (event) {
        if (event.pointerType === 'touch' || !chartData) return;
        var rect = svg.getBoundingClientRect();
        if (!rect.width) return;
        var x = ((event.clientX - rect.left) / rect.width) * W;
        var index = Math.round((x - PAD.l) / chartData.step);
        index = Math.max(0, Math.min(chartData.data.n - 1, index));
        showTipAt(index);
      });
      plot.addEventListener('pointerleave', hideTip);
    }

    Array.prototype.forEach.call(root.querySelectorAll('input[name="brief-period"]'), function (input) {
      input.addEventListener('change', function () {
        state.period = input.value;
        render();
      });
    });

    Array.prototype.forEach.call(root.querySelectorAll('input[name="brief-metric"]'), function (input) {
      input.addEventListener('change', function () {
        state.metric = input.value;
        render();
      });
    });

    var resizeTimer = 0;
    window.addEventListener('resize', function () {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(render, 180);
    }, { passive: true });

    render();
  })();

  /* ---------- 四步链路 ---------- */

  (function () {
    var board = doc.querySelector('[data-board]');
    if (!board) return;
    var tabs = Array.prototype.slice.call(board.querySelectorAll('.board-tab'));
    var panels = Array.prototype.slice.call(board.querySelectorAll('.board-panel'));
    var indicator = board.querySelector('.board-indicator');
    var ghost = doc.querySelector('[data-board-ghost]');
    if (!tabs.length || tabs.length !== panels.length) return;
    var current = 0;

    function place() {
      if (!indicator) return;
      var tab = tabs[current];
      if (!tab) return;
      indicator.style.left = tab.offsetLeft + 'px';
      indicator.style.width = tab.offsetWidth + 'px';
    }

    function open(index) {
      current = index;
      tabs.forEach(function (tab, i) {
        var on = i === index;
        tab.classList.toggle('is-open', on);
        tab.setAttribute('aria-expanded', on ? 'true' : 'false');
      });
      panels.forEach(function (panel, i) {
        panel.classList.toggle('is-open', i === index);
      });
      place();
      if (ghost) {
        ghost.textContent = '0' + (index + 1);
        ghost.classList.remove('is-in');
        void ghost.offsetWidth;
        ghost.classList.add('is-in');
      }
    }

    tabs.forEach(function (tab, index) {
      tab.setAttribute('data-sfx-skip', '');
      tab.addEventListener('click', function () {
        if (index === current) return;
        open(index);
        sfx.play('open');
      });
    });

    open(0);
    window.requestAnimationFrame(function () {
      board.classList.add('is-init');
    });

    var resizeTimer = 0;
    window.addEventListener('resize', function () {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(place, 120);
    }, { passive: true });
  })();

  /* ---------- 数据流细线：从 data/ 绕到承诺之下 ---------- */

  (function () {
    var flow = doc.querySelector('[data-flow]');
    if (!flow) return;
    var grid = flow.parentElement;
    var card = grid.querySelector('.data-card');
    var copy = grid.querySelector('.privacy-copy');
    if (!card || !copy) return;

    var segH1 = flow.querySelector('.flow-h1');
    var segV = flow.querySelector('.flow-v');
    var segH2 = flow.querySelector('.flow-h2');
    var dot = flow.querySelector('.flow-dot');

    function draw() {
      if (window.innerWidth < 1080) {
        flow.style.display = 'none';
        return;
      }
      flow.style.display = '';

      var g = grid.getBoundingClientRect();
      var c = card.getBoundingClientRect();
      var l = copy.getBoundingClientRect();

      var xCard = c.left - g.left;
      var yTop = c.top - g.top + 26;
      var lane = Math.max(24, xCard - 34);
      var yBottom = l.bottom - g.top + 26;
      var xEnd = l.left - g.left + 44;
      if (yBottom <= yTop + 40) yBottom = yTop + 40;

      segH1.style.left = lane + 'px';
      segH1.style.top = yTop + 'px';
      segH1.style.width = Math.max(0, xCard - lane) + 'px';

      segV.style.left = lane + 'px';
      segV.style.top = yTop + 'px';
      segV.style.height = Math.max(0, yBottom - yTop) + 'px';

      segH2.style.left = xEnd + 'px';
      segH2.style.top = yBottom + 'px';
      segH2.style.width = Math.max(0, lane - xEnd) + 'px';

      dot.style.left = xEnd - 2 + 'px';
      dot.style.top = yBottom - 2 + 'px';
    }

    draw();

    function reveal() {
      flow.classList.add('is-drawn');
    }

    if ('IntersectionObserver' in window && !reduce.matches) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          reveal();
          io.disconnect();
        });
      }, { rootMargin: '0px 0px -12% 0px' });
      io.observe(grid);
    } else {
      reveal();
    }

    var timer = 0;
    window.addEventListener('resize', function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(draw, 120);
    }, { passive: true });

    if ('ResizeObserver' in window) {
      new ResizeObserver(draw).observe(grid);
    }
  })();

  /* ---------- 打印时展开所有折叠项 ---------- */

  (function () {
    var items = Array.prototype.slice.call(doc.querySelectorAll('details'));
    if (!items.length) return;
    var state = [];
    window.addEventListener('beforeprint', function () {
      state = items.map(function (item) { return item.open; });
      items.forEach(function (item) { item.open = true; });
    });
    window.addEventListener('afterprint', function () {
      items.forEach(function (item, i) { item.open = state[i] || false; });
    });
  })();

  /* ---------- 赞助说明 ---------- */

  (function () {
    var dialog = doc.getElementById('sponsor');
    var opener = doc.querySelector('[data-sponsor-open]');
    if (!dialog || typeof dialog.showModal !== 'function') return;

    if (opener) {
      opener.addEventListener('click', function (event) {
        event.preventDefault();
        dialog.showModal();
        sfx.play('open');
      });
    }

    var close = dialog.querySelector('[data-sponsor-close]');
    if (close) close.addEventListener('click', function () { dialog.close('dismiss'); });

    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) dialog.close('dismiss');
    });

    dialog.addEventListener('close', function () { sfx.play('close'); });
  })();

  /* ---------- 首访说明 ---------- */

  (function () {
    var dialog = doc.getElementById('welcome');
    // 首访弹窗已停用：内容直接落在页面上，不再打断阅读。
    return;
    if (!dialog || typeof dialog.showModal !== 'function') return;
    if (window.location.hash) return;

    var version = doc.body.getAttribute('data-version') || 'v0';
    var key = 'yl-welcome-' + version;
    if (pref(key)) return;

    window.setTimeout(function () {
      if (dialog.open) return;
      dialog.showModal();
      sfx.play('open');
    }, 1500);

    dialog.addEventListener('close', function () {
      pref(key, '1');
      sfx.play('close');
    });

    var close = dialog.querySelector('[data-welcome-close]');
    if (close) close.addEventListener('click', function () { dialog.close('dismiss'); });

    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) dialog.close('dismiss');
    });
  })();

  /* ---------- 赛训简报演示（对齐 2.0 工作台首页） ---------- */

  (function () {
    var root = doc.querySelector('[data-demo]');
    if (!root) return;

    var svg = root.querySelector('[data-ov-svg]');
    var chipsEl = root.querySelector('[data-ov-chips]');
    var lineupEl = root.querySelector('[data-ov-lineup]');
    var scoreEl = root.querySelector('[data-ov-score]');
    var resultEl = root.querySelector('[data-ov-result]');
    var metaEl = root.querySelector('[data-ov-meta]');
    var periodEl = root.querySelector('[data-ov-period]');
    var readoutEl = root.querySelector('[data-ov-readout]');
    var rangeButtons = root.querySelectorAll('[data-ov-range]');

    var ROSTER = [['廉颇'], ['澜'], ['沈梦溪'], ['公孙离'], ['张飞']];

    // 合成示例数据：五局，按时间从新到旧。全部数字仅用于演示。
    var GAMES = [
      {
        ka: 9, kb: 9, dur: 18.7, result: 'win', date: '11-16 21:04', day: '2026-11-16',
        diff: [[0, 0], [2, 180], [4, 120], [6, -90], [8, -260], [10, -120], [12, 140], [14, 520], [16, 880], [18, 1240]]
      },
      {
        ka: 12, kb: 6, dur: 16.3, result: 'win', date: '11-15 20:12', day: '2026-11-15',
        diff: [[0, 0], [2, 260], [4, 480], [6, 420], [8, 760], [10, 1120], [12, 980], [14, 1460], [16, 1820]]
      },
      {
        ka: 7, kb: 11, dur: 21.1, result: 'loss', date: '11-14 19:38', day: '2026-11-14',
        diff: [[0, 0], [3, -280], [6, -560], [9, -480], [12, -860], [15, -1210], [18, -1520], [21, -1780]]
      },
      {
        ka: 10, kb: 8, dur: 19.4, result: 'win', date: '11-13 20:41', day: '2026-11-13',
        diff: [[0, 0], [2, -140], [4, 80], [6, 340], [8, 260], [10, 620], [12, 480], [14, 940], [16, 1180], [19, 1420]]
      },
      {
        ka: 6, kb: 12, dur: 20.6, result: 'loss', date: '11-10 19:22', day: '2026-11-10',
        diff: [[0, 0], [3, 120], [6, -180], [9, -520], [12, -740], [15, -980], [18, -1340], [20, -1620]]
      }
    ];

    var state = { game: 0, range: '3' };

    function visible() {
      return state.range === '3' ? GAMES.slice(0, 3) : GAMES;
    }

    function fmtClock(minute) {
      var m = Math.floor(minute);
      var s = Math.round((minute - m) * 60);
      if (s === 60) { m += 1; s = 0; }
      return m + ':' + (s < 10 ? '0' : '') + s;
    }

    function fmtDiff(value) {
      var k = value / 1000;
      if (Math.abs(k) < 0.05) return '0.0k';
      return (k > 0 ? '+' : '−') + Math.abs(k).toFixed(1) + 'k';
    }

    function resetReadout() {
      readoutEl.textContent = '点图上的点，看那一分钟的经济差。';
      readoutEl.classList.remove('is-active');
    }

    function showPoint(minute, value) {
      readoutEl.textContent = '第 ' + minute + ' 分钟 · 本队经济差 ' + fmtDiff(value) +
        '（' + (value > 0 ? '领先' : value < 0 ? '落后' : '持平') + '）';
      readoutEl.classList.add('is-active');
    }

    function renderChart() {
      var game = GAMES[state.game];
      var pts = game.diff;
      var W = Math.max(280, Math.round(svg.parentElement.clientWidth || 640));
      var H = W < 480 ? 170 : 240;
      var PAD = { l: W < 480 ? 40 : 52, r: 14, t: 14, b: 22 };
      svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);

      var maxAbs = Math.max.apply(null, pts.map(function (p) { return Math.abs(p[1]); }));
      var limit = Math.max(2000, Math.ceil(maxAbs / 1000) * 1000);
      var values = pts.map(function (p) { return p[1]; });
      var low = Math.min.apply(null, values) < 0 ? -limit : 0;
      var high = limit;

      var innerW = W - PAD.l - PAD.r;
      var innerH = H - PAD.t - PAD.b;

      function x(m) { return PAD.l + (m / game.dur) * innerW; }
      function y(v) { return PAD.t + innerH * (1 - (v - low) / (high - low)); }
      function path() {
        return pts.map(function (p, i) {
          return (i ? 'L' : 'M') + x(p[0]).toFixed(1) + ' ' + y(p[1]).toFixed(1);
        }).join(' ');
      }
      function tickLabel(v) {
        if (v === 0) return '0';
        return (v > 0 ? '+' : '−') + Math.abs(v / 1000).toFixed(0) + 'k';
      }

      var zero = y(0).toFixed(1);
      var area = path() + ' L' + x(game.dur).toFixed(1) + ' ' + zero + ' L' + PAD.l + ' ' + zero + ' Z';

      var parts = [];
      for (var i = 0; i <= 2; i += 1) {
        var value = low + ((high - low) * i) / 2;
        var yy = y(value).toFixed(1);
        parts.push('<line class="ov-grid" x1="' + PAD.l + '" x2="' + (W - PAD.r) + '" y1="' + yy + '" y2="' + yy + '"/>');
        parts.push('<text class="ov-axis" x="' + (PAD.l - 8) + '" y="' + (Number(yy) + 4) + '" text-anchor="end">' + tickLabel(value) + '</text>');
      }
      parts.push('<line class="ov-zero" x1="' + PAD.l + '" x2="' + (W - PAD.r) + '" y1="' + zero + '" y2="' + zero + '"/>');
      parts.push('<path class="ov-area" d="' + area + '"/>');
      parts.push('<path class="ov-line" d="' + path() + '"/>');
      // 每个采样点都是可点击、可用键盘聚焦的控件
      pts.forEach(function (pt) {
        var label = '第 ' + pt[0] + ' 分钟，本队经济差 ' + fmtDiff(pt[1]);
        parts.push('<circle class="ov-point" cx="' + x(pt[0]).toFixed(1) + '" cy="' + y(pt[1]).toFixed(1) +
          '" r="5" tabindex="0" role="button" aria-label="' + label + '"' +
          ' data-minute="' + pt[0] + '" data-value="' + pt[1] + '"/>');
      });
      svg.innerHTML = parts.join('');
    }

    function paintLineup() {
      lineupEl.innerHTML = ROSTER.map(function (hero) {
        return '<span class="ov-slot"><i aria-hidden="true">' + hero[0].slice(0, 1) + '</i><small>' + hero[0] + '</small></span>';
      }).join('');
    }

    function paintChips() {
      var list = visible();
      chipsEl.innerHTML = list.map(function (game) {
        var i = GAMES.indexOf(game);
        return '<button type="button" class="ov-chip ' + (game.result === 'win' ? 'is-win' : 'is-loss') +
          (i === state.game ? ' is-on' : '') + '" data-ov-chip="' + i + '"' +
          ' aria-label="' + game.date + ' 对局，' + (game.result === 'win' ? '胜利' : '失利') + '"' +
          ' aria-pressed="' + (i === state.game ? 'true' : 'false') + '">' +
          (game.result === 'win' ? '胜' : '负') + '</button>';
      }).join('');
    }

    function paintStats() {
      var list = visible();
      var wins = list.filter(function (g) { return g.result === 'win'; }).length;
      var avgDur = list.reduce(function (s, g) { return s + g.dur; }, 0) / list.length;
      var avgDiff = list.reduce(function (s, g) { return s + g.diff[g.diff.length - 1][1]; }, 0) / list.length;
      root.querySelector('[data-ov-stat-total]').innerHTML = list.length + '<small>局</small>';
      root.querySelector('[data-ov-stat-wr]').innerHTML = Math.round(wins / list.length * 100) + '<small>%</small>';
      root.querySelector('[data-ov-stat-dur]').textContent = fmtClock(avgDur);
      root.querySelector('[data-ov-stat-gold]').textContent = fmtDiff(avgDiff);
      root.querySelector('[data-ov-total]').textContent = list.length;
      root.querySelector('[data-ov-wins]').textContent = wins;
      root.querySelector('[data-ov-losses]').textContent = list.length - wins;
      root.querySelector('[data-ov-note]').textContent = list.length + ' 局记录，' + list.length + ' 局有可用的经济时间轴。';
      root.querySelector('[data-ov-stat-total]').nextElementSibling.textContent = list.length + ' 局时间轴完整';
      root.querySelector('[data-ov-stat-wr]').nextElementSibling.textContent = wins + ' 胜 / ' + list.length + ' 局';
      var days = list.map(function (g) { return g.day; }).sort();
      periodEl.textContent = days[0] + ' → ' + days[days.length - 1] + ' · ' + list.length + ' 局';
    }

    function select(index) {
      state.game = index;
      var game = GAMES[index];
      scoreEl.innerHTML = game.ka + '<span>:</span>' + game.kb;
      resultEl.textContent = game.result === 'win' ? '胜利' : '失利';
      resultEl.setAttribute('data-result', game.result);
      metaEl.textContent = game.date + ' / ' + fmtClock(game.dur) + ' / 训练赛';
      resetReadout();
      renderChart();
      paintChips();
    }

    chipsEl.addEventListener('click', function (event) {
      var chip = event.target.closest('[data-ov-chip]');
      if (!chip) return;
      var index = Number(chip.getAttribute('data-ov-chip'));
      if (index !== state.game) select(index);
    });

    Array.prototype.forEach.call(rangeButtons, function (button) {
      button.addEventListener('click', function () {
        var range = button.getAttribute('data-ov-range');
        if (range === state.range) return;
        state.range = range;
        Array.prototype.forEach.call(rangeButtons, function (b) {
          b.setAttribute('aria-pressed', String(b === button));
        });
        var list = visible();
        if (list.indexOf(GAMES[state.game]) < 0) state.game = 0;
        paintStats();
        select(state.game);
      });
    });

    svg.addEventListener('click', function (event) {
      var pt = event.target.closest('[data-minute]');
      if (!pt) return;
      showPoint(Number(pt.getAttribute('data-minute')), Number(pt.getAttribute('data-value')));
    });
    svg.addEventListener('focusin', function (event) {
      var pt = event.target.closest('[data-minute]');
      if (!pt) return;
      showPoint(Number(pt.getAttribute('data-minute')), Number(pt.getAttribute('data-value')));
    });
    svg.addEventListener('mouseover', function (event) {
      var pt = event.target.closest('[data-minute]');
      if (!pt) return;
      showPoint(Number(pt.getAttribute('data-minute')), Number(pt.getAttribute('data-value')));
    });

    paintLineup();
    paintStats();

    var resizeTimer = 0;
    window.addEventListener('resize', function () {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(renderChart, 150);
    }, { passive: true });

    select(0);
  })();

  /* ---------- 滚动动画（仅支持 scroll-driven 的浏览器） ---------- */

  (function () {
    if (reduce.matches) return;
    if (!window.CSS || !CSS.supports('animation-timeline', 'view()')) return;
    var targets = doc.querySelectorAll('.sec-head, .v9-head, .v9-fact, .v9-faq-body, .v5-cta-inner, .footer-gh, .page-tail-inner');
    Array.prototype.forEach.call(targets, function (el) { el.classList.add('scroll-rise'); });
  })();

  onScroll();
})();
