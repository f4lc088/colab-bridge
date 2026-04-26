from flask import Flask, request, jsonify
from flask_cors import CORS
import sys, io, traceback, json, threading, time, uuid, os

app = Flask(__name__)
CORS(app)

PASSWORD = os.environ.get("BRIDGE_PASSWORD", "colab1234")
jobs = {}
queue = []
history = []

@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "time": time.time()})

@app.route("/submit", methods=["POST"])
def submit():
    data = request.json or {}
    if data.get("pw") != PASSWORD:
        return jsonify({"error": "unauthorized"}), 403
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"code": data.get("code",""), "label": data.get("label",""), "status": "pending", "output": "", "error": False, "ts": time.time()}
    queue.append(job_id)
    return jsonify({"job_id": job_id})

@app.route("/next_job")
def next_job():
    if request.args.get("pw") != PASSWORD:
        return jsonify({"error": "unauthorized"}), 403
    for jid in list(jobs.keys()):
        if time.time() - jobs[jid]["ts"] > 3600:
            jobs.pop(jid, None)
            if jid in queue: queue.remove(jid)
    if not queue:
        return jsonify({"job": None})
    job_id = queue[0]
    job = jobs.get(job_id)
    if not job:
        queue.pop(0)
        return jsonify({"job": None})
    return jsonify({"job": {"id": job_id, "code": job["code"], "label": job["label"]}})

@app.route("/complete/<job_id>", methods=["POST"])
def complete(job_id):
    data = request.json or {}
    if data.get("pw") != PASSWORD:
        return jsonify({"error": "unauthorized"}), 403
    if job_id not in jobs:
        return jsonify({"error": "not found"}), 404
    jobs[job_id].update({"status": "done", "output": data.get("output",""), "error": data.get("error", False)})
    if job_id in queue: queue.remove(job_id)
    history.insert(0, {**jobs[job_id], "id": job_id})
    if len(history) > 100: history.pop()
    return jsonify({"ok": True})

@app.route("/result/<job_id>")
def result(job_id):
    job = jobs.get(job_id)
    if not job: return jsonify({"status": "not_found"}), 404
    return jsonify(job)

@app.route("/history")
def get_history():
    if request.args.get("pw") != PASSWORD: return jsonify([])
    return jsonify(history[:20])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
