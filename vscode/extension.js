// OmniCore Agent — VS Code Extension
// Chat with OmniCore, refactor code, security scan, generate tests
// All from inside your editor.

const vscode = require('vscode');
const http = require('http');
const https = require('https');

// ── API Client ────────────────────────────────────────────────────────

class OmniCoreClient {
    constructor(baseUrl, apiKey) {
        this.baseUrl = baseUrl || 'http://localhost:8000';
        this.apiKey = apiKey;
    }

    async chat(message, context = '') {
        const fullMessage = context ? `${context}\n\n${message}` : message;
        return this._post('/chat', {
            message: fullMessage,
            temperature: 0.7,
            max_tokens: 4096
        });
    }

    async health() {
        return this._get('/health');
    }

    _post(path, data) {
        return new Promise((resolve, reject) => {
            const url = new URL(path, this.baseUrl);
            const body = JSON.stringify(data);
            const mod = url.protocol === 'https:' ? https : http;

            const req = mod.request({
                hostname: url.hostname,
                port: url.port,
                path: url.pathname,
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(body),
                },
                timeout: 60000,
            }, (res) => {
                let chunks = [];
                res.on('data', c => chunks.push(c));
                res.on('end', () => {
                    try {
                        const json = JSON.parse(Buffer.concat(chunks).toString());
                        resolve(json);
                    } catch (e) {
                        reject(e);
                    }
                });
            });

            req.on('error', reject);
            req.write(body);
            req.end();
        });
    }

    _get(path) {
        return new Promise((resolve, reject) => {
            const url = new URL(path, this.baseUrl);
            const mod = url.protocol === 'https:' ? https : http;

            mod.get(url.toString(), { timeout: 10000 }, (res) => {
                let chunks = [];
                res.on('data', c => chunks.push(c));
                res.on('end', () => {
                    try {
                        resolve(JSON.parse(Buffer.concat(chunks).toString()));
                    } catch (e) {
                        reject(e);
                    }
                });
            }).on('error', reject);
        });
    }
}

// ── Status Bar ────────────────────────────────────────────────────────

let statusBarItem;
let client;

function updateStatus(status, text) {
    if (!statusBarItem) {
        statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
        statusBarItem.command = 'omnicore.chat';
    }
    statusBarItem.text = `$(hubot) OmniCore: ${text}`;
    statusBarItem.tooltip = `OmniCore Agent v3.0 — Status: ${status}`;
    statusBarItem.color = status === 'online' ? '#00ff88' : '#ff4444';
    statusBarItem.show();
}

async function checkHealth() {
    try {
        const health = await client.health();
        updateStatus('online', 'Online');
        return true;
    } catch (e) {
        updateStatus('offline', 'Offline');
        return false;
    }
}

// ── Webview Panel ─────────────────────────────────────────────────────

let chatPanel = undefined;

function createChatPanel(context) {
    if (chatPanel) {
        chatPanel.reveal();
        return;
    }

    chatPanel = vscode.window.createWebviewPanel(
        'omnicoreChat',
        'OmniCore Chat',
        vscode.ViewColumn.Beside,
        { enableScripts: true, retainContextWhenHidden: true }
    );

    chatPanel.webview.html = getChatHtml();

    chatPanel.webview.onDidReceiveMessage(async (message) => {
        switch (message.command) {
            case 'send':
                try {
                    const response = await client.chat(message.text);
                    chatPanel.webview.postMessage({
                        command: 'response',
                        text: response.response || response.content || 'No response',
                        model: response.model
                    });
                } catch (e) {
                    chatPanel.webview.postMessage({
                        command: 'response',
                        text: `Error: ${e.message || 'Connection failed'}`,
                        model: 'error'
                    });
                }
                break;
        }
    });

    chatPanel.onDidDispose(() => { chatPanel = undefined; });
}

function getChatHtml() {
    return `<!DOCTYPE html>
<html>
<head>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { 
            background:#0a0a0a; color:#e0e0e0; font-family:-apple-system,sans-serif;
            display:flex; flex-direction:column; height:100vh; padding:16px;
        }
        #messages { 
            flex:1; overflow-y:auto; margin-bottom:12px;
            display:flex; flex-direction:column; gap:8px;
        }
        .msg { padding:10px 14px; border-radius:8px; max-width:85%; }
        .user { background:#1a1a2e; align-self:flex-end; }
        .assistant { background:#0f3460; align-self:flex-start; }
        .model-tag { font-size:10px; color:#888; margin-top:4px; }
        #input-row { display:flex; gap:8px; }
        #input { 
            flex:1; padding:10px; background:#1a1a1a; color:#e0e0e0;
            border:1px solid #333; border-radius:6px; font-size:14px;
        }
        button { 
            padding:10px 20px; background:#00ff88; color:#000; 
            border:none; border-radius:6px; font-weight:600; cursor:pointer;
        }
        pre { background:#000; padding:8px; border-radius:4px; overflow-x:auto; }
        code { font-family:'Fira Code',monospace; font-size:13px; }
    </style>
</head>
<body>
    <div id="messages">
        <div class="msg assistant">
            OmniCore v3 ready. Ask me anything about your code.
            <div class="model-tag">IDE Agent</div>
        </div>
    </div>
    <div id="input-row">
        <input id="input" placeholder="Ask OmniCore..." autofocus 
               onkeydown="if(event.key==='Enter'&&!event.shiftKey){send();event.preventDefault()}">
        <button onclick="send()">Send</button>
    </div>
    <script>
        const vscode = acquireVsCodeApi();
        const msgs = document.getElementById('messages');
        const input = document.getElementById('input');

        function addMsg(role, text, model) {
            const div = document.createElement('div');
            div.className = 'msg ' + role;
            div.innerHTML = text.replace(/\\n/g,'<br>');
            if(model) div.innerHTML += '<div class="model-tag">' + model + '</div>';
            msgs.appendChild(div);
            msgs.scrollTop = msgs.scrollHeight;
        }

        function send() {
            const text = input.value.trim();
            if(!text) return;
            addMsg('user', text);
            input.value = '';
            vscode.postMessage({command:'send', text});
        }

        window.addEventListener('message', e => {
            if(e.data.command === 'response') {
                addMsg('assistant', e.data.text, e.data.model);
            }
        });
    </script>
</body>
</html>`;
}

// ── Commands ──────────────────────────────────────────────────────────

async function explainCode() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return vscode.window.showWarningMessage('No file open');

    const selection = editor.document.getText(editor.selection) || editor.document.getText();
    const language = editor.document.languageId;

    const response = await client.chat(
        `Explain this ${language} code concisely:\n\n${selection}`,
        'You are a senior code reviewer. Be concise.'
    );
    showResult('Code Explanation', response.response || 'No response');
}

async function refactorCode() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;

    const selection = editor.document.getText(editor.selection) || editor.document.getText();
    const language = editor.document.languageId;

    const response = await client.chat(
        `Refactor this ${language} code:\n\n${selection}\n\nReturn ONLY the refactored code.`,
        'You are a code refactoring expert. Use Blacksmith 6-strike forge.'
    );
    showResult('Refactored Code', response.response || 'No response');
}

async function securityScan() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;

    const code = editor.document.getText();
    const response = await client.chat(
        `Security scan this code. Find vulnerabilities (OWASP Top 10).`,
        `Code:\n\n${code}`
    );
    showResult('Security Scan', response.response || 'No response');
}

async function generateTests() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;

    const code = editor.document.getText();
    const language = editor.document.languageId;

    const response = await client.chat(
        `Generate unit tests for this ${language} code. Cover edge cases.`,
        `Code:\n\n${code}`
    );
    showResult('Generated Tests', response.response || 'No response');
}

async function codeReview() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;

    const code = editor.document.getText();
    const response = await client.chat(
        `Code review: check for bugs, style issues, performance problems, security issues.`,
        `Code:\n\n${code}`
    );
    showResult('Code Review', response.response || 'No response');
}

function showResult(title, text) {
    const doc = vscode.workspace.openTextDocument({ content: text, language: 'markdown' });
    doc.then(d => vscode.window.showTextDocument(d, vscode.ViewColumn.Beside));
}

// ── Activation ────────────────────────────────────────────────────────

function activate(context) {
    const config = vscode.workspace.getConfiguration('omnicore');
    client = new OmniCoreClient(
        config.get('apiUrl', 'http://localhost:8000'),
        config.get('apiKey', '')
    );

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('omnicore.chat', () => createChatPanel(context)),
        vscode.commands.registerCommand('omnicore.explain', explainCode),
        vscode.commands.registerCommand('omnicore.refactor', refactorCode),
        vscode.commands.registerCommand('omnicore.securityScan', securityScan),
        vscode.commands.registerCommand('omnicore.generateTests', generateTests),
        vscode.commands.registerCommand('omnicore.codeReview', codeReview),
    );

    // Status bar
    updateStatus('connecting', 'Connecting...');
    checkHealth();
    setInterval(checkHealth, 30000);

    vscode.window.showInformationMessage('OmniCore Agent v3.0 activated');
}

function deactivate() {
    if (statusBarItem) statusBarItem.dispose();
}

module.exports = { activate, deactivate };