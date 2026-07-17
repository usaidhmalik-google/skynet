let activeMessageDiv = null;
let eventSource = null;

window.addEventListener('DOMContentLoaded', () => {
    loadCode();
});

async function loadCode() {
    const codeDisplay = document.getElementById('code-display');
    try {
        const response = await fetch('/code');
        const data = await response.json();
        codeDisplay.textContent = data.code;
        
        // If there's an actual agent generated, enable chat
        if (data.code && !data.code.includes("# No agent generated yet.")) {
            enableChat();
            addSystemMessage("Agent loaded successfully. You can now chat with it!");
        }
    } catch (e) {
        codeDisplay.textContent = "# Failed to load code: " + e;
    }
}

async function buildAgent() {
    const promptInput = document.getElementById('prompt-input');
    const buildBtn = document.getElementById('build-btn');
    const prompt = promptInput.value.trim();
    
    if (!prompt) {
        alert("Please describe the agent you want to build!");
        return;
    }

    buildBtn.disabled = true;
    buildBtn.textContent = "Generating Agent...";
    addSystemMessage("Generating agent. This uses the ADK Builder agent to write generated_agent.py on disk...");

    try {
        const response = await fetch('/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            document.getElementById('code-display').textContent = data.code;
            enableChat();
            resetChat();
            addSystemMessage("Agent built successfully! Pointed to generated_agent.py. You can start chatting with your prototype agent in the right pane.");
        } else {
            alert("Error: " + (data.error || "Failed to generate agent"));
            addSystemMessage("Error occurred during generation: " + (data.error || "Unknown error"));
        }
    } catch (e) {
        alert("Request failed: " + e);
        addSystemMessage("Request failed: " + e);
    } finally {
        buildBtn.disabled = false;
        buildBtn.textContent = "Build Agent Prototype";
    }
}

function enableChat() {
    document.getElementById('chat-input').disabled = false;
    document.getElementById('send-btn').disabled = false;
}

function resetChat() {
    const container = document.getElementById('chat-messages');
    container.innerHTML = `
        <div class="message system">
            <div class="text">Chat session restarted. Send a message to your prototype agent!</div>
        </div>
    `;
    if (eventSource) {
        eventSource.close();
    }
}

function addSystemMessage(text) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message system';
    div.innerHTML = `<div class="text">${text}</div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function sendMessage() {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const message = input.value.trim();

    if (!message) return;

    // Clear input and disable chat input during generation
    input.value = "";
    input.disabled = true;
    sendBtn.disabled = true;

    const container = document.getElementById('chat-messages');

    // Add user message
    const userDiv = document.createElement('div');
    userDiv.className = 'message user';
    userDiv.innerHTML = `
        <div class="author">You</div>
        <div class="text">${message}</div>
    `;
    container.appendChild(userDiv);
    container.scrollTop = container.scrollHeight;

    // Create container for agent message
    activeMessageDiv = document.createElement('div');
    activeMessageDiv.className = 'message agent';
    activeMessageDiv.innerHTML = `
        <div class="author">Agent</div>
        <div class="text"></div>
    `;
    container.appendChild(activeMessageDiv);
    container.scrollTop = container.scrollHeight;

    const textSpan = activeMessageDiv.querySelector('.text');

    // Open EventSource connection for streaming
    const url = `/chat/stream?message=${encodeURIComponent(message)}`;
    eventSource = new EventSource(url);

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.error) {
            textSpan.textContent += "\n[Error: " + data.error + "]";
            eventSource.close();
            enableChat();
            return;
        }

        // Print text chunk
        if (data.text) {
            textSpan.textContent += data.text;
        }

        // Handle tool/function calls
        if (data.func_calls && data.func_calls.length > 0) {
            data.func_calls.forEach(call => {
                const chip = document.createElement('div');
                chip.className = 'tool-chip';
                chip.innerHTML = `
                    <span>⚙️ Running Tool: ${call.name}</span>
                    <span class="tool-chip-args">${JSON.stringify(call.args)}</span>
                `;
                container.insertBefore(chip, activeMessageDiv);
            });
        }

        container.scrollTop = container.scrollHeight;

        // If turn is complete or not partial, close stream and re-enable inputs
        if (data.partial === false) {
            eventSource.close();
            enableChat();
        }
    };

    eventSource.onerror = (e) => {
        console.error("EventSource failed:", e);
        eventSource.close();
        enableChat();
    };
}
