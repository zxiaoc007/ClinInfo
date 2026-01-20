// Use relative URL for API - works with same-origin Flask server
// If running on a different port, update this to match your server
const API_URL = '/api';
let sessionId = 'session_' + Date.now();
let currentMode = 'trials'; // 'trials' or 'drugs'

const chatContainer = document.getElementById('chatContainer');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const clearBtn = document.getElementById('clearBtn');
const charCount = document.getElementById('charCount');
const tabTrials = document.getElementById('tabTrials');
const tabDrugs = document.getElementById('tabDrugs');
const welcomeMessageTrials = document.getElementById('welcomeMessageTrials');
const welcomeMessageDrugs = document.getElementById('welcomeMessageDrugs');

// Tab switching
tabTrials.addEventListener('click', () => switchMode('trials'));
tabDrugs.addEventListener('click', () => switchMode('drugs'));

function switchMode(mode) {
    if (mode === currentMode) return;
    
    currentMode = mode;
    
    // Update tab appearance
    if (mode === 'trials') {
        tabTrials.classList.add('active');
        tabDrugs.classList.remove('active');
        messageInput.placeholder = 'Ask about clinical trials...';
        welcomeMessageTrials.style.display = 'block';
        welcomeMessageDrugs.style.display = 'none';
    } else {
        tabTrials.classList.remove('active');
        tabDrugs.classList.add('active');
        messageInput.placeholder = 'Ask about drugs and medications...';
        welcomeMessageTrials.style.display = 'none';
        welcomeMessageDrugs.style.display = 'block';
    }
    
    // Clear chat when switching modes (optional - you might want to keep history)
    // clearChatContainer();
}

// Auto-resize textarea
messageInput.addEventListener('input', () => {
    messageInput.style.height = 'auto';
    messageInput.style.height = messageInput.scrollHeight + 'px';
    
    // Update character count
    const count = messageInput.value.length;
    charCount.textContent = count;
    
    // Enable/disable send button
    sendBtn.disabled = count === 0 || count > 1000;
});

// Send message on Enter (Shift+Enter for new line)
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!sendBtn.disabled) {
            sendMessage();
        }
    }
});

// Send button click
sendBtn.addEventListener('click', sendMessage);

// Clear conversation
clearBtn.addEventListener('click', clearConversation);

// Helper function to attach example button listeners
function attachExampleButtonListeners() {
    document.querySelectorAll('.example-btn').forEach(btn => {
        // Remove existing listeners by cloning
        const newBtn = btn.cloneNode(true);
        btn.parentNode.replaceChild(newBtn, btn);
        
        // Add new listener
        newBtn.addEventListener('click', () => {
            const query = newBtn.getAttribute('data-query');
            messageInput.value = query;
            messageInput.dispatchEvent(new Event('input'));
            sendMessage();
        });
    });
}

// Attach example button listeners on page load
attachExampleButtonListeners();

async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message || message.length > 1000) return;

    // Add user message to chat
    addMessage('user', message);
    
    // Clear input
    messageInput.value = '';
    messageInput.style.height = 'auto';
    charCount.textContent = '0';
    sendBtn.disabled = true;
    
        // Remove welcome messages if present
        const welcomeMsgs = document.querySelectorAll('.welcome-message');
        welcomeMsgs.forEach(msg => {
            if (msg.style.display !== 'none') {
                msg.style.display = 'none';
            }
        });

    // Show loading indicator
    const loadingId = showLoading();

    try {
        const response = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: message,
                session_id: sessionId,
                mode: currentMode
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to get response');
        }

        // Remove loading indicator
        removeLoading(loadingId);

        // Add assistant response
        addMessage('assistant', data.response);

    } catch (error) {
        console.error('Error:', error);
        removeLoading(loadingId);
        addMessage('assistant', `Sorry, I encountered an error: ${error.message}. Please try again.`, true);
    }
}

function addMessage(role, content, isError = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    if (isError) {
        messageDiv.innerHTML = `
            <div class="message-content error-message">
                ${escapeHtml(content)}
            </div>
        `;
    } else {
        // Format the message content
        const formattedContent = formatMessage(content);
        
        messageDiv.innerHTML = `
            <div class="message-content">
                ${formattedContent}
            </div>
        `;
    }
    
    chatContainer.appendChild(messageDiv);
    scrollToBottom();
}

function formatMessage(content) {
    // Escape HTML first
    let formatted = escapeHtml(content);
    
    // Format ClinicalTrials.gov links (Link: https://clinicaltrials.gov/study/NCT...)
    formatted = formatted.replace(/Link:\s*(https?:\/\/clinicaltrials\.gov\/study\/[^\s]+)/g, 
        'Link: <a href="$1" target="_blank" rel="noopener noreferrer" style="color: #2563eb; text-decoration: underline;">$1</a>');
    
    // Format NCT IDs (e.g., NCT12345678) - make them links too
    formatted = formatted.replace(/\b(NCT\d+)\b/g, 
        '<a href="https://clinicaltrials.gov/study/$1" target="_blank" rel="noopener noreferrer" style="color: #2563eb; text-decoration: underline;"><code>$1</code></a>');
    
    // Format numbered lists
    formatted = formatted.replace(/^(\d+\.\s.+)$/gm, '<strong>$1</strong>');
    
    // Format section headers (lines that end with :)
    formatted = formatted.replace(/^(.+):$/gm, '<strong>$1:</strong>');
    
    // Preserve line breaks
    formatted = formatted.replace(/\n/g, '<br>');
    
    return formatted;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showLoading() {
    const loadingId = 'loading-' + Date.now();
    const loadingDiv = document.createElement('div');
    loadingDiv.id = loadingId;
    loadingDiv.className = 'message assistant';
    loadingDiv.innerHTML = `
        <div class="message-content">
            <div class="loading">
                <div class="loading-dot"></div>
                <div class="loading-dot"></div>
                <div class="loading-dot"></div>
            </div>
        </div>
    `;
    chatContainer.appendChild(loadingDiv);
    scrollToBottom();
    return loadingId;
}

function removeLoading(loadingId) {
    const loadingElement = document.getElementById(loadingId);
    if (loadingElement) {
        loadingElement.remove();
    }
}

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

async function clearConversation() {
    if (!confirm('Are you sure you want to clear the conversation?')) {
        return;
    }

    try {
        await fetch(`${API_URL}/clear`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                session_id: sessionId,
                mode: currentMode
            })
        });

        // Clear chat container (but keep welcome messages)
        const messages = chatContainer.querySelectorAll('.message');
        messages.forEach(msg => msg.remove());
        
        // Show appropriate welcome message
        if (currentMode === 'trials') {
            welcomeMessageTrials.style.display = 'block';
            welcomeMessageDrugs.style.display = 'none';
        } else {
            welcomeMessageTrials.style.display = 'none';
            welcomeMessageDrugs.style.display = 'block';
        }

        // Re-attach event listeners to example buttons
        attachExampleButtonListeners();

        // Generate new session ID
        sessionId = 'session_' + Date.now();

    } catch (error) {
        console.error('Error clearing conversation:', error);
        alert('Failed to clear conversation. Please try again.');
    }
}

// Check API health on load
fetch(`${API_URL}/health`)
    .then(response => response.json())
    .then(data => {
        console.log('API is healthy:', data);
    })
    .catch(error => {
        console.error('API health check failed:', error);
        addMessage('assistant', 'Warning: Unable to connect to the API. Please make sure the server is running.', true);
    });

