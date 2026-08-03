<script>
  import { invoke } from '@tauri-apps/api/core';
  import { listen } from '@tauri-apps/api/event';
  import { onMount } from 'svelte';
  import { messages, isLoading, activeCabinet, pendingCommand, stickyContext, cabinetCommands, inboxFiles as inboxFilesStore } from '$lib/store.js';
  import { toast } from '$lib/toast.js';
  import { attachmentsSkippedText } from '$lib/cloud-warning-text.js';
  import { cancelledTailAction } from '$lib/cancelled-run.js';
  import { getNextSteps, getRandomInsight, getCurrentPhase, trackRequest, getEmpathyError, getTimeGreeting, getUsageHint, startSession, incrementSessionMessages, endSession, pluralRu, getResponseActions, getSafetyTimeout, getEndowedProgressMessage, getContextInsight } from '$lib/psy.js';
  import { classifyMessage } from '$lib/chat-classifier.js';
  import { isEconometrica } from '$lib/creative-store.js';
  import { activeProject, modelData, decomposeData, optimizeData, validateData, unitCosts } from '$lib/project-state.js';
  import { ECON_DATA_COMMANDS, buildProjectDataBlock } from '$lib/econ-project-context.js';
  import { playSendSound, playCompleteSound, playAchievementSound } from '$lib/audio.js';
  import { parseResponseSections, shouldRenderStructured, isSlideDeckResponse, splitSlideSections, cleanSlideTitle, extractCompletionStats } from '$lib/response-parser.js';
  import { fade } from 'svelte/transition';
  import { X, Check, Copy } from 'lucide-svelte';
  import { prefersReducedMotion } from '$lib/stores/a11y.js';
  import ResponseSection from '$lib/components/ResponseSection.svelte';
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';

  // Configure marked for safe, sync rendering
  marked.setOptions({ breaks: true, gfm: true });

  /** @param {string} text */
  function renderMarkdown(text) {
    if (!text) return '';
    return DOMPurify.sanitize(/** @type {string} */ (marked.parse(text)), {
      ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'b', 'i', 'u', 'a', 'code', 'pre', 'blockquote',
                     'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'table',
                     'thead', 'tbody', 'tr', 'th', 'td', 'del', 'sup', 'sub', 'span', 'div'],
      ALLOWED_ATTR: ['href', 'target', 'rel', 'class'],
    });
  }

  /** @param {number} ts */
  function formatTime(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  }

  /** Tips for the empty state - usage advice for the user */
  const tips = [
    'Вы можете задавать уточняющие вопросы после получения ответа - без команды, обычным текстом. Ассистент помнит контекст диалога.',
    'Для экономии контекстного окна начинайте новый диалог (кнопка очистки), когда переключаетесь на другую тему.',
    'Загрузите файлы во «Входящие» перед отправкой задания - ассистент автоматически их прочитает и учтёт.',
    'Длинные диалоги (10+ сообщений) могут замедляться. Если ответы стали хуже - очистите чат и начните заново.',
    'Кнопки команд справа - быстрый старт. Но вы можете описать задачу своими словами, без команды.',
    'Результаты работы автоматически сохраняются в папку «Экспорт» на рабочем столе.',
    'Используйте Ctrl+F для быстрого поиска по истории сообщений.',
    'Чем точнее сформулировано задание, тем лучше результат. Указывайте формат, объём и цель.',
    'После получения ответа можно попросить: «переделай в формате таблицы», «сократи вдвое», «добавь примеры» - всё в свободной форме.',
    'Один диалог - одна тема. Так ассистент глубже погружается в задачу и даёт лучшие результаты.',
  ];

  /** Pick a random tip (stable per mount, changes on page revisit) */
  const currentTip = tips[Math.floor(Math.random() * tips.length)];

  // PSY-6: time-aware greeting + usage hint (stable per mount)
  const timeGreeting = getTimeGreeting();
  const usageHint = getUsageHint($activeCabinet?.id || '');

  /** @type {{ onShowSlides?: (messageIndex: number) => void }} */
  let { onShowSlides } = $props();

  let inputText = $state('');
  let statusText = $state('');
  let copiedIdx = $state(-1);
  let ratedIdx = $state(new Set());

  // ── Auto-continue: detect incomplete workflow and auto-send continuation ──
  let autoContinueCount = $state(0);
  const MAX_AUTO_CONTINUES = 8;

  /** Markers that indicate workflow is fully complete - stop auto-continuing */
  const COMPLETION_MARKERS = [
    'все задачи выполнены',
    'все этапы выполнены',
    'задачи выполнены',
    'презентация готова',
    'работа завершена',
    'анализ завершен',
    'проверка завершена',
    'итоговый комплект',
    'комплект готов',
    'все готово',
  ];

  /** Markers that indicate Claude is asking a question or hit an error - don't auto-continue */
  const STOP_MARKERS = [
    'ошибка', 'error', 'не удалось', 'failed', 'os error',
    'не найден', 'не существует', 'permission denied',
  ];

  /** Commands that support auto-continuation */
  const AUTO_CONTINUE_COMMANDS = [
    // media-analyst
    '/analytics', '/batch-analytics', '/check', '/action-title', '/executive-summary', '/bridges', '/benchmark', '/data-analysis',
    // econometrist
    '/mmm-full', '/mmm-prepare', '/mmm-model', '/mmm-decomposition', '/mmm-optimize',
    '/mmm-scenarios', '/mmm-report', '/awareness-forecast', '/awareness-to-sales',
    // econometrist - консультационные команды - длинные ответы
    '/interpret-model', '/why-channel', '/explain-ratio', '/pilot-design',
    '/next-quarter-plan', '/data-gaps',
  ];

  /** @type {string|null} Track last executed command for auto-continue */
  let lastCommand = $state(null);

  /**
   * Check if the last response needs auto-continuation.
   * @param {string} content - last assistant message
   * @returns {boolean}
   */
  function needsAutoContinue(content) {
    if (!lastCommand || !AUTO_CONTINUE_COMMANDS.includes(lastCommand)) return false;
    if (autoContinueCount >= MAX_AUTO_CONTINUES) return false;
    const lower = content.toLowerCase().replace(/ё/g, 'е');
    // If any completion marker is found - workflow is done
    if (COMPLETION_MARKERS.some(m => lower.includes(m))) return false;
    // If response is very short (< 200 chars) - likely an error, question, or status
    if (content.length < 200) return false;
    // If response ends with error markers - don't continue (check tail only, Python warnings mid-response are OK)
    const errorTail = lower.slice(-300);
    if (STOP_MARKERS.some(m => errorTail.includes(m))) return false;
    // If response ends with a question - Claude is asking for input, let user answer
    const trimmed = content.trimEnd();
    if (trimmed.endsWith('?') || trimmed.endsWith('?\n')) return false;
    // Check last 300 chars for multiple question marks - likely a questionnaire
    const tail = lower.slice(-300);
    if ((tail.match(/\?/g) || []).length >= 2) return false;
    return true;
  }
  /** @type {Set<number>} Set of collapsed assistant message indices */
  let collapsedMessages = $state(new Set());
  let searchQuery = $state('');
  let searchOpen = $state(false);
  /** @type {HTMLInputElement|undefined} */
  let searchInput = $state(undefined);
  /** @type {HTMLDivElement|undefined} */
  let chatContainer;
  /** @type {HTMLTextAreaElement|undefined} */
  let textareaRef;
  /** @type {(() => void)|undefined} */
  let unlistenStream;
  /** @type {(() => void)|undefined} */
  let unlistenDone;
  /** @type {(() => void)|undefined} */
  let unlistenAttachmentsSkipped;
  /** @type {(() => void)|undefined} */
  let unlistenCabinetsMismatch;
  /** @type {ReturnType<typeof setTimeout>|undefined} */
  let statusTimeout;
  /** @type {number|null} */
  let startTime = null;
  let cancelled = false;
  // 🔴 Номер хода чата. Отказ работы возвращается НЕ событием, а результатом команды,
  // и признака принадлежности не несёт вовсе: промис висит до конца работы, поэтому
  // отказ ОСТАНОВЛЕННОЙ работы срабатывает уже во время следующей — гасит её
  // защитный таймер и прогресс. Тот же класс, что CPD-42, на непокрытом пути.
  let turnSeq = 0;

  // PSY-2: Random insight for loading state
  let currentInsight = $state('');
  // C1: Slide counter during streaming (Goal Gradient Effect)
  let slideProgress = $state({ current: 0, total: 0 });
  // PSY-3: Progress phase tracking
  let progressPhase = $state('');
  let progressIndex = $state(0);
  let progressTotal = $state(0);
  /** @type {ReturnType<typeof setInterval>|undefined} */
  let progressInterval;
  // D3: флаг - pipeline_phase event получен, timer-based обновление отключено
  let pipelinePhaseReceived = false;
  /** @type {ReturnType<typeof setTimeout>|undefined} Safety timeout - гарантия ответа */
  let safetyTimer;
  /** Phase 4.2: micro-celebration pulse на последнем ответе */
  let lastResponseComplete = $state(false);
  // C3: Completion Summary Card (Peak-End Rule)
  /** @type {{slides: number, recommendations: number, anomalies: number, bridges: number, elapsed: number, contextInsight: string|null}|null} */
  let completionStats = $state(null);
  /** @type {Array<{label: string, command: string, description?: string}>} Top-3 команды кабинета для classifier + quick start */
  let quickStartCommands = $state([]);

  // Phase 3.1: Динамический placeholder (message-state-based)
  let dynamicPlaceholder = $derived.by(() => {
    const msgs = $messages;
    if (msgs.length === 0) {
      return 'Выберите и запустите команду...';
    }
    const last = msgs[msgs.length - 1];
    if (last?.role === 'assistant' && last.content?.trim().endsWith('?')) {
      return 'Ответьте на вопрос ассистента...';
    }
    if (last?.role === 'assistant') return 'Уточните результат или начните новую задачу...';
    return 'Введите задание...';
  });

  // Phase 3.3: Command mode indicator
  let isCommandInput = $derived(inputText.trimStart().startsWith('/'));
  // PSY-1: Next steps chips visible only after last response, not during loading
  let nextSteps = $derived.by(() => {
    const cabId = $activeCabinet?.id;
    if (!cabId || $isLoading) return [];
    const msgs = $messages;
    if (msgs.length === 0) return [];
    const last = msgs[msgs.length - 1];
    if (last.role !== 'assistant') return [];
    return getNextSteps(cabId);
  });

  // PSY-10: Sticky Context - подхватить контекст при переключении кабинета
  $effect(() => {
    const ctx = $stickyContext;
    if (!ctx || !$activeCabinet) return;
    // Забираем контекст сразу, чтобы не зациклиться
    stickyContext.set(null);
    // Добавить системное уведомление
    messages.update(msgs => [...msgs, {
      role: 'system',
      content: 'Контекст из предыдущего кабинета передан. Используйте его как вводные для задания.',
      ts: Date.now(),
    }]);
    // Предзаполнить input
    inputText = ctx;
  });

  // C2: Endowed Progress Effect - сообщение при загрузке первого файла
  let prevInboxCount = $state(0);
  $effect(() => {
    const files = $inboxFilesStore;
    if (files.length > 0 && prevInboxCount === 0) {
      const msg = getEndowedProgressMessage(files.length, files[0]);
      toast(msg, 'info', 3000);
    }
    prevInboxCount = files.length;
  });

  // ── Phase 5.1: Smart autoscroll - скролл при новых сообщениях / смене loading ──
  function isNearBottom() {
    if (!chatContainer) return true;
    return chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight < 150;
  }
  $effect(() => {
    const _msgCount = $messages.length;
    const _loading = $isLoading;
    void _msgCount; void _loading;
    if (chatContainer && isNearBottom()) {
      requestAnimationFrame(() => {
        chatContainer?.scrollTo({ top: chatContainer.scrollHeight, behavior: 'smooth' });
      });
    }
  });

  let filteredMessages = $derived(
    searchQuery.trim()
      ? $messages.filter(m => m.content?.toLowerCase().includes(searchQuery.trim().toLowerCase()))
      : $messages
  );

  /**
   * Svelte action: highlights search matches at DOM level (safe - no HTML injection).
   * @param {HTMLElement} node
   * @param {string} query
   */
  function highlightAction(node, query) {
    function apply(/** @type {string} */ q) {
      // Remove previous highlights
      node.querySelectorAll('mark[data-hl]').forEach(m => {
        const parent = m.parentNode;
        if (parent) {
          parent.replaceChild(document.createTextNode(m.textContent || ''), m);
          parent.normalize();
        }
      });
      if (!q?.trim()) return;
      const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`(${escaped})`, 'gi');
      const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
      /** @type {Text[]} */
      const textNodes = [];
      while (walker.nextNode()) textNodes.push(/** @type {Text} */ (walker.currentNode));
      for (const tn of textNodes) {
        const val = tn.nodeValue || '';
        if (!regex.test(val)) continue;
        regex.lastIndex = 0;
        const frag = document.createDocumentFragment();
        let lastIdx = 0;
        let match;
        while ((match = regex.exec(val)) !== null) {
          if (match.index > lastIdx) frag.appendChild(document.createTextNode(val.slice(lastIdx, match.index)));
          const mark = document.createElement('mark');
          mark.setAttribute('data-hl', '');
          mark.textContent = match[1];
          frag.appendChild(mark);
          lastIdx = regex.lastIndex;
        }
        if (lastIdx < val.length) frag.appendChild(document.createTextNode(val.slice(lastIdx)));
        tn.parentNode?.replaceChild(frag, tn);
      }
    }
    apply(query);
    return { update: apply };
  }

  function toggleSearch() {
    searchOpen = !searchOpen;
    if (!searchOpen) {
      searchQuery = '';
    } else {
      setTimeout(() => searchInput?.focus(), 50);
    }
  }

  /** @param {KeyboardEvent} e */
  function handleSearchKeydown(e) {
    if (e.key === 'Escape') {
      toggleSearch();
    }
  }

  /** @param {{name?: string, input?: Record<string, any>}} block */
  function toolUseToStatus(block) {
    const name = block.name || '';
    const input = block.input || {};

    if (name === 'Read') {
      const path = input.file_path || '';
      const short = path.split(/[/\\]/).pop() || path;
      return `Читаю файл: ${short}`;
    }
    if (name === 'Write' || name === 'Edit') {
      return 'Записываю результат...';
    }
    if (name === 'Bash') {
      return 'Выполняю команду...';
    }
    if (name === 'WebFetch') {
      return 'Загружаю страницу...';
    }
    if (name === 'Grep' || name === 'Glob') {
      return 'Ищу в файлах...';
    }
    return `Выполняю: ${name}...`;
  }

  async function loadHistory() {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      const history = /** @type {Array<{role: string, content: string, ts: number}>} */ (await invoke('load_chat_history', { cabinetId }));
      if (history && history.length > 0) {
        messages.set(history.map(m => ({ role: m.role, content: m.content, ts: m.ts })));
        setTimeout(scrollToBottom, 50);
      }
    } catch (err) {
      console.error('Failed to load history:', err);
    }
  }

  /** @param {string} role @param {string} content @param {number} ts */
  async function saveMsg(role, content, ts) {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      await invoke('save_chat_message', { cabinetId, role, content, ts });
    } catch { /* non-critical */ }
  }

  async function clearHistory() {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      await invoke('clear_chat_history', { cabinetId });
      messages.set([]);
    } catch (err) {
      console.error('Failed to clear history:', err);
    }
  }

  /** @param {KeyboardEvent} e */
  function handleGlobalKeydown(e) {
    // Ctrl+F → toggle search (Ctrl+K зарезервирован под глобальную палитру команд в +layout.svelte)
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
      e.preventDefault();
      toggleSearch();
    }
    // Escape → close search
    if (e.key === 'Escape' && searchOpen) {
      toggleSearch();
    }
  }

  onMount(() => {
    window.addEventListener('keydown', handleGlobalKeydown);

    // Subscribe to command buttons immediately (not inside async)
    const unsubCommand = pendingCommand.subscribe((cmd) => {
      if (cmd) {
        pendingCommand.set(null);
        inputText = cmd;
        sendMessage();
      }
    });

    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) {
      return () => {
        window.removeEventListener('keydown', handleGlobalKeydown);
        unsubCommand();
      };
    }

    // PSY-8: start session tracking
    startSession(cabinetId);

    // Async setup for stream listeners
    let asyncCleanup = /** @type {(() => void)|undefined} */ (undefined);
    (async () => {
    // Clean start moved to +layout.svelte (once on app launch, not on every cabinet open)

    // Phase 2.2: загрузка топ-команд для classifier
    // Используем cabinetCommands store (заполняется CommandGrid) - без дублирующего IPC
    const unsubCmds = cabinetCommands.subscribe(cmds => {
      if (cmds.length > 0) {
        quickStartCommands = cmds.slice(0, 3).map(c => ({ label: c.label, command: c.command }));
      }
    });
    // Fallback: если CommandGrid ещё не загрузил (например в execution mode)
    if (quickStartCommands.length === 0) {
      try {
        const cmds = /** @type {Array<{group: string, label: string, command: string}>} */ (
          await invoke('get_cabinet_commands', { cabinetId })
        );
        quickStartCommands = cmds.slice(0, 3).map(c => ({ label: c.label, command: c.command }));
      } catch { /* noncritical */ }
    }

    unlistenStream = await listen(`claude-stream-${cabinetId}`, (event) => {
      // 🔴 Помеченный хвост ОСТАНОВЛЕННОЙ работы разбирается ДО признака отмены
      // (находка аудита правок). Прежде проверка стояла ниже, и хвост погибал ровно
      // в том случае, ради которого пометка заведена: человек нажал «Остановить»,
      // признак стоит — и приписка с номером осиротевшей работы выбрасывалась первой
      // же строкой. Без неё человеку нечего назвать поддержке: место среди
      // одновременных занято, а следующий вопрос упрётся в потолок.
      let tail = null;
      try { tail = JSON.parse(event.payload); } catch { tail = null; }
      if (tail?.cancelled_run) {
        const action = cancelledTailAction($isLoading, tail.notice);
        if (action !== 'apply') {
          if (action === 'notice') {
            messages.update(msgs => [...msgs, {
              role: 'system', content: tail.notice, ts: Date.now(),
            }]);
            if (isNearBottom()) scrollToBottom();
          }
          return;
        }
      } else if (cancelled) {
        return;
      }
      try {
        const data = JSON.parse(event.payload);

        if (data.type === 'pipeline_phase') {
          // Multi-phase analytics pipeline: update progress, reset safety timer
          clearTimeout(safetyTimer);
          safetyTimer = setTimeout(async () => {
            if ($isLoading) {
              cancelled = true;
              try { await invoke('cancel_claude', { cabinetId }); } catch {}
              messages.update(msgs => [...msgs, { role: 'system', content: 'Превышено время ожидания фазы пайплайна.', ts: Date.now() }]);
              isLoading.set(false);
              resetProgress();
            }
          }, getSafetyTimeout(cabinetId));
          startTime = Date.now(); // Reset phase timer
          pipelinePhaseReceived = true; // D3: отключить timer-based progressPhase
          progressPhase = data.label || 'Обработка...';
          if (data.phase_index !== undefined) progressIndex = data.phase_index;
          if (data.total_phases !== undefined) progressTotal = data.total_phases;
        } else if (data.type === 'clear_response') {
          // Retry: remove partial assistant response from failed attempt
          messages.update(msgs => {
            const last = msgs[msgs.length - 1];
            if (last && last.role === 'assistant') {
              return msgs.slice(0, -1);
            }
            return msgs;
          });
        } else if (data.type === 'system' && data.subtype === 'init') {
          // Phase 1.1: прогресс уже запущен в sendMessage().
          // НЕ сбрасываем startTime - иначе прогресс-бар прыгает назад.
          // Только снимаем safety timeout (Claude ответил - значит жив).
          clearTimeout(safetyTimer);
          statusText = '';
        } else if (data.type === 'system' && data.subtype === 'cloud_wait_cancelled') {
          // 🔴 Отклик на «Остановить» обязан быть НЕМЕДЛЕННЫМ. Событие уже
          // отправлялось, но его никто не читал: единственный видимый признак
          // приходил позже, с завершением захода ленты, - до минуты тишины,
          // в которую человек успевает решить, что кнопка не работает.
          clearTimeout(safetyTimer);
          statusText = '';
          messages.update(msgs => [...msgs, {
            role: 'system', content: data.message || 'Работа остановлена на сервере.', ts: Date.now(),
          }]);
        } else if (data.type === 'system' && data.subtype === 'resume_fallback') {
          // Phase 1.3: уведомление о потере контекста
          messages.update(msgs => [...msgs, {
            role: 'system', content: data.message || 'Контекст диалога сброшен. Начинаю новую сессию.', ts: Date.now(),
          }]);
        } else if (data.type === 'assistant' && data.message?.content) {
          for (const block of data.message.content) {
            if (block.type === 'text') {
              messages.update(msgs => {
                const last = msgs[msgs.length - 1];
                if (last && last.role === 'assistant') {
                  // Dedup: skip if text is already at the end of current content
                  if (block.text && last.content.endsWith(block.text)) return msgs;
                  // Dedup: if new text contains everything we have (cumulative event), replace
                  if (block.text && block.text.length > last.content.length && block.text.startsWith(last.content)) {
                    return [...msgs.slice(0, -1), { role: 'assistant', content: block.text, ts: last.ts }];
                  }
                  return [...msgs.slice(0, -1), { role: 'assistant', content: last.content + block.text, ts: last.ts }];
                }
                return [...msgs, { role: 'assistant', content: block.text, ts: Date.now() }];
              });
              // C1: Slide counter - Goal Gradient Effect
              const lastMsg = $messages[$messages.length - 1];
              if (lastMsg?.role === 'assistant') {
                const slideMatches = lastMsg.content.match(/^##\s+(?:(?:Слайд|Slide)\s*№?\s*\d+|\d+\.\s)/gim);
                if (slideMatches) slideProgress = { current: slideMatches.length, total: slideProgress.total || 0 };
              }
            } else if (block.type === 'tool_use') {
              statusText = toolUseToStatus(block);
              // PSY-3: tool status более информативен - скрываем progress bar
              progressPhase = '';
            }
          }
        } else if (data.type === 'result') {
          resetProgress();
          // Show completion status + micro-celebration pulse
          if (startTime) {
            const elapsed = Math.round((Date.now() - startTime) / 1000);
            statusText = `Готово за ${elapsed}с`;
            clearTimeout(statusTimeout);
            statusTimeout = setTimeout(() => { statusText = ''; statusTimeout = undefined; }, 3000);
            // Phase 4.2: pulse animation
            lastResponseComplete = true;
            setTimeout(() => { lastResponseComplete = false; }, 600);
            // C3: Completion Summary Card - Peak-End Rule
            const msgs = $messages;
            const lastMsg = msgs[msgs.length - 1];
            if (lastMsg?.role === 'assistant' && $activeCabinet?.id === 'media-analyst') {
              const sections = parseResponseSections(lastMsg.content);
              if (isSlideDeckResponse(sections)) {
                completionStats = { ...extractCompletionStats(sections), elapsed, contextInsight: getContextInsight(lastMsg.content, 'media-analyst') };
                setTimeout(() => { completionStats = null; }, 8000);
              }
            }
            startTime = null;
          } else {
            statusText = '';
          }

          messages.update(msgs => {
            if (!data.result) return msgs;
            const last = msgs[msgs.length - 1];
            if (last?.role !== 'assistant') {
              return [...msgs, { role: 'assistant', content: data.result, ts: Date.now() }];
            }
            // 🔴 Облачный путь помечает финальное событие `replace` — его текст
            // ПОЛНЕЕ показанного: там приписки, которых в потоке не было (номер
            // осиротевшей работы, «Ответ неполный», не доехавшие файлы выгрузки).
            // Прежде такой текст молча выбрасывался: поток уже что-то показал,
            // условие ниже не пускало (находка внешнего аудита). Локальный путь
            // признак не ставит — там `result` дублирует показанное, и замена
            // на него отрезала бы часть склеенного ответа.
            if (data.replace) {
              return [...msgs.slice(0, -1), { role: 'assistant', content: data.result, ts: last.ts }];
            }
            return msgs;
          });
        } else if (data.type === 'retry') {
          statusText = `Повторная попытка ${data.attempt}/${data.max_retries} через ${data.backoff_secs}с...`;
          // Re-arm progress for next attempt (result event from failed attempt may have reset it)
          if (!startTime) startTime = Date.now();
        } else if (data.type === 'error') {
          resetProgress();
          statusText = '';
          // PSY-5: эмпатичное сообщение об ошибке
          const empathy = getEmpathyError(data.message || '');
          messages.update(msgs => [...msgs, {
            role: 'system',
            content: `${empathy.emoji} ${empathy.message}\n\n${empathy.tip}${empathy.code ? ` (${empathy.code})` : ''}`,
            ts: Date.now(),
          }]);
        }
      } catch {
        // Non-JSON line, try treating as plain text
        const payload = String(event.payload);
        if (payload.trim()) {
          messages.update(msgs => {
            const last = msgs[msgs.length - 1];
            if (last && last.role === 'assistant') {
              if (last.content.endsWith(payload)) return msgs;
              if (payload.length > last.content.length && payload.startsWith(last.content)) {
                return [...msgs.slice(0, -1), { role: 'assistant', content: payload, ts: last.ts }];
              }
              return [...msgs.slice(0, -1), { role: 'assistant', content: last.content + payload, ts: last.ts }];
            }
            return [...msgs, { role: 'assistant', content: payload, ts: Date.now() }];
          });
        }
      }
      // Smart autoscroll: скроллим только если пользователь у нижнего края
      if (isNearBottom()) scrollToBottom();
    });

    // 🔴 Тонкая поставка ТЕПЕРЬ передаёт файлы «Входящих» на сервер (контракт v1,
    // ADR-048). Если какой-то файл не уехал — велик, не прочитался, — человек обязан
    // это увидеть: иначе он считает данные учтёнными, а разбор идёт без них. Прежде
    // событие слал только продукт, слушателя не было вовсе, и предупреждение
    // пропадало — ровно та молчаливая потеря, против которой оно и писано.
    unlistenAttachmentsSkipped = await listen(`inbox-attachments-skipped-${cabinetId}`, (event) => {
      const data = typeof event.payload === 'string' ? JSON.parse(event.payload) : event.payload;
      // Текст собирает отдельная функция: проверять его по исходнику обработчика
      // значило проверять соседство слов, а не то, что увидит человек.
      toast(attachmentsSkippedText(data), 'info', 8000);
    });

    // 🔴 Расхождение методики: набор кабинетов на сервере разошёлся с тем, что
    // ожидает программа. Молчать нельзя — ответ построен по другому подходу, и
    // отличить это от нормальной работы человек не может ничем. Прежде событие
    // слал только продукт, слушателя не было: «видимое предупреждение» было невидимо.
    unlistenCabinetsMismatch = await listen(`cabinets-version-mismatch-${cabinetId}`, (event) => {
      const data = typeof event.payload === 'string' ? JSON.parse(event.payload) : event.payload;
      const reason = typeof data?.reason === 'string'
        ? data.reason
        : 'Методика на сервере отличается от той, что ожидает программа.';
      toast(reason, 'warning', 10000);
    });

    unlistenDone = await listen(`claude-done-${cabinetId}`, (event) => {
      // 🔴 Остановленность определяет САМО событие, а не наш признак (находка
      // внешнего аудита). Признак снимается следующим вопросом человека, и
      // завершение остановленной работы, доехавшее после него, шло по обычному
      // пути: гасило прогресс и защитный таймер ЖИВОЙ работы, а её недописанный
      // текст уходило сохранять в историю.
      let payload = event.payload;
      if (typeof payload === 'string') {
        try { payload = JSON.parse(payload); } catch { payload = null; }
      }
      if (payload?.cancelled) {
        // 🔴 Флаг НЕ трогаем (находка аудита правок): финал остановленной работы A
        // мог доехать, когда признак принадлежит уже работе B, которую человек тоже
        // остановил. Сбросив его здесь, мы пустили бы финал B обычным путём — он
        // погасил бы прогресс и сохранил недописанное в историю.
        return;
      }
      if (cancelled) {
        cancelled = false;
        return;
      }
      clearTimeout(safetyTimer);
      resetProgress();
      if (!statusTimeout) statusText = '';
      // Save last assistant message to history
      const msgs = $messages;
      const last = msgs[msgs.length - 1];
      if (last && last.role === 'assistant') {
        // Dedup: if this response duplicates the previous assistant message, merge instead of keeping both
        // Use reverse-search to skip any system/user messages between assistant turns
        let prevAssistant = null;
        for (let i = msgs.length - 2; i >= 0; i--) {
          if (msgs[i].role === 'assistant') { prevAssistant = msgs[i]; break; }
        }
        if (prevAssistant && last.content.trim() === prevAssistant.content.trim()) {
          // Duplicate - remove messages from the auto-continue user msg up to (not including) prevAssistant
          messages.update(m => {
            let cutFrom = m.length - 1;
            for (let i = m.length - 2; i >= 0; i--) {
              if (m[i].role === 'assistant') break;
              cutFrom = i;
            }
            return m.slice(0, cutFrom);
          });
          isLoading.set(false);
          return;
        }
        saveMsg('assistant', last.content, last.ts);
        incrementSessionMessages();

        // ── Auto-continue: if workflow is incomplete, send continuation automatically ──
        if (needsAutoContinue(last.content)) {
          autoContinueCount++;
          // Keep isLoading=true, re-arm safety timer, send continuation
          statusText = `Продолжаю автоматически (${autoContinueCount}/${MAX_AUTO_CONTINUES})...`;
          clearTimeout(safetyTimer);
          const safetyMs = getSafetyTimeout(cabinetId);
          safetyTimer = setTimeout(async () => {
            if ($isLoading) {
              cancelled = true;
              try { await invoke('cancel_claude', { cabinetId }); } catch {}
              isLoading.set(false);
              resetProgress();
            }
          }, safetyMs);
          // Add auto-continue message (marked for compact rendering)
          const contTs = Date.now();
          const contMsg = 'Продолжай. Не пересказывай сделанное - сразу к следующему шагу.';
          messages.update(m => [...m, { role: 'user', content: contMsg, ts: contTs, isAutoContinue: true }]);
          saveMsg('user', contMsg, contTs);
          invoke('send_message', { cabinetId, message: contMsg, suppressExport: true }).catch(() => {
            isLoading.set(false);
            resetProgress();
          });
          return; // Skip normal completion flow
        }

        // Normal completion - no auto-continue needed
        isLoading.set(false);
        playCompleteSound();
        // PSY-5: milestone tracking
        const cabId = $activeCabinet?.id;
        if (cabId) {
          const achievement = trackRequest(cabId);
          if (achievement) {
            toast(`${achievement.title} - ${achievement.description}`, 'success', 4000);
            playAchievementSound();
          }
        }
      } else {
        isLoading.set(false);
        playCompleteSound();
      }
    });

    asyncCleanup = () => {
      unlistenStream?.();
      unlistenDone?.();
      unlistenAttachmentsSkipped?.();
      unlistenCabinetsMismatch?.();
      unsubCmds?.();
      clearTimeout(statusTimeout);
      clearTimeout(safetyTimer);
      clearInterval(progressInterval);
    };
    })();

    return () => {
      window.removeEventListener('keydown', handleGlobalKeydown);
      unsubCommand();
      asyncCleanup?.();
    };
  });

  async function cancelClaude() {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      await invoke('cancel_claude', { cabinetId });
      messages.update(msgs => [...msgs, { role: 'system', content: 'Выполнение остановлено.', ts: Date.now() }]);
    } catch {
      // process may have already finished - ignore
    }
    cancelled = true;
    clearTimeout(statusTimeout);
    resetProgress();
    isLoading.set(false);
    statusText = '';
  }

  async function sendMessage() {
    const text = inputText.trim();
    if (!text || $isLoading) return;

    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;

    const ts = Date.now();

    // ── Правило №10 (CLAUDE.md): Pipeline context - inject в message, не файл ──
    // Консультационные команды econometrist (/interpret-model и др.) документированы
    // как читающие JSON-артефакты пайплайна из workspace, но runtime-restriction
    // запрещает env-пути и ни один код туда эти файлы не кладёт - контракт иначе
    // сломан. Прикладываем данные к сообщению, которое реально уходит в Claude;
    // отображаемый/сохраняемый текст (messages/history) остаётся оригинальным -
    // пользователь не должен видеть сырой JSON в чате.
    let messageToSend = text;
    if ($isEconometrica && ECON_DATA_COMMANDS.includes(text.split(/\s/)[0])) {
      const uc = $unitCosts && Object.keys($unitCosts).length > 0 ? $unitCosts : null;
      const meta = $activeProject || uc
        ? { name: $activeProject?.name ?? null, kpi_type: $activeProject?.kpi_type ?? null, unit_costs: uc }
        : null;
      messageToSend = text + buildProjectDataBlock({
        mod: $modelData?.diagnostics ? $modelData : null,
        dec: $decomposeData,
        opt: $optimizeData,
        val: $validateData,
        projectMeta: meta,
      });
    }

    // ── Phase 2.2: Classifier - перехват small talk ДО добавления user message ──
    // Важно: classifyMessage получает $messages ДО добавления нового сообщения,
    // чтобы follow-up protection корректно проверяла последнее сообщение ассистента.
    const quick = classifyMessage(text, $activeCabinet, quickStartCommands.map(c => c.label), $messages);

    messages.update(msgs => [...msgs, { role: 'user', content: text, ts }]);
    saveMsg('user', text, ts);
    incrementSessionMessages();
    inputText = '';
    cancelled = false;
    const myTurn = ++turnSeq;
    // Track command for auto-continue (slash commands only, reset for follow-ups)
    if (text.startsWith('/')) {
      lastCommand = text.split(/\s/)[0];
      autoContinueCount = 0;
    } else {
      lastCommand = null; // Non-slash follow-ups should not trigger auto-continue
    }
    scrollToBottom();
    if (quick) {
      const qts = Date.now();
      messages.update(msgs => [...msgs, {
        role: 'assistant', content: quick.response, ts: qts, isQuickReply: true,
      }]);
      saveMsg('assistant', quick.response, qts);
      scrollToBottom();
      return; // НЕ отправлять в Claude, НЕ ставить isLoading
    }

    // ── Phase 1.1: Instant feedback - прогресс сразу, не ждём system.init ──
    playSendSound();
    slideProgress = { current: 0, total: 0 }; // C1: reset slide counter
    isLoading.set(true);
    statusText = 'Подготавливаю запрос...';
    currentInsight = getRandomInsight(cabinetId) || '';
    startTime = Date.now();
    pipelinePhaseReceived = false; // D3: сброс флага перед новым запросом
    clearInterval(progressInterval);
    const phaseInfo = getCurrentPhase(0, cabinetId);
    progressPhase = phaseInfo.label;
    progressIndex = phaseInfo.phaseIndex;
    progressTotal = phaseInfo.totalPhases;
    progressInterval = setInterval(() => {
      if (cancelled || !startTime || pipelinePhaseReceived) return; // D3: pipeline wins
      const elapsed = Math.round((Date.now() - startTime) / 1000);
      const phase = getCurrentPhase(elapsed, cabinetId);
      progressPhase = phase.label;
      progressIndex = phase.phaseIndex;
    }, 1000);

    // ── Phase 1.2: Safety timeout - configurable per cabinet ──
    const safetyMs = getSafetyTimeout(cabinetId);
    clearTimeout(safetyTimer);
    safetyTimer = setTimeout(async () => {
      if ($isLoading) {
        cancelled = true;
        try { await invoke('cancel_claude', { cabinetId }); } catch { /* process may have finished */ }
        const mins = Math.round(safetyMs / 60_000);
        messages.update(msgs => [...msgs, {
          role: 'system',
          content: `Нет ответа более ${mins} мин. Попробуйте ещё раз или перезапустите кабинет.`,
          ts: Date.now(),
        }]);
        isLoading.set(false);
        resetProgress();
      }
    }, safetyMs);

    try {
      await invoke('send_message', { cabinetId, message: messageToSend });
    } catch (err) {
      // 🔴 Отказ ПРОШЛОГО хода не властен над текущим (тот же класс, что CPD-42, на
      // пути, который событий не шлёт вовсе). Промис команды висит до конца работы,
      // поэтому отказ остановленной работы срабатывает уже во время следующей: он
      // погасил бы её защитный таймер, прогресс и признак занятости. Сам текст отказа
      // человеку показать обязаны — работа, которую он запускал, не удалась.
      const stale = myTurn !== turnSeq;
      messages.update(msgs => [...msgs, { role: 'system', content: `Ошибка: ${err}`, ts: Date.now() }]);
      if (stale) return;
      clearTimeout(safetyTimer);
      isLoading.set(false);
      resetProgress();
    }
  }

  /** @param {KeyboardEvent} e */
  function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function scrollToBottom() {
    if (chatContainer) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }

  /** @param {number} idx @param {number} rating */
  async function rateMessage(idx, rating) {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      await invoke('rate_response', { cabinetId, commandSlug: null, rating, responseTimeSecs: null });
      ratedIdx = new Set([...ratedIdx, idx]);
    } catch (err) {
      console.error('Failed to rate:', err);
    }
  }

  /** Toggle collapse state for a single assistant message */
  /** @param {number} idx */
  function toggleCollapse(idx) {
    const next = new Set(collapsedMessages);
    if (next.has(idx)) { next.delete(idx); } else { next.add(idx); }
    collapsedMessages = next;
  }

  /** Collapse or expand all assistant messages */
  function toggleCollapseAll() {
    const assistantIndices = filteredMessages
      .map((m, i) => m.role === 'assistant' ? i : -1)
      .filter(i => i >= 0);
    const allCollapsed = assistantIndices.every(i => collapsedMessages.has(i));
    if (allCollapsed) {
      collapsedMessages = new Set();
    } else {
      collapsedMessages = new Set(assistantIndices);
    }
  }

  /** Get first meaningful line of content as preview (plain text, max 120 chars) */
  /** @param {string} content */
  function getPreview(content) {
    const line = content.replace(/^#+\s*/m, '').replace(/[*_`~]/g, '').split('\n').find(l => l.trim()) || '';
    return line.length > 120 ? line.slice(0, 120) + '...' : line;
  }

  /** Сбросить состояние progress/insight */
  function resetProgress() {
    clearInterval(progressInterval);
    progressPhase = '';
    currentInsight = '';
  }

  /**
   * PSY-1/PSY-10: Перейти в рекомендованный кабинет с передачей контекста.
   * @param {{id: string, label: string, reason: string}} step
   */
  async function navigateToNextCabinet(step) {
    try {
      const cabinets = /** @type {Array<{id: string, name: string, description: string, icon: string, color: string}>} */ (await invoke('get_cabinets'));
      const target = cabinets.find(c => c.id === step.id);
      if (!target) { toast('Кабинет недоступен', 'error'); return; }

      // Собираем контекст из последнего ответа (без confirm - передаём всегда)
      const msgs = $messages;
      const lastAssistant = [...msgs].reverse().find(m => m.role === 'assistant');
      if (lastAssistant) {
        // D2: для media-analyst передавать только synthesis, не все слайды (PSY-10)
        let contextText = null;
        if ($activeCabinet?.id === 'media-analyst') {
          const sections = parseResponseSections(lastAssistant.content);
          if (isSlideDeckResponse(sections)) {
            const { synthesis } = splitSlideSections(sections);
            const synthText = synthesis.map(s => `## ${s.title}\n${s.content}`).join('\n\n');
            if (synthText.length > 100) contextText = synthText.slice(0, 3000);
          }
        }
        if (!contextText) {
          contextText = lastAssistant.content.length > 2000
            ? lastAssistant.content.slice(0, 2000) + '\n\n[...текст сокращён]'
            : lastAssistant.content;
        }
        stickyContext.set(`Контекст из кабинета «${$activeCabinet?.name || ''}»:\n\n${contextText}\n\n---\n\n`);
      }

      // Закрыть текущий кабинет
      const currentId = $activeCabinet?.id;
      if (currentId) {
        try { await invoke('close_cabinet', { cabinetId: currentId }); } catch { /* ok */ }
      }
      endSession();

      // Открыть новый (vault + workspace)
      await invoke('open_cabinet', { cabinetId: step.id });
      messages.set([]);
      activeCabinet.set(target); // {#key} в cabinet page перемонтирует ChatPanel
      startSession(step.id);
    } catch (err) {
      toast(`Не удалось открыть кабинет: ${err}`, 'error');
    }
  }

  /** @param {string} content @param {number} idx */
  async function copyMessage(content, idx) {
    try {
      await navigator.clipboard.writeText(content);
      copiedIdx = idx;
      setTimeout(() => { copiedIdx = -1; }, 1500);
    } catch { /* clipboard API may be blocked */ }
  }
</script>

<div class="chat">
  <div class="chat-header">
    {#if searchOpen}
      <div class="search-bar">
        <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input
          bind:this={searchInput}
          class="search-input"
          type="text"
          placeholder="Поиск по сообщениям..."
          bind:value={searchQuery}
          onkeydown={handleSearchKeydown}
        />
        {#if searchQuery}
          <span class="search-count">{filteredMessages.length}</span>
        {/if}
        <button class="search-close" onclick={toggleSearch} aria-label="Закрыть поиск"><X size={16} strokeWidth={1.5} /></button>
      </div>
    {/if}
  </div>

  <div class="messages" bind:this={chatContainer}>
    {#if filteredMessages.length === 0 && !searchQuery}
      <div class="empty">
        <div class="empty-icon">
          <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <!-- mesh nodes -->
            <circle cx="24" cy="8"  r="2.5" fill="var(--accent-primary)" opacity="0.7"/>
            <circle cx="40" cy="24" r="2.5" fill="var(--accent-primary)" opacity="0.7"/>
            <circle cx="24" cy="40" r="2.5" fill="var(--accent-primary)" opacity="0.7"/>
            <circle cx="8"  cy="24" r="2.5" fill="var(--accent-primary)" opacity="0.7"/>
            <circle cx="24" cy="24" r="3.5" fill="var(--accent-secondary)" opacity="0.9"/>
            <!-- lines -->
            <line x1="24" y1="8"  x2="40" y2="24" stroke="var(--accent-primary)" stroke-width="1" opacity="0.3"/>
            <line x1="40" y1="24" x2="24" y2="40" stroke="var(--accent-primary)" stroke-width="1" opacity="0.3"/>
            <line x1="24" y1="40" x2="8"  y2="24" stroke="var(--accent-primary)" stroke-width="1" opacity="0.3"/>
            <line x1="8"  y1="24" x2="24" y2="8"  stroke="var(--accent-primary)" stroke-width="1" opacity="0.3"/>
            <line x1="24" y1="24" x2="24" y2="8"  stroke="var(--accent-secondary)" stroke-width="1.5" opacity="0.5"/>
            <line x1="24" y1="24" x2="40" y2="24" stroke="var(--accent-secondary)" stroke-width="1.5" opacity="0.5"/>
            <line x1="24" y1="24" x2="24" y2="40" stroke="var(--accent-secondary)" stroke-width="1.5" opacity="0.5"/>
            <line x1="24" y1="24" x2="8"  y2="24" stroke="var(--accent-secondary)" stroke-width="1.5" opacity="0.5"/>
          </svg>
        </div>
        <p class="empty-text">{timeGreeting}. {$activeCabinet?.name || 'Ассистент'} готов к работе</p>
        <p class="empty-hint">{usageHint ? usageHint.text : 'Загрузите файлы во «Входящие» и отправьте задание'}</p>

        <div class="tip-card">
          <div class="tip-header">
            <svg class="tip-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 18h6"/>
              <path d="M10 22h4"/>
              <path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/>
            </svg>
            <span class="tip-label">СОВЕТ</span>
          </div>
          <p class="tip-text">{currentTip}</p>
        </div>

        {#if quickStartCommands.length > 0}
          <div class="quick-start">
            <span class="quick-start-label">С чего начнём?</span>
            <div class="quick-start-grid">
              {#each quickStartCommands.slice(0, 3) as cmd}
                <button class="quick-start-card" onclick={() => { pendingCommand.set(cmd.command); }}>
                  <span class="qs-label">{cmd.label}</span>
                </button>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {:else if searchQuery && filteredMessages.length === 0}
      <div class="empty">
        <p class="empty-text">Ничего не найдено</p>
        <p class="empty-hint">Попробуйте другой запрос</p>
      </div>
    {:else}
      {#each filteredMessages as msg, idx}
        <div class="message message-{msg.role}" title={formatTime(msg.ts)}>
          {#if msg.role === 'assistant'}
            <!-- Structured rendering for complete messages with ## headings -->
            {@const sections = parseResponseSections(msg.content)}
            {@const isLastMsg = idx === filteredMessages.length - 1}
            {@const isStructured = shouldRenderStructured(sections) && !(isLastMsg && $isLoading)}
            {@const isSlideResponse = isStructured && isSlideDeckResponse(sections)}
            {#if isSlideResponse && !collapsedMessages.has(idx)}
              <!-- Slide deck: preamble + compact card + synthesis -->
              {@const split = splitSlideSections(sections)}
              {@const firstT = cleanSlideTitle(split.slides[0]?.title || '')}
              {@const lastT = cleanSlideTitle(split.slides[split.slides.length - 1]?.title || '')}
              {@const origIdx = searchQuery.trim() ? $messages.indexOf(msg) : idx}
              <div class="structured-response" class:response-complete={lastResponseComplete && idx === filteredMessages.length - 1}>
                {#each split.preamble as sec}
                  <ResponseSection title={sec.title} content={sec.content} level={sec.level}
                    onRefine={(title) => { inputText = `Доработай раздел "${title}": `; textareaRef?.focus(); }} />
                {/each}
                <button class="slide-deck-summary" onclick={() => onShowSlides?.(origIdx)}>
                  <span class="sds-icon">▦</span>
                  <span class="sds-range">Слайды {firstT.num}–{lastT.num}</span>
                  <span class="sds-titles">{firstT.name} → {lastT.name}</span>
                  <span class="sds-arrow">→</span>
                </button>
                {#each split.synthesis as sec}
                  <ResponseSection title={sec.title} content={sec.content} level={sec.level}
                    onRefine={(title) => { inputText = `Доработай раздел "${title}": `; textareaRef?.focus(); }} />
                {/each}
                <span class="msg-time structured-time">{formatTime(msg.ts)}</span>
              </div>
            {:else if isStructured && !collapsedMessages.has(idx)}
              <div class="structured-response" class:response-complete={lastResponseComplete && idx === filteredMessages.length - 1}>
                <!-- Mini-TOC for 3+ sections -->
                {#if sections.filter(s => s.title).length >= 3}
                  <div class="mini-toc">
                    {#each sections.filter(s => s.title) as sec, si}
                      <button class="toc-chip" onclick={() => { const el = document.getElementById(`sec-${idx}-${si}`); el?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}>
                        {sec.title}
                      </button>
                    {/each}
                  </div>
                {/if}
                {#each sections as sec, si}
                  <div id="sec-{idx}-{si}">
                    <ResponseSection
                      title={sec.title}
                      content={sec.content}
                      level={sec.level}
                      onRefine={(title) => { inputText = `Доработай раздел "${title}": `; textareaRef?.focus(); }}
                    />
                  </div>
                {/each}
                <span class="msg-time structured-time">{formatTime(msg.ts)}</span>
              </div>
            {:else}
            <!-- Standard bubble rendering (fallback or collapsed) -->
            <div class="message-bubble markdown-body" class:collapsed-bubble={collapsedMessages.has(idx)} class:quick-reply={msg.isQuickReply} class:response-complete={lastResponseComplete && idx === filteredMessages.length - 1}>
              <button
                class="collapse-btn"
                onclick={() => toggleCollapse(idx)}
                title={collapsedMessages.has(idx) ? 'Развернуть' : 'Свернуть'}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                  {#if collapsedMessages.has(idx)}
                    <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                  {:else}
                    <line x1="5" y1="12" x2="19" y2="12"/>
                  {/if}
                </svg>
              </button>
              {#if collapsedMessages.has(idx)}
                <span class="collapsed-preview">{getPreview(msg.content)}</span>
                <span class="msg-time">{formatTime(msg.ts)}</span>
              {:else}
                <div use:highlightAction={searchQuery}>
                  {@html renderMarkdown(msg.content)}
                </div>
                <span class="msg-time">{formatTime(msg.ts)}</span>
                <button
                  class="copy-btn"
                  onclick={() => copyMessage(msg.content, idx)}
                  title="Копировать"
                >
                  {#if copiedIdx === idx}<Check size={14} strokeWidth={1.5} style="vertical-align: -0.15em" />{:else}<Copy size={14} strokeWidth={1.5} style="vertical-align: -0.15em" />{/if}
                </button>
              {/if}
            </div>
            {/if}
            {#if !collapsedMessages.has(idx)}
              {#if !ratedIdx.has(idx)}
                <div class="rating-widget">
                  <button class="rate-btn rate-up" onclick={() => rateMessage(idx, 1)} title="Хороший ответ">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
                    </svg>
                  </button>
                  <button class="rate-btn rate-down" onclick={() => rateMessage(idx, -1)} title="Плохой ответ">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/>
                    </svg>
                  </button>
                </div>
              {:else}
                <div class="rating-done">Спасибо!</div>
              {/if}
            {/if}
            <!-- Response actions (Уточнить/Глубже/Рекомендации) - отключены, не функциональны -->

          {:else}
            {#if msg.isAutoContinue}
              <div class="message-bubble auto-continue-bubble">
                <span class="auto-continue-icon">↻</span> Авто-продолжение
              </div>
            {:else}
              <div class="message-bubble" use:highlightAction={searchQuery}>
                {msg.content}
                <span class="msg-time">{formatTime(msg.ts)}</span>
              </div>
            {/if}
          {/if}
        </div>
      {/each}
      {#if $isLoading && !statusText && !progressPhase}
        <div class="message message-assistant">
          <div class="message-bubble typing">
            <span class="dot"></span>
            <span class="dot"></span>
            <span class="dot"></span>
          </div>
        </div>
      {/if}
      {#if $isLoading && progressPhase}
        <!-- PSY-3: Progress indicator с фазами -->
        <div class="progress-block">
          <div class="progress-bar">
            <div class="progress-fill" style="width: {((progressIndex + 1) / progressTotal) * 100}%"></div>
          </div>
          <span class="progress-label">{progressPhase}</span>
          {#if slideProgress.current > 0}
            <span class="slide-counter">Слайд {slideProgress.current}{slideProgress.total ? `/${slideProgress.total}` : ''}</span>
          {/if}
          {#if currentInsight}
            <!-- PSY-2: Insight во время загрузки -->
            <div class="insight-card">
              <svg class="insight-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/>
              </svg>
              <span class="insight-text">{currentInsight}</span>
            </div>
          {/if}
        </div>
      {/if}
      {#if statusText}
        <div class="status-block">
          <span class="status-spinner">{statusText.startsWith('Готово') ? '\u2713' : '\u27F3'}</span>
          <span class="status-text">{statusText}</span>
        </div>
      {/if}
      {#if completionStats}
        <div class="completion-card" transition:fade={{ duration: $prefersReducedMotion ? 0 : 300 }}>
          <span class="cc-time">Готово за {completionStats.elapsed}с</span>
          <div class="cc-stats">
            <span>{completionStats.slides} {pluralRu(completionStats.slides, 'слайд', 'слайда', 'слайдов')}</span>
            {#if completionStats.anomalies > 0}<span class="cc-warning">{completionStats.anomalies} {pluralRu(completionStats.anomalies, 'аномалия', 'аномалии', 'аномалий')}</span>{/if}
            {#if completionStats.recommendations > 0}<span>{completionStats.recommendations} {pluralRu(completionStats.recommendations, 'рекомендация', 'рекомендации', 'рекомендаций')}</span>{/if}
            {#if completionStats.bridges > 0}<span>{completionStats.bridges} {pluralRu(completionStats.bridges, 'мост', 'моста', 'мостов')}</span>{/if}
          </div>
          {#if completionStats.contextInsight}
            <div class="cc-insight">{completionStats.contextInsight}</div>
          {/if}
        </div>
      {/if}
      <!-- PSY-1: Next Steps - отключены (предлагали другие кабинеты, а не команды текущего) -->
      <!-- TODO: заменить на in-cabinet next commands (следующие шаги внутри текущего кабинета) -->
      {#if false && nextSteps.length > 0 && !$isLoading}
        <div class="next-steps">
          <span class="next-steps-label">Следующий шаг:</span>
          <div class="next-steps-chips">
            {#each nextSteps as step}
              <button
                class="next-step-chip"
                onclick={() => navigateToNextCabinet(step)}
                title={step.reason}
              >
                <span class="chip-label">{step.label}</span>
                <span class="chip-reason">{step.reason}</span>
              </button>
            {/each}
          </div>
        </div>
      {/if}
    {/if}
  </div>

  <div class="input-area">
    {#if $messages.length > 0 && !$isLoading}
      <button class="search-toggle-btn" onclick={toggleSearch} title="Поиск (Ctrl+F)" class:active={searchOpen}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
      </button>
      {#if filteredMessages.some(m => m.role === 'assistant')}
        <button class="collapse-all-btn" onclick={toggleCollapseAll} title={collapsedMessages.size > 0 ? 'Развернуть все ответы' : 'Свернуть все ответы'}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            {#if collapsedMessages.size > 0}
              <path d="M4 7h16M4 12h16M4 17h16"/><line x1="20" y1="7" x2="20" y2="7.01"/>
            {:else}
              <path d="M4 7h10M4 12h10M4 17h10"/>
            {/if}
          </svg>
        </button>
      {/if}
    {/if}
    <button class="clear-history-btn" onclick={clearHistory} disabled={$messages.length === 0 || $isLoading} title="Очистить чат">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <polyline points="3 6 5 6 21 6"/>
        <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
      </svg>
    </button>
    <div class="input-wrapper" class:command-mode={isCommandInput}>
      {#if isCommandInput}
        <span class="command-badge">Команда</span>
      {/if}
      <textarea
        bind:this={textareaRef}
        class="input"
        placeholder={dynamicPlaceholder}
        bind:value={inputText}
        onkeydown={handleKeydown}
        disabled={$isLoading}
        rows="1"
      ></textarea>
    </div>
    {#if $isLoading}
      <button class="stop-btn" onclick={cancelClaude} title="Остановить">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <rect x="4" y="4" width="16" height="16" rx="2"/>
        </svg>
      </button>
    {:else}
      <button
        class="send-btn"
        onclick={sendMessage}
        disabled={!inputText.trim()}
        title="Отправить"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          <path d="M2 21l21-9L2 3v7l15 2-15 2v7z"/>
        </svg>
      </button>
    {/if}
  </div>
</div>

<style>
  /* Phase 2.2: quick-reply animation (CSS вместо setTimeout - BUG-3 fix) */
  @keyframes fadeSlideIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }
  :global(.message-assistant:last-child .message-bubble.quick-reply) {
    animation: fadeSlideIn 0.3s ease-out;
  }

  .chat {
    flex: 1 1 0;
    display: flex;
    flex-direction: column;
    min-width: 0;
    overflow: hidden;
    background: transparent;
  }

  /* ── Search Bar ── */
  .chat-header {
    flex-shrink: 0;
  }

  .search-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    background: var(--panel-bg);
    backdrop-filter: var(--blur-quiet);
    -webkit-backdrop-filter: var(--blur-quiet);
    border-bottom: 1px solid var(--border);
    animation: fadeIn 0.2s ease;
  }

  .search-icon {
    color: var(--text-muted);
    flex-shrink: 0;
  }

  .search-input {
    flex: 1;
    background: var(--input-bg);
    border: 1px solid var(--input-border);
    color: var(--text-primary);
    padding: 6px 10px;
    border-radius: var(--radius-input);
    font-size: 13px;
    min-width: 0;
    transition: border-color var(--transition-fast);
  }

  .search-input:focus {
    border-color: var(--border-active);
    outline: none;
  }

  .search-input::placeholder {
    color: var(--text-muted);
  }

  .search-count {
    font-size: 11px;
    color: var(--text-muted);
    background: var(--accent-glow);
    padding: 2px 7px;
    border-radius: 10px;
    flex-shrink: 0;
  }

  .search-close {
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    color: var(--text-muted);
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
    flex-shrink: 0;
    transition: all 0.15s ease;
  }

  .search-close:hover {
    color: var(--text-primary);
    background: var(--hover-bg);
  }

  .search-toggle-btn {
    width: 36px;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    cursor: pointer;
    flex-shrink: 0;
    transition: all var(--transition-fast);
  }

  .search-toggle-btn:hover {
    color: var(--text-primary);
    background: var(--accent-glow);
    border-color: var(--accent-glow);
  }

  .search-toggle-btn.active {
    color: var(--accent-primary);
    background: var(--accent-glow);
    border-color: var(--accent-glow-strong);
  }

  /* ── Search highlight ── */
  .chat :global(mark) {
    background: color-mix(in srgb, var(--accent-secondary) 30%, transparent);
    color: inherit;
    border-radius: 2px;
    padding: 0 1px;
  }

  .messages {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 24px 28px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  /* ── Empty State ── */
  .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    gap: 4px;
  }

  .empty-icon {
    width: 52px;
    height: 52px;
    margin-bottom: 14px;
    opacity: 0.65;
  }

  .empty-icon svg {
    width: 100%;
    height: 100%;
  }

  .empty-text {
    font-size: 15px;
    color: var(--text-secondary);
    font-weight: 500;
  }

  .empty-hint {
    font-size: 12.5px;
    color: var(--text-muted);
  }

  /* ── Tip Card (INSIGHT-style) ── */
  .tip-card {
    margin-top: 20px;
    max-width: 380px;
    padding: 14px 16px;
    border: 1px solid color-mix(in srgb, var(--accent-secondary) 15%, transparent);
    border-left: 3px solid var(--accent-secondary);
    border-radius: 8px;
    background: color-mix(in srgb, var(--accent-secondary) 7%, transparent);
    animation: fadeIn 0.3s ease;
  }

  .tip-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
  }

  .tip-icon {
    color: var(--accent-secondary);
    opacity: 0.85;
    flex-shrink: 0;
  }

  .tip-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.1em;
    color: var(--accent-secondary);
    opacity: 0.85;
  }

  .tip-text {
    font-size: 12.5px;
    line-height: 1.55;
    color: var(--text-secondary);
  }

  /* ── Quick Start cards (Phase 3.2) ── */
  .quick-start {
    margin-top: 16px;
    text-align: center;
  }
  .quick-start-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    display: block;
    margin-bottom: 10px;
  }
  .quick-start-grid {
    display: flex;
    gap: 8px;
    justify-content: center;
    flex-wrap: wrap;
  }
  .quick-start-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 16px;
    cursor: pointer;
    transition: all 0.15s ease;
    min-width: 120px;
  }
  .quick-start-card:hover {
    border-color: var(--accent-primary);
    background: var(--bg-tertiary, var(--bg-secondary));
    transform: translateY(-1px);
  }
  .qs-label {
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
  }

  /* ── Phase 4.2: Micro-celebration pulse ── */
  @keyframes response-pulse {
    0% { box-shadow: 0 0 0 0 var(--accent-glow-strong); }
    70% { box-shadow: 0 0 0 6px transparent; }
    100% { box-shadow: 0 0 0 0 transparent; }
  }
  .response-complete {
    animation: response-pulse 0.6s ease-out;
  }

  /* ── Phase 4.3: Response actions ── */
  .response-actions {
    display: flex;
    gap: 6px;
    margin-top: 8px;
    flex-wrap: wrap;
  }
  .action-btn {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 4px 12px;
    font-size: 12px;
    color: var(--text-secondary);
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .action-btn:hover {
    border-color: var(--accent-primary);
    color: var(--accent-primary);
    background: var(--bg-tertiary, var(--bg-secondary));
  }

  /* ── Messages ── */
  .message {
    display: flex;
    animation: fadeIn 0.2s ease;
  }

  .message-user {
    justify-content: flex-end;
  }

  .message-bubble {
    max-width: 76%;
    padding: 11px 16px;
    border-radius: var(--radius-md);
    font-size: 14px;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
  }

  /* User: solid accent */
  .message-user .message-bubble {
    background: var(--accent-primary);
    color: white;
    border-bottom-right-radius: 4px;
    box-shadow: var(--shadow-glow);
  }

  /* Assistant: glass */
  .message-assistant .message-bubble {
    background: var(--bg-glass);
    backdrop-filter: var(--blur-quiet);
    -webkit-backdrop-filter: var(--blur-quiet);
    border: 1px solid var(--input-border);
    border-bottom-left-radius: 4px;
    white-space: normal;
    position: relative;
  }

  /* ── Markdown body ── */
  .markdown-body :global(h1) { font-size: 1.35em; font-weight: 700; margin: 16px 0 8px; letter-spacing: -0.02em; }
  .markdown-body :global(h2) { font-size: 1.15em; font-weight: 700; margin: 14px 0 6px; letter-spacing: -0.01em; }
  .markdown-body :global(h3) { font-size: 1.04em; font-weight: 600; margin: 12px 0 4px; }
  .markdown-body :global(h4) { font-size: 1em; font-weight: 600; margin: 10px 0 4px; }

  .markdown-body :global(p) { margin: 6px 0; }
  .markdown-body :global(p:first-child) { margin-top: 0; }
  .markdown-body :global(p:last-child) { margin-bottom: 0; }

  .markdown-body :global(ul),
  .markdown-body :global(ol) { margin: 6px 0; padding-left: 20px; }
  .markdown-body :global(li) { margin: 2px 0; }

  .markdown-body :global(pre) {
    background: var(--code-bg);
    border: 1px solid var(--border);
    padding: 12px 14px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 8px 0;
    font-size: 12.5px;
    line-height: 1.5;
    font-family: var(--font-mono);
  }

  .markdown-body :global(code) {
    background: var(--accent-glow);
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 12.5px;
    font-family: var(--font-mono);
    color: var(--accent-text-light);
  }

  .markdown-body :global(pre code) {
    background: none;
    padding: 0;
    border-radius: 0;
    color: inherit;
  }

  .markdown-body :global(table) {
    border-collapse: collapse;
    margin: 8px 0;
    width: 100%;
    font-size: 13px;
  }

  .markdown-body :global(th),
  .markdown-body :global(td) {
    border: 1px solid var(--border);
    padding: 6px 10px;
    text-align: left;
  }

  .markdown-body :global(th) {
    background: var(--accent-glow);
    font-weight: 600;
    color: var(--accent-text-light);
  }

  .markdown-body :global(blockquote) {
    border-left: 2px solid var(--accent-primary);
    margin: 8px 0;
    padding: 4px 12px;
    color: var(--text-secondary);
    font-style: italic;
    background: var(--accent-glow);
    border-radius: 0 6px 6px 0;
  }

  .markdown-body :global(hr) {
    border: none;
    border-top: 1px solid var(--border);
    margin: 12px 0;
  }

  .markdown-body :global(strong) { font-weight: 700; }
  .markdown-body :global(em) { font-style: italic; }

  .markdown-body :global(a) {
    color: var(--accent-text-light);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  /* ── Copy Button ── */
  .copy-btn {
    position: absolute;
    top: 7px;
    right: 7px;
    width: 26px;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: 5px;
    color: var(--text-muted);
    font-size: 13px;
    cursor: pointer;
    opacity: 0;
    transition: opacity var(--transition-fast), background var(--transition-fast);
  }

  .message-bubble:hover .copy-btn {
    opacity: 1;
  }

  .copy-btn:hover {
    background: var(--accent-glow-strong);
    border-color: var(--accent-glow-strong);
    color: var(--accent-text-light);
  }

  /* ── System / Error ── */
  .message-system .message-bubble {
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    color: var(--danger);
    border: 1px solid color-mix(in srgb, var(--danger) 20%, transparent);
    border-radius: var(--radius-sm);
    font-size: 13px;
  }

  /* ── Typing Indicator ── */
  .typing {
    display: flex;
    gap: 5px;
    padding: 14px 18px;
    align-items: center;
  }

  .dot {
    width: 6px;
    height: 6px;
    background: var(--accent-primary);
    border-radius: 50%;
    animation: bounce 1.4s infinite ease-in-out;
    opacity: 0.7;
  }

  .dot:nth-child(1) { animation-delay: 0s; }
  .dot:nth-child(2) { animation-delay: 0.22s; }
  .dot:nth-child(3) { animation-delay: 0.44s; }

  /* ── Status ── */
  .status-block {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    font-size: 12px;
    color: var(--text-muted);
  }

  .status-spinner {
    display: inline-block;
    animation: spin-status 1s linear infinite;
    font-size: 13px;
    color: var(--accent-primary);
  }

  .status-text {
    font-style: italic;
    color: var(--text-muted);
  }

  /* ── Input Area ── */
  .input-area {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    padding: 14px 20px;
    border-top: 1px solid var(--border);
    background: var(--panel-bg);
    backdrop-filter: var(--blur-quiet);
    -webkit-backdrop-filter: var(--blur-quiet);
  }

  /* Phase 3.3: Command mode indicator */
  .input-wrapper {
    flex: 1;
    position: relative;
    display: flex;
    flex-direction: column;
  }
  .input-wrapper.command-mode .input {
    border-color: var(--accent-primary, #7c3aed);
    box-shadow: 0 0 0 2px var(--accent-glow);
  }
  .command-badge {
    position: absolute;
    top: -8px;
    left: 12px;
    background: var(--accent-primary, #7c3aed);
    color: var(--text-on-accent, #fff);
    font-size: 10px;
    font-weight: 600;
    padding: 1px 6px;
    border-radius: var(--radius-chip);
    z-index: 1;
    letter-spacing: 0.3px;
  }

  .input {
    flex: 1;
    resize: none;
    background: var(--input-bg);
    border: 1px solid var(--input-border);
    color: var(--text-primary);
    padding: 12px 16px;
    border-radius: var(--radius-input);
    font-size: 14px;
    line-height: 1.5;
    max-height: 140px;
    min-height: 46px;
    transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  }

  .input:focus {
    border-color: var(--border-active);
    box-shadow: 0 0 0 2px var(--accent-glow);
  }

  .input::placeholder {
    color: var(--text-muted);
  }

  .input:disabled {
    opacity: 0.45;
  }

  /* Send button: cobalt → green gradient */
  .send-btn {
    width: 46px;
    height: 46px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--gradient-primary);
    color: white;
    border-radius: var(--radius-btn);
    transition: all var(--transition);
    flex-shrink: 0;
    box-shadow: var(--shadow-glow);
  }

  .send-btn:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: var(--shadow-glow);
    filter: brightness(1.1);
  }

  .send-btn:disabled {
    opacity: 0.5;
    cursor: default;
    box-shadow: none;
  }

  .stop-btn {
    width: 46px;
    height: 46px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: color-mix(in srgb, var(--danger) 12%, transparent);
    color: var(--danger);
    border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
    border-radius: var(--radius-btn);
    transition: all var(--transition);
    flex-shrink: 0;
    cursor: pointer;
  }

  .stop-btn:hover {
    background: color-mix(in srgb, var(--danger) 25%, transparent);
    border-color: color-mix(in srgb, var(--danger) 60%, transparent);
  }

  .rating-widget {
    display: flex;
    gap: 4px;
    margin-top: 4px;
    margin-left: 4px;
    opacity: 0;
    transition: opacity 0.2s ease;
  }

  .message-assistant:hover .rating-widget {
    opacity: 1;
  }

  .rate-btn {
    width: 26px;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: 5px;
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .rate-up:hover {
    color: var(--success, #10B981);
    background: color-mix(in srgb, var(--success) 10%, transparent);
    border-color: color-mix(in srgb, var(--success) 30%, transparent);
  }

  .rate-down:hover {
    color: var(--danger, #EF4444);
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    border-color: color-mix(in srgb, var(--danger) 30%, transparent);
  }

  .rating-done {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 4px;
    margin-left: 4px;
    opacity: 0.6;
  }

  .clear-history-btn,
  .collapse-all-btn {
    width: 36px;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    cursor: pointer;
    flex-shrink: 0;
    transition: all var(--transition-fast);
  }

  .clear-history-btn:hover:not(:disabled) {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    border-color: color-mix(in srgb, var(--danger) 20%, transparent);
  }

  .clear-history-btn:disabled {
    opacity: 0.45;
    cursor: default;
  }

  .collapse-all-btn:hover {
    color: var(--text-primary);
    background: var(--accent-glow);
    border-color: var(--accent-glow);
  }

  /* ── Collapse/Expand for assistant messages ── */
  .collapse-btn {
    position: absolute;
    top: 7px;
    left: 7px;
    width: 22px;
    height: 22px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-muted);
    cursor: pointer;
    opacity: 0;
    transition: opacity var(--transition-fast), background var(--transition-fast);
    z-index: 1;
  }

  .message-bubble:hover .collapse-btn,
  .collapsed-bubble .collapse-btn {
    opacity: 1;
  }

  .collapse-btn:hover {
    background: var(--accent-glow-strong);
    border-color: var(--accent-glow-strong);
    color: var(--accent-text-light);
  }

  .collapsed-bubble {
    padding: 8px 16px 8px 36px;
    cursor: pointer;
  }

  .collapsed-preview {
    font-size: 13px;
    color: var(--text-muted);
    font-style: italic;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
  }

  /* ── Message Timestamp ── */
  .msg-time {
    display: block;
    font-size: 10.5px;
    margin-top: 5px;
    text-align: right;
    opacity: 0.5;
    user-select: none;
    font-variant-numeric: tabular-nums;
  }

  .message-user .msg-time {
    color: var(--text-secondary);
  }

  .message-assistant .msg-time {
    color: var(--text-muted);
    margin-right: 34px; /* не перекрывать copy-btn */
  }

  /* ── PSY-3: Progress Indicator ── */
  .progress-block {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 16px;
    margin: 4px 0;
    background: var(--hover-bg);
    border: 1px solid var(--accent-glow);
    border-radius: 10px;
    animation: fadeIn 0.3s ease;
  }

  .progress-bar {
    height: 3px;
    background: var(--hover-bg);
    border-radius: 2px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent-primary), var(--color-info, var(--accent-secondary)), var(--color-completion, var(--accent-secondary)));
    background-size: 200% 100%;
    animation: progress-hue 45s linear;
    border-radius: 2px;
    transition: width 0.8s ease;
  }

  @keyframes progress-hue {
    0%   { background-position: 0% 50%; }
    100% { background-position: 100% 50%; }
  }

  .progress-label {
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 500;
  }

  .slide-counter {
    font-size: 11px;
    color: var(--text-muted, var(--text-secondary));
    font-variant-numeric: tabular-nums;
    opacity: 0.75;
    letter-spacing: 0.02em;
  }

  /* ── PSY-2: Insight Card ── */
  .insight-card {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 8px 10px;
    background: color-mix(in srgb, var(--accent-secondary) 4%, transparent);
    border-left: 2px solid color-mix(in srgb, var(--accent-secondary) 25%, transparent);
    border-radius: 4px;
    margin-top: 2px;
  }

  .insight-icon {
    color: var(--accent-secondary);
    flex-shrink: 0;
    margin-top: 1px;
  }

  .insight-text {
    font-size: 11.5px;
    color: var(--text-muted);
    line-height: 1.45;
    font-style: italic;
  }

  /* ── C3: Completion Summary Card (Peak-End Rule) ── */
  .completion-card {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    padding: 8px 12px;
    background: var(--bg-surface-focus);
    backdrop-filter: var(--blur-focus);
    -webkit-backdrop-filter: var(--blur-focus);
    border: 1px solid var(--color-completion, var(--accent-primary));
    border-radius: 8px;
    margin-top: 4px;
    animation: glow-pulse 2s ease-in-out 1;
  }

  .cc-time {
    font-size: 12px;
    font-weight: 600;
    color: var(--color-completion, var(--accent-primary));
    white-space: nowrap;
    flex-shrink: 0;
  }

  .cc-stats {
    display: flex;
    flex-direction: row;
    gap: 10px;
    flex-wrap: wrap;
  }

  .cc-stats span {
    font-size: 12px;
    color: var(--text-muted);
    white-space: nowrap;
  }

  .cc-warning {
    color: var(--warning-text) !important;
  }

  /* C6: Context-aware insight - занимает всю строку (flex-wrap новая строка) */
  .cc-insight {
    flex-basis: 100%;
    font-size: 12px;
    color: var(--text-primary, #e2e8f0);
    font-weight: 500;
    padding-top: 4px;
    margin-top: -2px;
    border-top: 1px solid color-mix(in srgb, var(--accent-primary) 25%, transparent);
  }

  /* ── PSY-1: Next Steps Chips ── */
  .next-steps {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 4px;
    animation: fadeIn 0.4s ease;
  }

  .next-steps-label {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 500;
  }

  .next-steps-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .next-step-chip {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 14px;
    background: var(--accent-glow);
    border: 1px solid var(--accent-glow);
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.2s ease;
    text-align: left;
  }

  .next-step-chip:hover {
    background: var(--accent-glow);
    border-color: var(--accent-glow-strong);
    transform: translateY(-1px);
  }

  .chip-label {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--accent-primary);
  }

  .chip-reason {
    font-size: 10.5px;
    color: var(--text-muted);
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }

  /* ─── Structured Response ─── */
  .structured-response {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 76%;
    animation: fadeIn 0.3s ease-out;
  }

  .structured-time {
    font-size: 10px;
    color: var(--text-muted);
    text-align: right;
    margin-top: 4px;
  }

  /* ─── Mini-TOC ─── */
  .mini-toc {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    padding: 8px 0;
    position: sticky;
    top: 0;
    z-index: 5;
    background: var(--bg-primary);
  }

  .toc-chip {
    padding: 4px 10px;
    background: var(--accent-glow);
    border: 1px solid var(--accent-glow);
    border-radius: 12px;
    color: var(--text-secondary);
    font-size: 11px;
    font-family: inherit;
    cursor: pointer;
    transition: all 150ms ease-out;
  }

  .toc-chip:hover {
    background: var(--accent-glow);
    border-color: var(--accent-glow-strong);
    color: var(--accent-primary);
  }

  /* ─── Slide deck compact card ─── */
  .slide-deck-summary {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 12px 16px;
    margin: 6px 0;
    background: var(--accent-glow);
    border: 1px solid var(--accent-glow);
    border-radius: 10px;
    color: var(--text-primary, #EAEAF0);
    font-family: inherit;
    font-size: 13px;
    cursor: pointer;
    transition: all 150ms ease-out;
  }

  .slide-deck-summary:hover {
    background: var(--accent-glow);
    border-color: var(--accent-glow-strong);
  }

  .sds-icon {
    font-size: 18px;
    opacity: 0.7;
    flex-shrink: 0;
  }

  .sds-range {
    font-weight: 600;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .sds-titles {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-muted, #7A7A90);
    font-size: 12px;
  }

  .sds-arrow {
    font-size: 14px;
    opacity: 0.4;
    flex-shrink: 0;
    transition: opacity 150ms;
  }

  .slide-deck-summary:hover .sds-arrow {
    opacity: 1;
  }

  /* ─── Auto-continue compact bubble ─── */
  .auto-continue-bubble {
    font-size: 11px !important;
    padding: 4px 10px !important;
    opacity: 0.5;
    background: var(--text-muted, #7A7A90) !important;
  }

  .auto-continue-icon {
    font-size: 12px;
  }
</style>
