"""Climate Misinformation SNA - local web app.

Run:  python app.py        (the START_* launchers do this for you)
Then the browser opens at http://127.0.0.1:<port>. Keep the console window open.
"""
import logging
import os
import socket
import sys
import threading
import time
import webbrowser

from flask import Flask, jsonify, request, send_from_directory

from sna import config, pipeline

app = Flask(__name__, static_folder=None)
app.json.sort_keys = False   # keep strategy order as requested


def _ready():
    st = pipeline.STATE["status"]
    return st is not None and st["state"] == "ready"


def _need_ready():
    if not _ready():
        return jsonify({"error": "The pipeline is still running - please wait."}), 409
    return None


def _net(body):
    name = (body.get("net") or "cop26").lower()
    if name not in config.NETWORKS:
        raise ValueError("Unknown network")
    return name


@app.errorhandler(Exception)
def _err(e):
    code = getattr(e, "code", 500)
    if not isinstance(code, int):
        code = 500
    return jsonify({"error": f"{type(e).__name__}: {e}"}), code


# ------------------------------------------------------------------ static files
@app.route("/")
def index():
    return send_from_directory(config.WEB_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(config.WEB_DIR, path)


# ------------------------------------------------------------------ API
@app.get("/api/status")
def status():
    st = pipeline.STATE["status"] or {"state": "starting", "stages": [], "message": "Starting..."}
    out = {k: v for k, v in st.items() if k != "trace"}
    out["elapsed"] = round(time.time() - st.get("started", time.time()), 1)
    return jsonify(out)


@app.post("/api/rerun")
def rerun():
    if pipeline.STATE["status"] and pipeline.STATE["status"]["state"] == "running":
        return jsonify({"ok": False, "error": "Already running"}), 409
    threading.Thread(target=pipeline.run_pipeline, kwargs={"force": True}, daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/summary")
def summary():
    bad = _need_ready()
    if bad:
        return bad
    nets = {}
    for name in config.NETWORKS:
        r = pipeline.STATE["results"][name]
        nets[name] = {k: v for k, v in r.items() if k != "layout"}
        nets[name]["label"] = config.NETWORK_LABEL[name]
    return jsonify({
        "meta": pipeline.STATE["meta"],
        "networks": nets,
        "strategies": {k: {"label": a, "description": b} for k, (a, b) in pipeline.STRATEGIES.items()},
        "models": pipeline.detection.MODELS,
        "features": pipeline.detection.FEATURES,
        "source": {"zenodo": config.ZENODO_URL, "paper": config.PAPER_DOI},
        "users_in_both": int(len(set(pipeline.STATE["nets"]["cop26"].posters.tolist()) &
                                 set(pipeline.STATE["nets"]["cop27"].posters.tolist()))),
    })


@app.get("/api/layout/<name>")
def layout(name):
    bad = _need_ready()
    if bad:
        return bad
    payload = pipeline.STATE["results"][name]["layout"]
    # refresh detector scores in case the model was retrained in this session
    prob = pipeline.STATE["derived"][name]["node_prob"]
    g = pipeline.STATE["samples"][name]["global_index"]
    for node, gi in zip(payload["nodes"], g.tolist()):
        node["pred"] = round(float(prob[gi]), 4)
    return jsonify(payload)


@app.post("/api/detect")
def detect():
    bad = _need_ready()
    if bad:
        return bad
    b = request.get_json(force=True) or {}
    res = pipeline.detect(_net(b), model=b.get("model", "boosting"), share=float(b.get("share", 0.2)),
                          min_posts=int(b.get("min_posts", 3)), groups=b.get("groups"))
    return jsonify(res)


def _sim_args(b):
    return dict(budget_pct=min(max(float(b.get("budget_pct", 1)), 0.1), 20),
                n_seeds=min(max(int(b.get("n_seeds", 10)), 1), 100),
                trials=min(max(int(b.get("trials", 200)), 10), 2000),
                strategies=b.get("strategies") or ["random", "degree", "bridge"],
                seed=int(b.get("seed", 0)))


@app.post("/api/simulate")
def simulate():
    bad = _need_ready()
    if bad:
        return bad
    b = request.get_json(force=True) or {}
    p = min(max(float(b.get("p", 0.1)), 0.005), 0.9)
    t = time.time()
    res = pipeline.simulate(_net(b), p=p, **_sim_args(b))
    res["seconds"] = round(time.time() - t, 2)
    return jsonify(res)


@app.post("/api/sweep")
def sweep():
    bad = _need_ready()
    if bad:
        return bad
    b = request.get_json(force=True) or {}
    ps = [min(max(float(p), 0.005), 0.9) for p in (b.get("ps") or [0.05, 0.1, 0.2])][:10]
    t = time.time()
    res = pipeline.sweep(_net(b), ps, **_sim_args(b))
    res["seconds"] = round(time.time() - t, 2)
    return jsonify(res)


@app.post("/api/cascade")
def cascade():
    bad = _need_ready()
    if bad:
        return bad
    b = request.get_json(force=True) or {}
    return jsonify(pipeline.cascade(_net(b), strategy=b.get("strategy", "bridge"),
                                    p=min(max(float(b.get("p", 0.3)), 0.01), 0.95),
                                    budget_pct=min(max(float(b.get("budget_pct", 5)), 0.5), 30),
                                    n_seeds=min(max(int(b.get("n_seeds", 3)), 1), 20),
                                    seed=int(b.get("seed", 1))))


# ------------------------------------------------------------------ startup
def _free_port(preferred=(8765, 8766, 8767, 8780, 8790, 5055)):
    for port in preferred:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    from werkzeug.serving import make_server
    logging.getLogger("werkzeug").setLevel(logging.ERROR)   # keep the console quiet
    port = int(os.environ.get("SNA_PORT") or _free_port())
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=pipeline.run_pipeline, daemon=True).start()
    server = make_server("127.0.0.1", port, app, threaded=True)
    line = "=" * 62
    print(line)
    print("  Climate Misinformation SNA - demo server")
    print(f"  Open in your browser:  {url}")
    print("  Keep this window open while presenting. Close it (or Ctrl+C) to stop.")
    print(line, flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
