<script>
  import { invoke } from '@tauri-apps/api/core';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { activeCabinet, messages } from '$lib/store.js';
  import { isCreativeHub, ragAvailable, activeBrandId, activeBrand, checkServices } from '$lib/creative-store.js';
  import { classifyIntent, formatGreetingAnswer } from '$lib/data-chat-engine.js';
  import { toast } from '$lib/toast.js';
  import { marked } from 'marked';
  import { MessagesSquare } from 'lucide-svelte';
  import DOMPurify from 'dompurify';
  import { get } from 'svelte/store';
  import { listen } from '@tauri-apps/api/event';

  marked.setOptions({ breaks: true, gfm: true });

  /** @type {'lite'|'pro'} */
  let mode = $derived($isCreativeHub && $ragAvailable ? 'pro' : 'lite');

  /** @type {Array<{role: string, content: string}>} */
  let chatMessages = $state([]);
  let input = $state('');
  let isThinking = $state(false);
  /** @type {HTMLDivElement|undefined} */
  let chatContainer = $state(undefined);

  /** @type {Array<{question: string, subtitle: string, icon: string}>} */
  let suggestions = $state([
    { question: 'Что ты умеешь?', subtitle: 'Узнать о возможностях', icon: '💬' },
    { question: 'Как работают кабинеты?', subtitle: 'Общий обзор', icon: '📋' },
    { question: 'Какие команды доступны?', subtitle: 'Список всех команд', icon: '/' },
  ]);

  /** @param {string} text */
  function renderMarkdown(text) {
    if (!text) return '';
    return DOMPurify.sanitize(/** @type {string} */ (marked.parse(text)));
  }

  function scrollToBottom() {
    if (chatContainer) {
      const el = chatContainer;
      setTimeout(() => el.scrollTop = el.scrollHeight, 50);
    }
  }

  /** @param {string} text */
  async function sendMessage(text) {
    if (!text?.trim() || isThinking) return;
    const question = text.trim();
    input = '';

    chatMessages = [...chatMessages, { role: 'user', content: question }];
    scrollToBottom();
    isThinking = true;

    const { intent } = classifyIntent(question);

    if (intent === 'greeting') {
      const result = formatGreetingAnswer('Aurora AI');
      chatMessages = [...chatMessages, { role: 'assistant', content: result.answer }];
      suggestions = result.suggestions.map(s => ({ question: s, subtitle: '', icon: '💡' }));
      isThinking = false;
      scrollToBottom();
      return;
    }

    if (mode === 'pro') {
      // Data Chat Pro: RAG-powered deep analysis
      await sendProMessage(question, intent);
    } else {
      // Data Chat Lite: helpful routing
      await sendLiteMessage(question, intent);
    }
  }

  /**
   * Lite mode: helpful routing to cabinets
   * @param {string} question
   * @param {string} intent
   */
  async function sendLiteMessage(question, intent) {
    try {
      /** @type {Record<string, string>} */
      const intentDescriptions = {
        profile: 'Для работы с профилем бренда откройте кабинет Копирайтер и используйте `/brand-setup`.',
        stats: 'Откройте страницу бренда (Бренды → выберите бренд) для просмотра статистики.',
        search: 'Для поиска по данным бренда активируйте Creative Hub с RAG-сервером.',
        history: 'История работы кабинетов сохраняется автоматически. Каждый результат доступен в exports соответствующего кабинета.',
        comparison: 'Для сравнения с конкурентами используйте кабинет Коммуникационный аналитик → `/competitors`.',
        analysis: 'Для глубокого анализа откройте подходящий кабинет и задайте вопрос напрямую. Рекомендую:\n\n- **Медиа-аналитик** - для анализа данных и отчётов\n- **Коммуникационный аналитик** - для анализа медиаполя\n- **Эконометрист** - для моделирования и оптимизации',
      };

      const answer = intentDescriptions[intent] || `Хороший вопрос! Для ответа используйте подходящий кабинет:\n\n- **Ctrl+K** → найдите нужный кабинет или команду\n- Перетащите файлы в inbox кабинета для анализа`;

      chatMessages = [...chatMessages, { role: 'assistant', content: answer }];
      suggestions = [
        { question: 'Открыть Command Palette', subtitle: 'Ctrl+K', icon: '⌨' },
        { question: 'Какие кабинеты доступны?', subtitle: '13 экспертов', icon: '*' },
      ];
    } catch (err) {
      chatMessages = [...chatMessages, { role: 'assistant', content: `Ошибка: ${err}` }];
    } finally {
      isThinking = false;
      scrollToBottom();
    }
  }

  /**
   * Pro mode: RAG-powered deep analysis through Claude
   * @param {string} question
   * @param {string} intent
   */
  async function sendProMessage(question, intent) {
    const brandId = get(activeBrandId);
    if (!brandId) {
      chatMessages = [...chatMessages, { role: 'assistant', content: 'Выберите бренд на странице Бренды для использования Data Chat Pro.' }];
      isThinking = false;
      scrollToBottom();
      return;
    }

    try {
      // Assemble context from brand profile + RAG search
      let contextParts = [];

      // Brand profile
      try {
        const profile = /** @type {any} */ (await invoke('brand_get', { brandId }));
        contextParts.push(`## Профиль бренда\n- Название: ${profile.name}\n- Индустрия: ${profile.industry || 'не указана'}\n- Описание: ${profile.description || 'не указано'}`);
      } catch { /* ignore */ }

      // RAG vector search
      try {
        const searchResults = /** @type {any} */ (await invoke('brand_search', { brandId, query: question, topK: 5 }));
        if (searchResults?.results?.length > 0) {
          const snippets = searchResults.results.map((/** @type {any} */ r) => `- ${r.text || r.content || JSON.stringify(r)}`).join('\n');
          contextParts.push(`## Релевантные данные из базы знаний\n${snippets}`);
        }
      } catch {
        // RAG search failed - might have gone down mid-session
      }

      // History search
      try {
        const histResults = /** @type {any[]} */ (await invoke('brand_history_search', { brandId, query: question }));
        if (histResults.length > 0) {
          const histSnippets = histResults.slice(0, 3).map((/** @type {any} */ r) => `- [${r.cabinet}/${r.filename}]: ${r.excerpt}`).join('\n');
          contextParts.push(`## История кабинетов\n${histSnippets}`);
        }
      } catch { /* ignore */ }

      const contextMarkdown = contextParts.join('\n\n') || 'Нет данных по бренду.';

      // Stream response through Claude
      /** @type {string} */
      let responseText = '';
      const unlisten = await listen('claude-stream-data-chat', (event) => {
        const payload = /** @type {string} */ (event.payload);
        try {
          const data = JSON.parse(payload);
          if (data.type === 'content') {
            responseText += data.text || '';
            // Update last message reactively
            chatMessages = [...chatMessages.slice(0, -1), { role: 'assistant', content: responseText }];
            scrollToBottom();
          }
        } catch { /* non-JSON stream data */ }
      });

      // Add placeholder for streaming
      chatMessages = [...chatMessages, { role: 'assistant', content: '...' }];

      await invoke('data_chat_deep', {
        brandId,
        question,
        contextMarkdown,
      });

      unlisten();

      // If no streaming happened, show the final state
      if (!responseText) {
        chatMessages = [...chatMessages.slice(0, -1), { role: 'assistant', content: 'Анализ завершён. Ответ был передан через Claude.' }];
      }

      suggestions = [];
    } catch (err) {
      // RAG might have gone down - fallback to Lite
      const errStr = String(err);
      if (errStr.includes('RAG') || errStr.includes('unavailable')) {
        ragAvailable.set(false);
        toast('RAG-сервер недоступен, переключаюсь на Lite', 'info');
        chatMessages = [...chatMessages, { role: 'assistant', content: 'RAG-сервер стал недоступен. Переключён в режим Lite.' }];
      } else {
        chatMessages = [...chatMessages, { role: 'assistant', content: `Ошибка: ${err}` }];
      }
    } finally {
      isThinking = false;
      scrollToBottom();
    }
  }

  function clearChat() {
    chatMessages = [];
    suggestions = [
      { question: 'Что ты умеешь?', subtitle: 'Узнать о возможностях', icon: '💬' },
      { question: 'Как работают кабинеты?', subtitle: 'Общий обзор', icon: '📋' },
      { question: 'Какие команды доступны?', subtitle: 'Список всех команд', icon: '/' },
    ];
  }
</script>

<div class="data-chat-page">
  <div class="chat-container">
    <div class="chat-header">
      <button class="back-link" onclick={() => goto('/')}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M19 12H5M12 19l-7-7 7-7"/>
        </svg>
        Назад
      </button>
      <h1 class="chat-title">Data Chat</h1>
      <span class="chat-badge" class:pro={mode === 'pro'}>{mode === 'pro' ? 'Pro' : 'Lite'}</span>
      {#if mode === 'pro' && $activeBrand}
        <span class="brand-indicator">{$activeBrand.name}</span>
      {:else if mode === 'pro'}
        <a href="/brands" class="brand-indicator no-brand">Выберите бренд</a>
      {/if}
      {#if chatMessages.length > 0}
        <button class="btn-clear" onclick={clearChat}>Очистить</button>
      {/if}
    </div>

    <div class="chat-body" bind:this={chatContainer}>
      {#if chatMessages.length === 0}
        <div class="welcome">
          <div class="welcome-icon"><MessagesSquare size={28} strokeWidth={1.5} /></div>
          <h2 class="welcome-title">Спросите о чём угодно</h2>
          <p class="welcome-desc">Data Chat Lite отвечает на вопросы и направляет к нужным кабинетам. Полный анализ данных бренда - в v0.5.0.</p>

          <div class="suggestions">
            {#each suggestions as s}
              <button class="suggestion-card" onclick={() => sendMessage(s.question)}>
                <span class="suggestion-icon">{s.icon}</span>
                <div class="suggestion-text">
                  <span class="suggestion-q">{s.question}</span>
                  {#if s.subtitle}
                    <span class="suggestion-sub">{s.subtitle}</span>
                  {/if}
                </div>
              </button>
            {/each}
          </div>
        </div>
      {:else}
        {#each chatMessages as msg}
          <div class="msg msg-{msg.role}">
            <div class="msg-content">{@html renderMarkdown(msg.content)}</div>
          </div>
        {/each}
        {#if isThinking}
          <div class="msg msg-assistant">
            <div class="msg-content thinking">Думаю...</div>
          </div>
        {/if}

        {#if suggestions.length > 0 && !isThinking}
          <div class="suggestions-inline">
            {#each suggestions as s}
              <button class="suggestion-chip" onclick={() => sendMessage(s.question)}>
                {s.icon} {s.question}
              </button>
            {/each}
          </div>
        {/if}
      {/if}
    </div>

    <div class="chat-input-bar">
      <input
        class="chat-input"
        type="text"
        placeholder="Задайте вопрос..."
        bind:value={input}
        onkeydown={(e) => e.key === 'Enter' && sendMessage(input)}
        disabled={isThinking}
      />
      <button class="btn-send" onclick={() => sendMessage(input)} disabled={isThinking || !input.trim()}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
        </svg>
      </button>
    </div>
  </div>
</div>

<style>
  .data-chat-page {
    min-height: 100vh;
    display: flex;
    justify-content: center;
    padding: 0;
    background: var(--bg-primary);
  }

  .chat-container {
    width: 100%;
    max-width: 700px;
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .chat-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 24px;
    border-bottom: 1px solid var(--hover-bg);
  }

  .back-link {
    display: flex;
    align-items: center;
    gap: 5px;
    color: var(--text-muted);
    font-size: 12px;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
  }

  .back-link:hover { color: var(--text-primary); }

  .chat-title { font-size: 18px; font-weight: 700; flex: 1; }

  .chat-badge {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--accent-primary);
    background: var(--accent-glow);
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
  }

  .chat-badge.pro {
    color: var(--accent-tertiary, #a78bfa);
    background: color-mix(in srgb, var(--accent-tertiary, #a78bfa) 15%, transparent);
  }

  .brand-indicator {
    font-size: 11px;
    color: var(--text-secondary);
    background: var(--hover-bg);
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid var(--hover-bg);
    text-decoration: none;
  }

  .brand-indicator.no-brand {
    color: var(--warning, #f59e0b);
    border-color: color-mix(in srgb, var(--warning, #f59e0b) 30%, transparent);
  }

  .btn-clear {
    font-size: 11px;
    color: var(--text-muted);
    background: none;
    border: 1px solid var(--border);
    padding: 4px 10px;
    border-radius: 6px;
    cursor: pointer;
  }

  .chat-body {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
  }

  .welcome {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    text-align: center;
    gap: 12px;
  }

  .welcome-icon { font-size: 40px; }
  .welcome-title { font-size: 20px; font-weight: 700; }
  .welcome-desc { font-size: 13px; color: var(--text-muted); max-width: 400px; line-height: 1.5; }

  .suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: center;
    margin-top: 16px;
  }

  .suggestion-card {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    background: var(--bg-glass);
    backdrop-filter: var(--blur-quiet);
    border: 1px solid var(--hover-bg);
    border-radius: 12px;
    cursor: pointer;
    text-align: left;
    color: var(--text-secondary);
    transition: all 0.15s ease;
    max-width: 220px;
  }

  .suggestion-card:hover {
    border-color: var(--accent-primary);
    color: var(--text-primary);
  }

  .suggestion-icon { font-size: 20px; flex-shrink: 0; }
  .suggestion-text { display: flex; flex-direction: column; gap: 2px; }
  .suggestion-q { font-size: 13px; font-weight: 500; }
  .suggestion-sub { font-size: 11px; color: var(--text-muted); }

  .msg { margin-bottom: 16px; }

  .msg-user .msg-content {
    background: var(--accent-primary);
    color: var(--text-on-accent, #fff);
    padding: 10px 14px;
    border-radius: 12px 12px 4px 12px;
    margin-left: auto;
    max-width: 80%;
    font-size: 13px;
    width: fit-content;
  }

  .msg-assistant .msg-content {
    background: var(--hover-bg);
    border: 1px solid var(--hover-bg);
    padding: 12px 16px;
    border-radius: 12px 12px 12px 4px;
    max-width: 90%;
    font-size: 13px;
    line-height: 1.6;
  }

  .msg-assistant .msg-content :global(h2) { font-size: 15px; margin: 0 0 8px; }
  .msg-assistant .msg-content :global(h3) { font-size: 13px; margin: 12px 0 4px; }
  .msg-assistant .msg-content :global(ul) { padding-left: 16px; margin: 4px 0; }
  .msg-assistant .msg-content :global(li) { margin: 2px 0; }
  .msg-assistant .msg-content :global(strong) { color: var(--text-primary); }
  .msg-assistant .msg-content :global(code) { background: var(--hover-bg); padding: 1px 4px; border-radius: 3px; font-size: 12px; }

  .thinking { color: var(--text-muted); animation: pulse 1.5s infinite; }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  .suggestions-inline {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
  }

  .suggestion-chip {
    padding: 6px 12px;
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: 20px;
    font-size: 12px;
    color: var(--text-secondary);
    cursor: pointer;
    transition: all 0.15s;
  }

  .suggestion-chip:hover {
    border-color: var(--accent-primary);
    color: var(--text-primary);
  }

  .chat-input-bar {
    display: flex;
    gap: 8px;
    padding: 16px 24px;
    border-top: 1px solid var(--hover-bg);
  }

  .chat-input {
    flex: 1;
    padding: 10px 14px;
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text-primary);
    font-size: 13px;
    outline: none;
  }

  .chat-input:focus { border-color: var(--accent-primary); }
  .chat-input:disabled { opacity: 0.5; }

  .btn-send {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    background: var(--accent-primary);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.15s;
  }

  .btn-send:hover { filter: brightness(1.15); }
  .btn-send:disabled { opacity: 0.3; cursor: not-allowed; }
</style>
