import requests as req, base64, json, time, uuid, os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

PASSWORD = os.environ.get("BRIDGE_PASSWORD", "colab1234")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")
GITHUB_USER = "f4lc088"
GITHUB_REPO = "android-app"

jobs = {}
queue = []
history = []

def gh():
    return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

@app.route("/")
def home():
    return send_from_directory("static", "index.html")

@app.route("/ping")
def ping():
    return jsonify({"status": "ok"})

@app.route("/chat", methods=["POST"])
def chat():
    """Riceve messaggio utente, chiama Claude, esegue azioni GitHub"""
    data = request.json or {}
    if data.get("pw") != PASSWORD:
        return jsonify({"error": "unauthorized"}), 403
    
    user_msg = data.get("message", "")
    history_msgs = data.get("history", [])
    
    system = f"""Sei un assistente Android developer. Hai accesso al repo GitHub {GITHUB_USER}/{GITHUB_REPO}.
Quando l utente ti chiede modifiche all app, usa i tool disponibili per leggere e modificare i file.
Rispondi sempre in italiano. Dopo ogni modifica di file, di all utente cosa hai fatto.

Tool disponibili (chiamali con JSON nel formato {{"tool": "nome", "params": {...}}}):
- read_file: {{"path": "percorso"}} - legge un file dal repo
- write_file: {{"path": "percorso", "content": "contenuto", "message": "commit msg"}} - scrive un file
- list_files: {{"path": ""}} - lista file in una cartella
- build_status: {{}} - controlla stato ultima build
"""

    messages = history_msgs + [{"role": "user", "content": user_msg}]
    
    # Chiama Claude
    r = req.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        json={"model": "claude-haiku-4-5-20251001", "max_tokens": 2000, "system": system, "messages": messages}
    )
    
    if r.status_code != 200:
        return jsonify({"error": "Claude API error", "detail": r.text}), 500
    
    reply = r.json()["content"][0]["text"]
    
    # Esegui tool calls se presenti
    tool_results = []
    import re
    tool_calls = re.findall(r'\{\s*"tool":\s*"([^"]+)"[^}]*"params":\s*(\{[^}]*\})\s*\}', reply)
    
    for tool_name, params_str in tool_calls:
        try:
            params = json.loads(params_str)
            result = execute_tool(tool_name, params)
            tool_results.append({"tool": tool_name, "result": result})
        except Exception as e:
            tool_results.append({"tool": tool_name, "error": str(e)})
    
    return jsonify({"reply": reply, "tool_results": tool_results})

def execute_tool(name, params):
    if name == "read_file":
        r = req.get(f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{params['path']}", headers=gh())
        if r.status_code == 200:
            return base64.b64decode(r.json()["content"]).decode()
        return f"Errore: {r.status_code}"
    
    elif name == "write_file":
        path = params["path"]
        content = params["content"]
        message = params.get("message", "update by Claude")
        r = req.get(f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{path}", headers=gh())
        payload = {"message": message, "content": base64.b64encode(content.encode()).decode()}
        if r.status_code == 200:
            payload["sha"] = r.json()["sha"]
        r2 = req.put(f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{path}", headers=gh(), json=payload)
        return "OK" if r2.status_code in [200,201] else f"Errore: {r2.status_code}"
    
    elif name == "list_files":
        path = params.get("path", "")
        r = req.get(f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{path}", headers=gh())
        if r.status_code == 200:
            return [f["name"] for f in r.json()]
        return []
    
    elif name == "build_status":
        r = req.get(f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/actions/runs", headers=gh())
        runs = r.json().get("workflow_runs", [])
        if not runs: return "Nessuna build"
        latest = runs[0]
        return {"status": latest["status"], "conclusion": latest.get("conclusion"), "url": latest["html_url"]}
    
    return "Tool non trovato"

# ── Job queue (per Colab) ──
@app.route("/submit", methods=["POST"])
def submit():
    data = request.json or {}
    if data.get("pw") != PASSWORD: return jsonify({"error": "unauthorized"}), 403
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"code": data.get("code",""), "label": data.get("label",""), "status": "pending", "output": "", "error": False, "ts": time.time()}
    queue.append(job_id)
    return jsonify({"job_id": job_id})

@app.route("/next_job")
def next_job():
    if request.args.get("pw") != PASSWORD: return jsonify({"job": None})
    if not queue: return jsonify({"job": None})
    job_id = queue[0]
    job = jobs.get(job_id)
    if not job: queue.pop(0); return jsonify({"job": None})
    return jsonify({"job": {"id": job_id, "code": job["code"], "label": job["label"]}})

@app.route("/complete/<job_id>", methods=["POST"])
def complete(job_id):
    data = request.json or {}
    if data.get("pw") != PASSWORD: return jsonify({"error": "unauthorized"}), 403
    if job_id not in jobs: return jsonify({"error": "not found"}), 404
    jobs[job_id].update({"status": "done", "output": data.get("output",""), "error": data.get("error", False)})
    if job_id in queue: queue.remove(job_id)
    history.insert(0, {**jobs[job_id], "id": job_id})
    return jsonify({"ok": True})

@app.route("/result/<job_id>")
def result(job_id):
    job = jobs.get(job_id)
    if not job: return jsonify({"status": "not_found"}), 404
    return jsonify(job)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
