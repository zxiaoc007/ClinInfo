const API_URL   = '/api';
let   sessionId = 'session_' + Date.now();
const currentMode = 'orchestrated';

const chatContainer = document.getElementById('chatContainer');
const messageInput  = document.getElementById('messageInput');
const sendBtn       = document.getElementById('sendBtn');
const clearBtn      = document.getElementById('clearBtn');
const charCount     = document.getElementById('charCount');
const welcomeMsg    = document.getElementById('welcomeMessage');
const logo          = document.querySelector('.logo');

// ── Textarea auto-resize & char count ───────────────────────
messageInput.addEventListener('input', () => {
    messageInput.style.height = 'auto';
    messageInput.style.height = messageInput.scrollHeight + 'px';
    const n = messageInput.value.length;
    charCount.textContent = n;
    sendBtn.disabled = n === 0 || n > 1000;
});

// ── Keyboard shortcuts ───────────────────────────────────────
messageInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!sendBtn.disabled) sendMessage();
    }
});

sendBtn.addEventListener('click', sendMessage);
clearBtn.addEventListener('click', clearConversation);
logo.addEventListener('click', goHome);

// ── Example buttons ──────────────────────────────────────────
function attachExampleButtonListeners() {
    document.querySelectorAll('.example-btn').forEach(btn => {
        const fresh = btn.cloneNode(true);
        btn.replaceWith(fresh);
        fresh.addEventListener('click', () => {
            messageInput.value = fresh.dataset.query;
            messageInput.dispatchEvent(new Event('input'));
            sendMessage();
        });
    });
}
attachExampleButtonListeners();

// ── Send message ─────────────────────────────────────────────
async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message || message.length > 1000) return;

    addMessage('user', message);

    messageInput.value = '';
    messageInput.style.height = 'auto';
    charCount.textContent = '0';
    sendBtn.disabled = true;

    if (welcomeMsg) welcomeMsg.style.display = 'none';

    const loadingId = showLoading();

    try {
        const res  = await fetch(`${API_URL}/chat`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ message, session_id: sessionId, mode: currentMode }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Server error');
        removeLoading(loadingId);
        addMessage('assistant', data.response);
    } catch (err) {
        console.error(err);
        removeLoading(loadingId);
        addMessage('assistant', `Sorry, I encountered an error: ${err.message}. Please try again.`, true);
    }
}

// ── Add message bubble ───────────────────────────────────────
function addMessage(role, content, isError = false) {
    const wrap = document.createElement('div');
    wrap.className = `message ${role}`;

    const inner = document.createElement('div');
    inner.className = 'message-content' + (isError ? ' error-message' : '');
    inner.innerHTML  = isError ? escapeHtml(content) : formatMessage(content);

    wrap.appendChild(inner);
    chatContainer.appendChild(wrap);
    scrollToBottom();
}

// ── Markdown-aware formatter ─────────────────────────────────
function formatMessage(raw) {
    const lines  = raw.split('\n');
    const output = [];
    let inList   = false;

    for (let i = 0; i < lines.length; i++) {
        let line = lines[i];

        if (/^## (.+)/.test(line)) {
            if (inList) { output.push('</ul>'); inList = false; }
            output.push(`<h2>${inlineFormat(line.replace(/^## /, ''))}</h2>`);
            continue;
        }
        if (/^### (.+)/.test(line)) {
            if (inList) { output.push('</ul>'); inList = false; }
            output.push(`<h3>${inlineFormat(line.replace(/^### /, ''))}</h3>`);
            continue;
        }
        if (/^---+$/.test(line.trim())) {
            if (inList) { output.push('</ul>'); inList = false; }
            output.push('<hr>');
            continue;
        }
        if (/^[-*•]\s+/.test(line)) {
            if (!inList) { output.push('<ul>'); inList = true; }
            output.push(`<li>${inlineFormat(line.replace(/^[-*•]\s+/, ''))}</li>`);
            continue;
        }
        if (/^\d+\.\s+/.test(line)) {
            if (inList) { output.push('</ul>'); inList = false; }
            output.push(`<p><strong>${inlineFormat(line)}</strong></p>`);
            continue;
        }
        if (line.trim() === '') {
            if (inList) { output.push('</ul>'); inList = false; }
            output.push('<p></p>');
            continue;
        }
        if (inList) { output.push('</ul>'); inList = false; }
        output.push(`<p>${inlineFormat(line)}</p>`);
    }

    if (inList) output.push('</ul>');
    return output.join('');
}

function inlineFormat(text) {
    text = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.+?)\*/g,     '<em>$1</em>');
    text = text.replace(/`([^`]+)`/g,     '<code>$1</code>');

    text = text.replace(
        /Link:\s*(https?:\/\/clinicaltrials\.gov\/study\/([^\s]+))/g,
        'Link: <a class="nct-link" href="$1" target="_blank" rel="noopener">$2 ↗</a>'
    );
    text = text.replace(
        /\b(NCT\d{6,8})\b(?![^<]*<\/a>)/g,
        '<a class="nct-link" href="https://clinicaltrials.gov/study/$1" target="_blank" rel="noopener">$1 ↗</a>'
    );
    text = text.replace(
        /(?<!href=["'])(https?:\/\/[^\s<]+)/g,
        '<a href="$1" target="_blank" rel="noopener">$1</a>'
    );

    return text;
}

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}

// ── Loading indicator ────────────────────────────────────────
function showLoading() {
    const id  = 'loading-' + Date.now();
    const div = document.createElement('div');
    div.id        = id;
    div.className = 'message assistant';
    div.innerHTML = `<div class="message-content">
        <div class="loading">
            <div class="loading-dot"></div>
            <div class="loading-dot"></div>
            <div class="loading-dot"></div>
        </div>
    </div>`;
    chatContainer.appendChild(div);
    scrollToBottom();
    return id;
}

function removeLoading(id) {
    document.getElementById(id)?.remove();
}

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

// ── Go home (logo click) ─────────────────────────────────────
async function goHome() {
    if (!chatContainer.querySelector('.message')) return; // already on home
    try {
        await fetch(`${API_URL}/clear`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ session_id: sessionId, mode: currentMode }),
        });
    } catch (e) { /* best-effort */ }

    chatContainer.querySelectorAll('.message').forEach(m => m.remove());
    if (welcomeMsg) welcomeMsg.style.display = 'block';
    attachExampleButtonListeners();
    sessionId = 'session_' + Date.now();
}

// ── Clear conversation ───────────────────────────────────────
async function clearConversation() {
    if (!confirm('Are you sure you want to clear the conversation?')) return;

    try {
        await fetch(`${API_URL}/clear`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ session_id: sessionId, mode: currentMode }),
        });
    } catch (e) { /* best-effort */ }

    chatContainer.querySelectorAll('.message').forEach(m => m.remove());
    if (welcomeMsg) welcomeMsg.style.display = 'block';
    attachExampleButtonListeners();
    sessionId = 'session_' + Date.now();
}

// ── Health check ─────────────────────────────────────────────
fetch(`${API_URL}/health`)
    .then(r => r.json())
    .then(() => console.log('API is healthy'))
    .catch(() => addMessage('assistant', 'Warning: Unable to connect to the API. Please make sure the server is running.', true));
