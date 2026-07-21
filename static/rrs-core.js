/* ===== RRS CORE — 3D Circular Plates & Dynamic Rendering ===== */
(function (window) {
  'use strict';

  const API_BASE = '';

  const CONFIG = window.TRILLOKA_CONFIG || {};
  const theme = (CONFIG.themes && CONFIG.themes.dark) ? CONFIG.themes.dark.colors : {};

  function getStateClass(score, metric) {
    if (metric === 'template' || metric === 'presence') {
      return score >= 70 ? 'state-bad' : (score >= 40 ? 'state-warn' : 'state-good');
    }
    if (metric === 'sameness') {
      return score >= 60 ? 'state-bad' : (score >= 30 ? 'state-warn' : 'state-good');
    }
    if (metric === 'visual-twin') {
      return score >= 50 ? 'state-bad' : 'state-good';
    }
    return score >= 70 ? 'state-bad' : (score >= 40 ? 'state-warn' : 'state-good');
  }

  function getStateLabel(metric, score) {
    const labels = {
      template: { bad: '% GENERIC', good: '% GENERIC', warn: '% GENERIC' },
      sameness: { bad: '/ 100', good: '/ 100', warn: '/ 100' },
      'visual-twin': { bad: '% MATCH', good: '% MATCH', warn: '% MATCH' },
      presence: { bad: 'NO SIGNAL', good: 'STRONG', warn: 'WEAK' }
    };
    const m = labels[metric] || labels.template;
    const s = score >= 70 ? 'bad' : (score >= 40 ? 'warn' : 'good');
    return m[s];
  }

  function getDescription(metric, score) {
    const descs = {
      template: {
        bad: 'Bootstrap + Tailwind + Shopify Dawn detected. High generic footprint.',
        warn: 'Some framework patterns detected. Partial customisation.',
        good: 'Custom architecture detected. Strong unique foundation.'
      },
      sameness: {
        bad: 'High cliché density. Content blends into the noise.',
        warn: 'Some overused phrases detected. Voice needs sharpening.',
        good: 'Low cliché density. Content is relatively unique.'
      },
      'visual-twin': {
        bad: 'Visual duplicates detected in database. High overlap risk.',
        warn: 'Some similar layouts found. Consider differentiation.',
        good: 'No visual duplicates detected in database.'
      },
      presence: {
        bad: 'No public sentiment or brand mentions detected.',
        warn: 'Sparse brand signals. Presence needs building.',
        good: 'Strong brand presence across multiple channels.'
      }
    };
    const d = descs[metric] || descs.template;
    const s = score >= 70 ? 'bad' : (score >= 40 ? 'warn' : 'good');
    return d[s];
  }

  function getFixes(metric, score) {
    const fixes = {
      template: ['Custom CSS architecture', 'Unique component library', 'Break the grid layout'],
      sameness: ['Voice distillation workshop', 'Cliché audit', 'Brand narrative rewrite'],
      'visual-twin': ['Visual DNA session', 'Competitor differentiation map', 'Custom layout system'],
      presence: ['Social proof integration', 'Review aggregation', 'Brand mention monitoring']
    };
    const status = score >= 70 ? 'bad' : (score >= 40 ? 'warn' : 'good');
    if (status === 'good') {
      return ['Status: Strong', 'Maintain current approach', 'Monitor for changes'];
    }
    return fixes[metric] || fixes.template;
  }

  async function fetchScanData(domain) {
    try {
      const res = await fetch(`${API_BASE}/api/v1/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: domain, tier: 'free' })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn('API unavailable, using fallback:', err);
      return null;
    }
  }

  function renderCross(containerId, data) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const domain = data.domain || 'example.com';
    const scores = data.scores || {};
    const initials = domain.split('.')[0].slice(0, 2).toUpperCase();

    const metrics = [
      { key: 'template', label: 'Template', pos: 'north', tilt: 'tilt-north', depth: 'depth-far' },
      { key: 'visual-twin', label: 'Visual Twin', pos: 'west', tilt: 'tilt-west', depth: 'depth-mid' },
      { key: 'sameness', label: 'Sameness', pos: 'east', tilt: 'tilt-east', depth: 'depth-mid' },
      { key: 'presence', label: 'Presence', pos: 'south', tilt: 'tilt-south', depth: 'depth-far' }
    ];

    let platesHtml = '';
    metrics.forEach(function (m) {
      const score = scores[m.key] !== undefined ? scores[m.key] : 0;
      const state = getStateClass(score, m.key);
      const sub = getStateLabel(m.key, score);
      platesHtml += '<div class="rrs-plate ' + state + ' ' + m.tilt + ' ' + m.depth + ' rrs-' + m.pos + '" data-metric="' + m.key + '" data-score="' + score + '"><div class="rrs-score">' + score + '</div><div class="rrs-label">' + m.label + '</div><div class="rrs-sub">' + sub + '</div></div>';
    });

    const hubGradient = 'linear-gradient(135deg,#3c8c9a,#2a6a75)';

    container.innerHTML = '<div class="rrs-lines"></div><div class="rrs-cross" id="rrsCross">' + platesHtml + '<div class="rrs-hub rrs-center"><div style="width:45px;height:45px;border-radius:50%;background:' + hubGradient + ';display:flex;align-items:center;justify-content:center;margin-bottom:6px;border:2px solid #a08020;"><span style="color:#F5E6C8;font-size:10px;font-weight:700;letter-spacing:2px;">' + initials + '</span></div><div class="rrs-hub-domain">' + domain + '</div><div class="rrs-hub-status">' + (data.status || 'No Public Sentiment') + '</div></div></div>';

    initInteractions(container);
  }

  function initInteractions(stage) {
    const cross = stage.querySelector('.rrs-cross');
    if (!cross) return;

    stage.addEventListener('mousemove', function (e) {
      const rect = stage.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      cross.style.transform = 'rotateY(' + (x * 10) + 'deg) rotateX(' + (-y * 10) + 'deg)';
    });

    stage.addEventListener('mouseleave', function () {
      cross.style.transform = 'rotateY(0deg) rotateX(0deg)';
    });

    const plates = stage.querySelectorAll('.rrs-plate');
    const overlay = document.getElementById('rrsOverlay');

    plates.forEach(function (plate) {
      plate.addEventListener('click', function () {
        if (plate.classList.contains('zoomed')) return;
        plates.forEach(function (p) {
          p.classList.remove('zoomed');
          var cb = p.querySelector('.rrs-close');
          if (cb) cb.remove();
        });
        plate.classList.add('zoomed');
        if (overlay) overlay.classList.add('active');
        var closeBtn = document.createElement('div');
        closeBtn.className = 'rrs-close';
        closeBtn.innerHTML = '&times;';
        closeBtn.addEventListener('click', function (ev) {
          ev.stopPropagation();
          plate.classList.remove('zoomed');
          if (overlay) overlay.classList.remove('active');
          closeBtn.remove();
        });
        plate.appendChild(closeBtn);
      });
    });

    if (overlay) {
      overlay.addEventListener('click', function () {
        plates.forEach(function (p) {
          p.classList.remove('zoomed');
          var cb = p.querySelector('.rrs-close');
          if (cb) cb.remove();
        });
        overlay.classList.remove('active');
      });
    }

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        plates.forEach(function (p) {
          p.classList.remove('zoomed');
          var cb = p.querySelector('.rrs-close');
          if (cb) cb.remove();
        });
        if (overlay) overlay.classList.remove('active');
      }
    });
  }

  function renderMetricPlates(containerSelector, data) {
    const container = document.querySelector(containerSelector);
    if (!container) return;

    const scores = data.scores || {};
    const metrics = [
      { key: 'template', label: 'Template', unit: '% GENERIC' },
      { key: 'sameness', label: 'Sameness', unit: '/ 100' },
      { key: 'visual-twin', label: 'Visual Twin', unit: '% MATCH' },
      { key: 'presence', label: 'Presence', unit: 'NO SIGNAL' }
    ];

    let html = '';
    metrics.forEach(function (m) {
      const score = scores[m.key] !== undefined ? scores[m.key] : 0;
      const state = getStateClass(score, m.key);
      const desc = getDescription(m.key, score);
      const fixes = getFixes(m.key, score);
      html += '<div class="metric-plate ' + state + '" data-metric="' + m.key + '"><div class="plate-inner"><span class="plate-label">' + m.label + '</span><span class="plate-value">' + score + '</span><span class="plate-unit">' + m.unit + '</span><p class="plate-desc">' + desc + '</p></div><div class="plate-fixes"><h4>' + (score >= 70 ? 'Fixes' : 'Status') + '</h4><ul>' + fixes.map(function(f){ return '<li>' + f + '</li>'; }).join('') + '</ul></div></div>';
    });

    container.innerHTML = html;

    const plates = container.querySelectorAll('.metric-plate');
    plates.forEach(function (plate) {
      plate.addEventListener('click', function () {
        plates.forEach(function (p) { p.classList.remove('active', 'zoomed'); });
        plate.classList.add('active', 'zoomed');
      });
    });
  }

  window.RRS = {
    renderCross: renderCross,
    renderMetricPlates: renderMetricPlates,
    getStateClass: getStateClass
  };

  window.renderScanResults = function (data, containerId) {
    containerId = containerId || 'rrsCross';
    renderCross(containerId, data);
  };

  // Auto-init on page load with dynamic fetch
  document.addEventListener('DOMContentLoaded', function () {
    const params = new URLSearchParams(window.location.search);
    const domain = params.get('domain') || 'example.com';

    // Update DOM text elements
    const scanDomainEl = document.getElementById('scanDomain');
    const hubDomainEl = document.getElementById('hubDomain');
    if (scanDomainEl) scanDomainEl.textContent = domain;
    if (hubDomainEl) hubDomainEl.textContent = domain;

    const initials = domain.replace(/^https?:\/\//, '').split('.')[0].slice(0, 2).toUpperCase();
    const hubSpan = document.querySelector('.rrs-hub span');
    if (hubSpan) hubSpan.textContent = initials;

    // Fetch real data from Railway API
    fetchScanData(domain).then(function (data) {
      if (data && window.RRS) {
        window.RRS.renderCross('rrsCross', data);
      } else {
        // Fallback to demo data if API fails
        window.RRS.renderCross('rrsCross', {
          domain: domain,
          scores: {
            template: 89,
            'visual-twin': 0,
            sameness: 5,
            presence: 0
          },
          status: 'No Public Sentiment'
        });
      }
    });
  });

})(window);