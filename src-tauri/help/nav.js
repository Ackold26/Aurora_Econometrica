/**
 * Aurora AI — Unified Help Navigation
 * Инжектирует навбар + поиск во все HTML-справки
 */
(function () {
  'use strict';

  const PAGES = [
    { id: 'index',            title: 'Быстрый старт',           group: 'start',    keywords: 'начало старт обзор команды лицензия' },
    { id: 'user-guide',      title: 'Руководство пользователя', group: 'start',    keywords: 'инструкция советы работа кабинеты файлы экспорт' },
    { id: 'about',           title: 'О платформе',              group: 'start',    keywords: 'платформа автор безопасность технологии модули' },
    { id: 'pipeline',        title: 'Pipeline работы',          group: 'start',    keywords: 'пайплайн этапы цикл процесс воронка' },
    { id: 'workflow-builder', title: 'Workflow Builder',        group: 'start',    keywords: 'workflow пайплайн шаги шаблоны бриф экспорт zip параллельный цикл' },
    { id: 'brands',          title: 'Управление брендами',      group: 'start',    keywords: 'бренд документы rag drag-drop тон маркеры стоп-слова creative hub' },

    { id: 'social-listening',       title: 'Social Listening',        group: 'insights', keywords: 'мониторинг отзывы упоминания соцсети бренд' },
    { id: 'media-analyst',          title: 'Медиа-аналитик',          group: 'insights', keywords: 'медиа аналитика презентации tier-1 данные' },
    { id: 'communication-analyst',  title: 'Комм. аналитик',          group: 'insights', keywords: 'медиаполе PR коммуникации анализ' },
    { id: 'econometrica',             title: 'Visual Pipeline (MMM)',    group: 'insights', keywords: 'pipeline импорт валидация колонки drag drop светофор корреляция матрица heatmap KPI медиа adstock обучение модель декомпозиция оптимизация отчёт' },
    { id: 'econometrist',            title: 'Эконометрист (чат)',       group: 'insights', keywords: 'MMM эконометрика ROI декомпозиция бюджет оптимизация awareness validate train чат команды' },

    { id: 'communication-strategist', title: 'Комм. стратег',         group: 'creative', keywords: 'стратегия позиционирование бриф платформа бренда' },
    { id: 'creative-director',        title: 'Креативный директор',    group: 'creative', keywords: 'креатив концепции идеи реклама кампания' },
    { id: 'copywriter',               title: 'Копирайтер',             group: 'creative', keywords: 'текст копирайтинг тон бренд рассылка пост контент' },
    { id: 'art-director',             title: 'Арт-директор',           group: 'creative', keywords: 'визуал дизайн макет логотип айдентика промпт midjourney' },
    { id: 'focus-groups',             title: 'Фокус-группы',           group: 'creative', keywords: 'тестирование фокус респонденты синтетические' },

    { id: 'lawyer-contracts',    title: 'Юрист — Контракты',    group: 'legal', keywords: 'договор контракт риски анализ условия' },
    { id: 'lawyer-claims',       title: 'Юрист — NDA',          group: 'legal', keywords: 'претензии NDA конфиденциальность' },
    { id: 'lawyer-advertising',  title: 'Юрист — Реклама',      group: 'legal', keywords: 'комплаенс реклама ФАС 38-ФЗ закон' },

    { id: 'doc-master',    title: 'Доку-мастер',     group: 'docmaster', keywords: 'документ медиаплан приложение договор генерация шаблон акт реквизиты' },

    { id: 'error-codes',  title: 'Коды ошибок', group: 'ref', keywords: 'ошибка код диагностика проблема' },
  ];

  const GROUPS = {
    start:    { label: 'Начало',       color: '#2E5BFF' },
    insights: { label: 'Insights Hub', color: '#06B6D4' },
    creative: { label: 'Creative',     color: '#8B5CF6' },
    legal:    { label: 'Legal',        color: '#10B981' },
    docmaster:{ label: 'Docu-master', color: '#6366F1' },
    ref:      { label: 'Справочник',   color: '#F59E0B' },
  };

  // Determine current page
  const currentFile = location.pathname.split('/').pop().replace('.html', '') || 'index';

  // Build nav HTML
  function buildNav() {
    const nav = document.createElement('nav');
    nav.id = 'aurora-nav';
    nav.innerHTML = `
      <div class="anav-inner">
        <a href="index.html" class="anav-logo">Aurora AI</a>
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
        background: #0C0C12; border-bottom: 1px solid rgba(255,255,255,0.1);
        font-family: 'Segoe UI', system-ui, sans-serif;
        padding: 0; margin: 0;
      }
      .anav-inner {
        max-width: 1100px; margin: 0 auto;
        display: flex; align-items: center; justify-content: center; gap: 8px;
        padding: 8px 20px; height: 48px;
      }
      .anav-logo {
        font-size: 15px; font-weight: 700; color: #fff; text-decoration: none;
        letter-spacing: -0.02em; white-space: nowrap; margin-right: 12px;
        background: linear-gradient(135deg, #2E5BFF, #CCFF00);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      }
      .anav-groups { display: flex; gap: 2px; }
      .anav-group { position: relative; }
      .anav-group-btn {
        background: none; border: 1px solid transparent; color: #9898A8;
        font-size: 12.5px; font-weight: 600; padding: 6px 12px;
        border-radius: 6px; cursor: pointer; transition: all 0.15s;
        white-space: nowrap;
      }
      .anav-group-btn:hover {
        color: #EAEAF0; background: rgba(255,255,255,0.06);
        border-color: var(--gc, rgba(255,255,255,0.1));
      }
      .anav-group:hover .anav-group-btn {
        color: #EAEAF0; border-color: var(--gc, rgba(255,255,255,0.15));
      }
      .anav-dropdown {
        display: none; position: absolute; top: 100%; left: 0;
        background: #141420; border: 1px solid rgba(255,255,255,0.1);
        border-radius: 8px; padding: 6px; min-width: 200px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.5); margin-top: 4px;
      }
      .anav-group:hover .anav-dropdown { display: block; }
      .anav-dropdown a {
        display: block; padding: 8px 12px; color: #9898A8;
        text-decoration: none; font-size: 13px; border-radius: 5px;
        transition: all 0.12s;
      }
      .anav-dropdown a:hover { color: #EAEAF0; background: rgba(255,255,255,0.06); }
      .anav-dropdown a.active {
        color: #EAEAF0; background: rgba(46,91,255,0.12);
        border-left: 2px solid #2E5BFF; padding-left: 10px;
      }
      .anav-search-wrap { position: relative; margin-left: 8px; }
      .anav-search {
        background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
        color: #EAEAF0; font-size: 12.5px; padding: 6px 12px;
        border-radius: 6px; width: 200px; outline: none;
        transition: all 0.2s; font-family: inherit;
      }
      .anav-search:focus {
        border-color: rgba(46,91,255,0.4); width: 260px;
        background: rgba(255,255,255,0.08);
      }
      .anav-search::placeholder { color: #5A5A6E; }
      .anav-results {
        display: none; position: absolute; top: 100%; right: 0;
        background: #141420; border: 1px solid rgba(255,255,255,0.1);
        border-radius: 8px; padding: 6px; min-width: 280px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.5); margin-top: 4px;
        max-height: 360px; overflow-y: auto;
      }
      .anav-results.visible { display: block; }
      .anav-results a {
        display: flex; flex-direction: column; padding: 8px 12px;
        color: #9898A8; text-decoration: none; font-size: 13px;
        border-radius: 5px; transition: all 0.12s; gap: 2px;
      }
      .anav-results a:hover { color: #EAEAF0; background: rgba(255,255,255,0.06); }
      .anav-results .r-title { font-weight: 600; color: #EAEAF0; }
      .anav-results .r-group { font-size: 11px; color: #5A5A6E; }
      .anav-results .r-empty {
        padding: 12px; text-align: center; color: #5A5A6E; font-size: 12.5px;
      }
      @media (max-width: 700px) {
        .anav-inner { flex-wrap: wrap; height: auto; padding: 8px 12px; }
        .anav-groups { order: 3; width: 100%; overflow-x: auto; padding-top: 6px; }
        .anav-search-wrap { order: 2; }
        .anav-search { width: 140px; }
        .anav-search:focus { width: 180px; }
      }
    `;
    document.head.appendChild(style);
  }

  // Search logic
  function initSearch(nav) {
    const input = nav.querySelector('.anav-search');
    const results = nav.querySelector('.anav-results');

    input.addEventListener('input', function () {
      const q = this.value.trim().toLowerCase();
      if (q.length < 2) {
        results.classList.remove('visible');
        return;
      }

      const matches = PAGES.filter(p =>
        p.title.toLowerCase().includes(q) ||
        p.keywords.toLowerCase().includes(q)
      );

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

    // Close on outside click
    document.addEventListener('click', function (e) {
      if (!nav.querySelector('.anav-search-wrap').contains(e.target)) {
        results.classList.remove('visible');
      }
    });

    // Close on Escape
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        this.value = '';
        results.classList.remove('visible');
      }
    });
  }

  // Adjust body padding to avoid content hidden behind sticky nav
  function adjustBody() {
    document.body.style.paddingTop = '0';
  }

  // Init
  function init() {
    injectStyles();
    const nav = buildNav();
    document.body.prepend(nav);
    initSearch(nav);
    adjustBody();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
