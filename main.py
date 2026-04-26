
import requests as req, base64, json, time, uuid, os
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

PASSWORD = os.environ.get("BRIDGE_PASSWORD", "colab1234")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
jobs = {}
queue = []
history = []

def github_headers():
    return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

@app.route("/ping")
def ping():
    return jsonify({"status": "ok"})

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
    if request.args.get("pw") != PASSWORD: return jsonify({"error": "unauthorized"}), 403
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

@app.route("/github/update_file", methods=["POST"])
def github_update_file():
    """Claude chiama questo endpoint per modificare file su GitHub"""
    data = request.json or {}
    if data.get("pw") != PASSWORD: return jsonify({"error": "unauthorized"}), 403
    repo = data.get("repo")
    path = data.get("path")
    content = data.get("content")
    message = data.get("message", "update by Claude")
    user = data.get("user")
    if not all([repo, path, content, user]): return jsonify({"error": "missing fields"}), 400
    h = github_headers()
    r = req.get(f"https://api.github.com/repos/{user}/{repo}/contents/{path}", headers=h)
    payload = {"message": message, "content": base64.b64encode(content.encode()).decode()}
    if r.status_code == 200: payload["sha"] = r.json()["sha"]
    r2 = req.put(f"https://api.github.com/repos/{user}/{repo}/contents/{path}", headers=h, json=payload)
    return jsonify({"ok": r2.status_code in [200,201], "status": r2.status_code})

@app.route("/github/get_file", methods=["POST"])
def github_get_file():
    """Claude chiama questo per leggere file da GitHub"""
    data = request.json or {}
    if data.get("pw") != PASSWORD: return jsonify({"error": "unauthorized"}), 403
    h = github_headers()
    r = req.get(f"https://api.github.com/repos/{data['user']}/{data['repo']}/contents/{data['path']}", headers=h)
    if r.status_code == 200:
        content = base64.b64decode(r.json()["content"]).decode()
        return jsonify({"ok": True, "content": content})
    return jsonify({"ok": False}), 404

@app.route("/github/actions_status", methods=["POST"])
def github_actions_status():
    """Claude chiama questo per controllare lo stato della build"""
    data = request.json or {}
    if data.get("pw") != PASSWORD: return jsonify({"error": "unauthorized"}), 403
    h = github_headers()
    r = req.get(f"https://api.github.com/repos/{data['user']}/{data['repo']}/actions/runs", headers=h)
    runs = r.json().get("workflow_runs", [])
    if not runs: return jsonify({"status": "no runs"})
    latest = runs[0]
    return jsonify({"status": latest["status"], "conclusion": latest.get("conclusion"), "run_id": latest["id"], "url": latest["html_url"]})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
