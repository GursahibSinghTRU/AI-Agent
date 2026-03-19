/**
 * TRU Risk & Safety Assistant Chatbot Widget — chatbot.js
 * Connects to the local FastAPI RAG backend (port 8000).
 * Streams answers via SSE and renders document citations.
 */

(function () {
  'use strict';

  // ── Markdown ────────────────────────────────────────────

  function renderMarkdown(text) {
    if (window.marked) {
      marked.setOptions({ breaks: true, gfm: true });
      const html = marked.parse(text);
      console.log('[TRU Chat] Rendered markdown HTML:', html);
      return html;
    }
    // Fallback: escape HTML, preserve newlines
    return text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>');
  }

  // ── Config ─────────────────────────────────────────────

  const CONFIG = {
    apiStream:  '/api/chat/stream',
    apiHealth:  '/api/health',
    timeoutMs:  120_000,
    connectMs:  5_000,
  };

  const QUICK_REPLIES = [
    { label: '� Emergency procedures', text: 'What should I do if I witness an emergency on campus?' },
    { label: '📝 Incident reporting', text: 'How do I report a workplace incident to Risk and Safety Services?' },
    { label: '👷 Safety training', text: 'What training courses are required for TRU staff?' },
    { label: '🚨 Safety alerts', text: 'How can I stay informed about campus safety alerts?' },
    { label: '💼 Workplace ergonomics', text: 'What are best practices for desk safety and ergonomics?' },
  ];

  // ── State ───────────────────────────────────────────────

  let isOpen       = false;
  let isLoading    = false;
  let isConnected  = false;
  let chatHistory  = [];
  let unreadCount  = 0;

  // ── DOM Refs ────────────────────────────────────────────

  let fab, chatWindow, messagesEl, textareaEl, sendBtn, statusDot, statusLabel, badge;

  // ── Init ────────────────────────────────────────────────

  function init() {
    injectHTML();
    cacheDOMRefs();
    bindEvents();
    checkConnection();
  }

  // ── HTML Injection ──────────────────────────────────────

  function injectHTML() {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = `
<!-- TRU Policy Chatbot FAB -->
<button id="tru-chat-fab" aria-label="Open TRU Risk & Safety Assistant" title="Ask about TRU Safety & Risk">
  <span class="fab-badge" id="tru-fab-badge"></span>
  <svg class="fab-icon-chat" width="26" height="26" fill="none" viewBox="0 0 24 24" stroke="white" stroke-width="1.8">
    <path stroke-linecap="round" stroke-linejoin="round"
      d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.94L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
  </svg>
  <svg class="fab-icon-close" width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="white" stroke-width="2">
    <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
  </svg>
</button>

<!-- TRU Policy Chat Window -->
<div id="tru-chat-window" role="dialog" aria-label="TRU Risk & Safety Assistant" aria-modal="false">

  <!-- Header -->
  <div class="tru-chat-header">
    <div class="tru-chat-header-avatar" aria-hidden="true">📋</div>
    <div class="tru-chat-header-info">
      <div class="tru-chat-header-name">TRU Risk & Safety Assistant</div>
      <div class="tru-chat-header-status">
        <span class="tru-status-dot connecting" id="tru-status-dot"></span>
        <span id="tru-status-label">Connecting…</span>
      </div>
    </div>
    <div class="tru-chat-header-actions">
      <button class="tru-chat-header-btn" id="tru-clear-btn" title="Clear conversation" aria-label="Clear conversation">
        <svg width="17" height="17" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round"
            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
        </svg>
      </button>
      <button class="tru-chat-header-btn" id="tru-close-btn" title="Close chat" aria-label="Close chat">
        <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    </div>
  </div>

  <!-- Yellow accent strip -->
  <div class="tru-header-accent"></div>

  <!-- Messages -->
  <div class="tru-chat-messages" id="tru-messages">
    ${buildWelcomeHTML()}
  </div>

  <!-- Input -->
  <div class="tru-chat-input-area">
    <div class="tru-chat-input-wrap">
      <textarea
        class="tru-chat-textarea"
        id="tru-input"
        placeholder="Ask a policy question…"
        rows="1"
        aria-label="Type your policy question"
      ></textarea>
    </div>
    <button class="tru-send-btn" id="tru-send-btn" aria-label="Send message" disabled>
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
      </svg>
    </button>
  </div>

  <!-- Footer -->
  <div class="tru-chat-footer">
    Answers sourced from TRU policy documents · <a href="https://www.tru.ca" target="_blank" rel="noopener">tru.ca</a>
  </div>
</div>`;

    Array.from(wrapper.childNodes).forEach((node) => {
      if (node.nodeType === 1 || node.nodeType === 3) {
        document.body.appendChild(node);
      }
    });
  }

  function buildWelcomeHTML() {
    const chips = QUICK_REPLIES.map(
      (q) => `<button class="tru-quick-reply-chip" data-text="${escapeAttr(q.text)}">${q.label}</button>`
    ).join('');
    return `
<div class="tru-welcome" id="tru-welcome-block">
  <div class="tru-welcome-logo">📋</div>
  <h3>Policy Assistant</h3>
  <p>Ask me anything about Risk & Safety at TRU. I will try to provide you with accurate information based on our policy documents.</p>
  <div class="tru-quick-replies">${chips}</div>
</div>`;
  }

  // ── DOM Refs ────────────────────────────────────────────

  function cacheDOMRefs() {
    fab         = document.getElementById('tru-chat-fab');
    chatWindow  = document.getElementById('tru-chat-window');
    messagesEl  = document.getElementById('tru-messages');
    textareaEl  = document.getElementById('tru-input');
    sendBtn     = document.getElementById('tru-send-btn');
    statusDot   = document.getElementById('tru-status-dot');
    statusLabel = document.getElementById('tru-status-label');
    badge       = document.getElementById('tru-fab-badge');
  }

  // ── Events ──────────────────────────────────────────────

  function bindEvents() {
    fab.addEventListener('click', toggleChat);
    document.getElementById('tru-close-btn').addEventListener('click', closeChat);
    document.getElementById('tru-clear-btn').addEventListener('click', clearConversation);
    sendBtn.addEventListener('click', handleSend);

    textareaEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });

    textareaEl.addEventListener('input', () => {
      autoResize(textareaEl);
      sendBtn.disabled = textareaEl.value.trim() === '' || isLoading;
    });

    // Quick reply chips (event delegation)
    messagesEl.addEventListener('click', (e) => {
      const chip = e.target.closest('.tru-quick-reply-chip');
      if (chip) {
        const text = chip.dataset.text;
        if (text) {
          textareaEl.value = text;
          autoResize(textareaEl);
          sendBtn.disabled = false;
          handleSend();
        }
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && isOpen) closeChat();
    });
  }

  // ── Open / Close ────────────────────────────────────────

  function toggleChat() { isOpen ? closeChat() : openChat(); }

  function openChat() {
    isOpen = true;
    fab.classList.add('is-open');
    chatWindow.classList.add('is-open');
    chatWindow.setAttribute('aria-modal', 'true');
    fab.setAttribute('aria-label', 'Close TRU Risk & Safety Assistant');
    clearBadge();
    setTimeout(() => textareaEl.focus(), 320);
  }

  function closeChat() {
    isOpen = false;
    fab.classList.remove('is-open');
    chatWindow.classList.remove('is-open');
    chatWindow.setAttribute('aria-modal', 'false');
    fab.setAttribute('aria-label', 'Open TRU Risk & Safety Assistant');
  }

  // ── Connection Check ────────────────────────────────────

  async function checkConnection() {
    setStatus('connecting', 'Connecting…');
    try {
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), CONFIG.connectMs);
      const res = await fetch(CONFIG.apiHealth, {
        signal: controller.signal,
        headers: { Accept: 'application/json' },
      });
      clearTimeout(tid);
      if (res.ok) {
        const data = await res.json();
        isConnected = true;
        const label = data.ok ? 'Ready · Policy RAG' : 'Connected';
        setStatus('online', label);
        sendBtn.disabled = textareaEl.value.trim() === '';
      } else {
        throw new Error('API error ' + res.status);
      }
    } catch (err) {
      isConnected = false;
      setStatus('offline', 'Offline — start the server');
      sendBtn.disabled = true;
      console.warn('[TRU Policy Chat] Connection failed:', err);
    }
  }

  function setStatus(state, text) {
    statusDot.className = 'tru-status-dot ' + state;
    statusLabel.textContent = text;
  }

  // ── Messaging via SSE stream ────────────────────────────

  async function handleSend() {
    const text = textareaEl.value.trim();
    if (!text || isLoading) return;

    // Remove welcome block on first message
    const welcomeBlock = document.getElementById('tru-welcome-block');
    if (welcomeBlock) welcomeBlock.remove();

    chatHistory.push({ role: 'user', content: text });
    appendUserMessage(text);

    textareaEl.value = '';
    autoResize(textareaEl);
    sendBtn.disabled = true;
    isLoading = true;

    const { msgEl, bubbleEl, sourcesEl } = createAssistantContainer();
    bubbleEl.innerHTML = '<em style="opacity:0.55;font-style:normal">Thinking…</em>';
    scrollToBottom();

    let fullText = '';
    let firstToken = true;

    try {
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), CONFIG.timeoutMs);

      const res = await fetch(CONFIG.apiStream, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          question: text,
          chat_history: chatHistory.slice(-8),
        }),
      });

      clearTimeout(tid);
      if (!res.ok) throw new Error('HTTP ' + res.status);

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer    = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let event;
          try { event = JSON.parse(raw); } catch { continue; }

          if (event.type === 'sources') {
            // Sources display hidden — citations are embedded in the response text
          } else if (event.type === 'token') {
            if (firstToken) {
              bubbleEl.innerHTML = '';
              firstToken = false;
            }
            fullText += event.token;
            console.log('[TRU Chat] Received token:', event.token);
            console.log('[TRU Chat] Full response so far:', fullText);
            bubbleEl.innerHTML = renderMarkdown(fullText);
            // Make all links open in a new tab
            const links = bubbleEl.querySelectorAll('a');
            links.forEach(link => {
              link.setAttribute('target', '_blank');
              link.setAttribute('rel', 'noopener noreferrer');
            });
            scrollToBottom();
          } else if (event.type === 'clear_sources') {
            sourcesEl.innerHTML = '';
            sourcesEl.classList.add('tru-sources--hidden');
          }
          // 'done' event (timing) — ignored for clean UI
        }
      }

      if (firstToken && fullText === '') {
        bubbleEl.innerHTML = renderMarkdown('No response received from the policy documents.');
      }

      chatHistory.push({ role: 'assistant', content: fullText });

      if (!isOpen) {
        unreadCount++;
        badge.textContent = unreadCount > 9 ? '9+' : unreadCount;
        badge.classList.add('visible');
      }
    } catch (err) {
      chatHistory.pop();
      let msg = 'Something went wrong. Please try again.';
      if (err.name === 'AbortError') msg = 'Request timed out. Please try again.';
      else if (err.name === 'TypeError') msg = 'Unable to reach the Policy Assistant. Make sure the server is running.';
      msgEl.remove();
      appendError(msg);
      console.error('[TRU Policy Chat] Error:', err);
    } finally {
      isLoading = false;
      sendBtn.disabled = textareaEl.value.trim() === '';
      textareaEl.focus();
    }
  }

  // ── Message Rendering ─────────────────────────────────

  function appendUserMessage(content) {
    const wrapper = document.createElement('div');
    wrapper.className = 'tru-message user';

    const meta = document.createElement('div');
    meta.className = 'tru-msg-meta';
    meta.textContent = 'You';

    const bubble = document.createElement('div');
    bubble.className = 'tru-msg-bubble';
    bubble.textContent = content;

    wrapper.appendChild(meta);
    wrapper.appendChild(bubble);
    messagesEl.appendChild(wrapper);
    scrollToBottom();
  }

  function createAssistantContainer() {
    const msgEl = document.createElement('div');
    msgEl.className = 'tru-message assistant';

    const meta = document.createElement('div');
    meta.className = 'tru-msg-meta';
    meta.textContent = 'Policy Assistant';

    const bubbleEl = document.createElement('div');
    bubbleEl.className = 'tru-msg-bubble';

    const sourcesEl = document.createElement('div');
    sourcesEl.className = 'tru-sources tru-sources--hidden';

    msgEl.appendChild(meta);
    msgEl.appendChild(bubbleEl);
    msgEl.appendChild(sourcesEl);
    messagesEl.appendChild(msgEl);
    scrollToBottom();

    return { msgEl, bubbleEl, sourcesEl };
  }

  // ── Citations / Sources ───────────────────────────────

  function renderSources(el, sources) {
    if (!sources || !sources.length) return;

    el.classList.remove('tru-sources--hidden');
    el.innerHTML = '';

    const label = document.createElement('div');
    label.className = 'tru-sources-label';
    label.textContent = 'Sources';
    el.appendChild(label);

    const list = document.createElement('div');
    list.className = 'tru-sources-list';

    const seen = new Set();
    for (const s of sources) {
      const key = typeof s === 'string' ? s : (s.policy || s.file || '');
      if (seen.has(key)) continue;
      seen.add(key);

      const chip = document.createElement('div');
      chip.className = 'tru-source-chip';

      const name = document.createElement('span');
      name.className = 'tru-source-chip-name';
      name.textContent = typeof s === 'string' ? s : (s.policy || s.file || 'Document');
      chip.appendChild(name);

      if (s.page) {
        const page = document.createElement('span');
        page.className = 'tru-source-chip-page';
        page.textContent = `p.${s.page}`;
        chip.appendChild(page);
      }

      if (s.relevance != null) {
        const rel = document.createElement('span');
        rel.className = 'tru-source-chip-rel';
        rel.textContent = `${Math.round(s.relevance * 100)}%`;
        chip.appendChild(rel);
      }

      list.appendChild(chip);
    }
    el.appendChild(list);
  }

  function appendError(message) {
    const div = document.createElement('div');
    div.className = 'tru-error-msg';
    div.textContent = '⚠️ ' + message;
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function clearConversation() {
    chatHistory = [];
    messagesEl.innerHTML = buildWelcomeHTML();
    textareaEl.value = '';
    autoResize(textareaEl);
    sendBtn.disabled = true;
  }

  // ── Helpers ────────────────────────────────────────────

  function scrollToBottom() {
    requestAnimationFrame(() => { messagesEl.scrollTop = messagesEl.scrollHeight; });
  }

  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 100) + 'px';
  }

  function clearBadge() {
    unreadCount = 0;
    badge.classList.remove('visible');
    badge.textContent = '';
  }

  function escapeAttr(str) {
    return str.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // ── Boot ──────────────────────────────────────────────

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
