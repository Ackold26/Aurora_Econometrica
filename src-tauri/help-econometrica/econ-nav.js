/**
 * Aurora AI Econometrica - Help Navigation
 * Инжектирует навбар + поиск в HTML-справки Econometrica
 */
(function () {
  'use strict';

  const PAGES = [
    { id: 'index',             title: 'Быстрый старт',          group: 'start',    keywords: 'начало старт обзор лицензия запуск' },
    { id: 'about',             title: 'О продукте',              group: 'start',    keywords: 'продукт автор эконометрика MMM' },
    { id: 'user-guide',        title: 'Руководство пользователя', group: 'start',   keywords: 'руководство гайд инструкция шаги' },
    { id: 'system-requirements', title: 'Системные требования',  group: 'start',    keywords: 'требования компьютер оборудование ОС windows RAM CPU диск python jax numpyro зависимости' },
    { id: 'faq',               title: 'FAQ и troubleshooting',   group: 'start',    keywords: 'вопросы проблемы troubleshooting python mcmc' },
    { id: 'error-codes',       title: 'Коды ошибок',             group: 'start',    keywords: 'ошибка код диагностика проблема' },

    { id: 'data-preparation',  title: 'Подготовка данных',       group: 'data',     keywords: 'данные подготовка структура столбцы kpi media control date формат недельные помесячные FMCG pharma фарма объём ratio csv xlsx' },
    { id: 'pipeline',          title: 'Pipeline: 5 шагов',       group: 'data',     keywords: 'pipeline validate train decompose optimize report шаги процесс' },
    { id: 'methodology',       title: 'Методология MMM',         group: 'data',     keywords: 'MMM bayesian байес MCMC NUTS hill adstock saturation насыщение trust levels CPP' },

    { id: 'econometrica',      title: 'Visual Pipeline (UI)',    group: 'pipeline', keywords: 'pipeline импорт валидация колонки drag drop светофор корреляция матрица KPI медиа adstock обучение модель декомпозиция оптимизация отчёт xlsx' },
  ];

  const GROUPS = {
    start:    { label: 'Начало',    color: '#2E5BFF' },
    data:     { label: 'Данные и MMM', color: '#3fb950' },
    pipeline: { label: 'Интерфейс',  color: '#58a6ff' },
  };

  // Determine current page
  const currentFile = location.pathname.split('/').pop().replace('.html', '') || 'index';

  // Build nav HTML
  function buildNav() {
    const nav = document.createElement('nav');
    nav.id = 'aurora-nav';
    nav.innerHTML = `
      <div class="anav-inner">
        <a href="index.html" class="anav-logo" title="Aurora AI Econometrica - справочный центр">
          <img src="logo-wordmark.png" alt="Aurora AI" class="anav-logo-img" />
          <span class="anav-logo-text">Econometrica</span>
        </a>
        <div class="anav-groups">
          ${Object.entries(GROUPS).map(([gid, g]) => {
            const items = PAGES.filter(p => p.group === gid);
            return `
              <div class="anav-group" data-group="${gid}">
                <button class="anav-group-btn" style="--gc: ${g.color}">${g.label}</button>
                <div class="anav-dropdown">
                  ${items.map(p => `<a href="${p.id}.html" class="${p.id === currentFile ? 'active' : ''}">${p.title}</a>`).join('')}
                </div>
              </div>`;
          }).join('')}
        </div>
        <div class="anav-search-wrap">
          <input type="text" class="anav-search" placeholder="Поиск по справке..." />
          <div class="anav-results"></div>
        </div>
      </div>
    `;
    return nav;
  }

  // Build styles
  function injectStyles() {
    const style = document.createElement('style');
    style.textContent = `
      #aurora-nav {
        position: sticky; top: 0; z-index: 9999;
        background: #0d1117; border-bottom: 1px solid rgba(255,255,255,0.1);
        font-family: 'Segoe UI', system-ui, sans-serif;
        padding: 0; margin: 0;
      }
      .anav-inner {
        max-width: 1100px; margin: 0 auto;
        display: flex; align-items: center; justify-content: center; gap: 8px;
        padding: 8px 20px; height: 48px;
      }
      .anav-logo {
        display: inline-flex; align-items: center; gap: 8px;
        text-decoration: none; white-space: nowrap; margin-right: 14px;
      }
      .anav-logo-img {
        height: 22px; width: auto; opacity: 0.92;
      }
      .anav-logo-text {
        font-size: 12px; font-weight: 700; letter-spacing: 0.08em;
        color: #e6edf3; text-transform: uppercase;
      }
      .anav-groups { display: flex; gap: 2px; }
      /* padding-bottom расширяет hover-зону группы на область между кнопкой и dropdown -
         без этого mouseleave срабатывает в 4-пиксельной "мёртвой зоне" и меню исчезает
         до того как курсор доберётся до пункта. */
      .anav-group { position: relative; padding-bottom: 6px; margin-bottom: -6px; }
      .anav-group-btn {
        background: none; border: 1px solid transparent; color: #8b949e;
        font-size: 12.5px; font-weight: 600; padding: 6px 12px;
        border-radius: 6px; cursor: pointer; transition: all 0.15s;
        white-space: nowrap;
      }
      .anav-group-btn:hover { color: #e6edf3; background: rgba(255,255,255,0.06); border-color: var(--gc, rgba(255,255,255,0.1)); }
      .anav-group:hover .anav-group-btn { color: #e6edf3; border-color: var(--gc, rgba(255,255,255,0.15)); }
      .anav-dropdown {
        display: none; position: absolute; top: 100%; left: 0;
        background: #161b22; border: 1px solid rgba(255,255,255,0.1);
        border-radius: 8px; padding: 6px; min-width: 200px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.5);
        /* margin-top убран - hover-зона группы теперь бесшовная (см. padding-bottom выше) */
      }
      .anav-group:hover .anav-dropdown { display: block; }
      .anav-dropdown a {
        display: block; padding: 8px 12px; color: #8b949e;
        text-decoration: none; font-size: 13px; border-radius: 5px; transition: all 0.12s;
      }
      .anav-dropdown a:hover { color: #e6edf3; background: rgba(255,255,255,0.06); }
      .anav-dropdown a.active { color: #e6edf3; background: rgba(88,166,255,0.12); border-left: 2px solid #58a6ff; padding-left: 10px; }
      .anav-search-wrap { position: relative; margin-left: 8px; }
      .anav-search {
        background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
        color: #e6edf3; font-size: 12.5px; padding: 6px 12px;
        border-radius: 6px; width: 200px; outline: none; transition: all 0.2s; font-family: inherit;
      }
      .anav-search:focus { border-color: rgba(88,166,255,0.4); width: 260px; background: rgba(255,255,255,0.08); }
      .anav-search::placeholder { color: #484f58; }
      .anav-results {
        display: none; position: absolute; top: 100%; right: 0;
        background: #161b22; border: 1px solid rgba(255,255,255,0.1);
        border-radius: 8px; padding: 6px; min-width: 280px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.5); margin-top: 4px;
        max-height: 360px; overflow-y: auto;
      }
      .anav-results.visible { display: block; }
      .anav-results a { display: flex; flex-direction: column; padding: 8px 12px; color: #8b949e; text-decoration: none; font-size: 13px; border-radius: 5px; transition: all 0.12s; gap: 2px; }
      .anav-results a:hover { color: #e6edf3; background: rgba(255,255,255,0.06); }
      .anav-results .r-title { font-weight: 600; color: #e6edf3; }
      .anav-results .r-group { font-size: 11px; color: #484f58; }
      .anav-results .r-empty { padding: 12px; text-align: center; color: #484f58; font-size: 12.5px; }
    `;
    document.head.appendChild(style);
  }

  // Search logic
  function initSearch(nav) {
    const input = nav.querySelector('.anav-search');
    const results = nav.querySelector('.anav-results');

    input.addEventListener('input', function () {
      const q = this.value.trim().toLowerCase();
      if (q.length < 2) { results.classList.remove('visible'); return; }
      const matches = PAGES.filter(p => p.title.toLowerCase().includes(q) || p.keywords.toLowerCase().includes(q));
      if (matches.length === 0) {
        results.innerHTML = '<div class="r-empty">Ничего не найдено</div>';
      } else {
        results.innerHTML = matches.map(p => {
          const g = GROUPS[p.group];
          return `<a href="${p.id}.html"><span class="r-title">${p.title}</span><span class="r-group">${g.label}</span></a>`;
        }).join('');
      }
      results.classList.add('visible');
    });

    document.addEventListener('click', function (e) {
      if (!nav.querySelector('.anav-search-wrap').contains(e.target)) results.classList.remove('visible');
    });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { this.value = ''; results.classList.remove('visible'); }
    });
  }

  function init() {
    injectStyles();
    const nav = buildNav();
    document.body.prepend(nav);
    initSearch(nav);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
