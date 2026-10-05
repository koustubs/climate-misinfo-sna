"""Runs every stage in order, reports progress to the web UI and caches the results.

First launch: about a minute (depends on the laptop). Later launches load from cache/.
"""
import json
import threading
import time
import traceback

import networkx as nx
import numpy as np

from . import centrality, communities, config, detection, graph, ingest, layout, simulation

STAGES = [
    ("ingest", "Load & verify dataset", "Stream the Zenodo CSV, check its MD5, encode account IDs"),
    ("graph", "Build retweet networks", "Directed author → retweeter graphs for COP26 and COP27"),
    ("community", "Detect communities", "Louvain modularity optimisation, compared with Infomap"),
    ("centrality", "Compute centrality", "Degree, sampled Brandes betweenness, PageRank, k-core"),
    ("detection", "Train spreader detector", "Gradient boosting on behaviour + structure + homophily"),
    ("simulation", "Run fact-check experiment", "Independent Cascade, 200 paired trials × 3 spread rates"),
    ("layout", "Prepare network view", "Sample the community cores and compute a force layout"),
]

# Values printed on the presentation slides (reduction in mean reach, %)
SLIDE_VALUES = {
    "cop26": {0.05: {"random": 2.27, "degree": 53.54, "bridge": 55.09},
              0.1: {"random": 3.85, "degree": 53.91, "bridge": 58.80},
              0.2: {"random": 2.07, "degree": 40.23, "bridge": 47.28}},
    "cop27": {0.05: {"random": 2.85, "degree": 36.04, "bridge": 5.82},
              0.1: {"random": 1.83, "degree": 41.70, "bridge": 29.62},
              0.2: {"random": 4.08, "degree": 60.03, "bridge": 63.21}},
}

STRATEGIES = {
    "random": ("Random", "Uniformly random accounts (control)"),
    "degree": ("Degree", "Most distinct retweeters (biggest amplifiers)"),
    "bridge": ("Bridge", "Highest betweenness (on most shortest paths)"),
    "pagerank": ("PageRank", "Retweeted by influential accounts"),
    "detector": ("Detector", "Highest predicted spreader probability"),
    "detector_reach": ("Detector × reach", "Spreader probability × number of retweeters"),
}

STATE = {"status": None, "nets": {}, "derived": {}, "results": {}, "samples": {}, "engines": {},
         "sub_engines": {}, "meta": None}
LOCK = threading.Lock()


def _new_status():
    return {"state": "running", "current": None, "message": "Starting...", "progress": 0.0,
            "error": None, "from_cache": False, "started": time.time(), "total_seconds": None,
            "stages": [{"key": k, "label": l, "detail": d, "status": "pending", "seconds": None}
                       for k, l, d in STAGES]}


def _stage(key):
    return next(s for s in STATE["status"]["stages"] if s["key"] == key)


class _Timer:
    def __init__(self, key, cached=False):
        self.key, self.cached = key, cached

    def __enter__(self):
        st = STATE["status"]
        st["current"] = self.key
        st["progress"] = 0.0
        _stage(self.key)["status"] = "running"
        self.t = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        s = _stage(self.key)
        s["seconds"] = round(time.time() - self.t, 2)
        s["status"] = "error" if exc_type else ("cached" if self.cached else "done")
        return False


def _msg(text, frac=None):
    STATE["status"]["message"] = text
    if frac is not None:
        STATE["status"]["progress"] = float(frac)


# ----------------------------------------------------------------- cache helpers
def _cache_paths():
    c = config.CACHE_DIR
    return c / "dataset.npz", c / "results.json", {n: c / f"{n}_derived.npz" for n in config.NETWORKS}


def _load_cache():
    ds, res, der = _cache_paths()
    if not (ds.exists() and res.exists() and all(p.exists() for p in der.values())):
        return None
    try:
        results = json.loads(res.read_text())
        if results.get("version") != config.CACHE_VERSION:
            return None
        z = np.load(ds, allow_pickle=False)
        data = {k: z[k] for k in z.files}
        derived = {}
        for n, p in der.items():
            zz = np.load(p, allow_pickle=False)
            derived[n] = {k: zz[k] for k in zz.files}
        return data, results, derived
    except Exception:
        return None


def _save_cache(data, meta):
    ds, res, der = _cache_paths()
    config.CACHE_DIR.mkdir(exist_ok=True)
    np.savez_compressed(ds, **data)
    out = {"version": config.CACHE_VERSION, "meta": meta, "results": STATE["results"]}
    res.write_text(json.dumps(out))
    for n, p in der.items():
        d = dict(STATE["derived"][n])
        smp = STATE["samples"][n]
        for k in ["global_index", "xy", "src", "dst", "sub_betweenness", "sub_pagerank", "comm"]:
            d["sample_" + k] = smp[k]
        np.savez_compressed(p, **d)


# ----------------------------------------------------------------- stages
def run_pipeline(force=False):
    with LOCK:
        STATE["status"] = _new_status()
        try:
            _run(force)
            STATE["status"]["state"] = "ready"
            STATE["status"]["current"] = None
            STATE["status"]["message"] = "Ready"
            STATE["status"]["progress"] = 1.0
        except Exception as e:  # shown in the UI
            STATE["status"]["state"] = "error"
            STATE["status"]["error"] = f"{type(e).__name__}: {e}"
            STATE["status"]["trace"] = traceback.format_exc()
        STATE["status"]["total_seconds"] = round(time.time() - STATE["status"]["started"], 1)


def _run(force):
    cached = None if force else _load_cache()
    STATE["status"]["from_cache"] = cached is not None

    # 1 ingest
    with _Timer("ingest", cached is not None):
        if cached:
            data, saved, derived_cache = cached
            meta = saved["meta"]
            _msg("Loaded dataset from cache", 1)
        else:
            data, meta = ingest.ingest(progress=_msg)
            if not meta["md5_ok"]:
                _msg("Warning: MD5 does not match Zenodo - file may be modified")
        STATE["meta"] = meta

    # 2 graphs
    with _Timer("graph"):
        for j, name in enumerate(config.NETWORKS):
            _msg(f"Building {name.upper()} retweet network", j / 2)
            net = graph.build_network(data, meta["subset_names"].index(name), name)
            net.ids = data["ids"]
            STATE["nets"][name] = net
            STATE["engines"][name] = simulation.CascadeEngine(net.n, net.src, net.dst)

    if cached:
        for k in ["community", "centrality", "detection", "simulation", "layout"]:
            with _Timer(k, True):
                pass
        STATE["results"] = saved["results"]
        for name in config.NETWORKS:
            d = derived_cache[name]
            STATE["derived"][name] = {k: d[k] for k in ["louvain", "betweenness", "pagerank", "kcore", "node_prob"]}
            smp = {k[7:]: d[k] for k in d if k.startswith("sample_")}
            smp["sub"] = layout.SubNet(len(smp["global_index"]), smp["src"], smp["dst"])
            STATE["samples"][name] = smp
            STATE["sub_engines"][name] = simulation.CascadeEngine(smp["sub"].n, smp["src"], smp["dst"])
        return

    # 3 communities
    graphs_u = {}
    with _Timer("community"):
        for j, name in enumerate(config.NETWORKS):
            _msg(f"Louvain on {name.upper()} ({STATE['nets'][name].n:,} accounts)...", j / 2)
            net = STATE["nets"][name]
            labels, Q, G = communities.louvain(net)
            graphs_u[name] = G
            STATE["derived"][name] = {"louvain": labels}
            STATE["results"][name] = {"stats": net.stats, "communities": communities.summarise(net, labels, Q)}

    # 4 centrality
    with _Timer("centrality"):
        for j, name in enumerate(config.NETWORKS):
            net = STATE["nets"][name]
            adj = centrality.adjacency(net)
            _msg(f"Betweenness on {name.upper()} (Brandes, {config.BETWEENNESS_SAMPLES} sampled sources)", j / 2)
            bc = centrality.brandes_sampled(
                adj, config.BETWEENNESS_SAMPLES, config.BASE_SEED + j,
                progress=lambda f, j=j: STATE["status"].__setitem__("progress", (j + f) / 2))
            pr = centrality.pagerank(net)
            G = graphs_u[name]
            G.remove_edges_from(nx.selfloop_edges(G))
            core = nx.core_number(G)
            kcore = np.array([core[i] for i in range(net.n)])
            STATE["derived"][name].update({"betweenness": bc, "pagerank": pr, "kcore": kcore})

    # 5 detection
    with _Timer("detection"):
        for j, name in enumerate(config.NETWORKS):
            _msg(f"Training detector for {name.upper()} (3 feature sets + permutation importance)", j / 2)
            net = STATE["nets"][name]
            res, node_prob = detection.run_detection(net, STATE["derived"][name])
            STATE["derived"][name]["node_prob"] = node_prob
            STATE["results"][name]["detection"] = res
            STATE["results"][name]["top_accounts"] = top_accounts(name)

    # 6 simulation - reproduce the presentation
    with _Timer("simulation"):
        for j, name in enumerate(config.NETWORKS):
            rep = []
            for i, p in enumerate([0.05, 0.1, 0.2]):
                _msg(f"{name.upper()}: 200 paired trials at p = {int(p * 100)}%", (j * 3 + i) / 6)
                r = simulate(name, p=p, budget_pct=1, n_seeds=10, trials=200,
                             strategies=["random", "degree", "bridge"], seed=0)
                r["slide"] = SLIDE_VALUES[name][p]
                rep.append(r)
            STATE["results"][name]["reproduction"] = rep

    # 7 layout
    with _Timer("layout"):
        for j, name in enumerate(config.NETWORKS):
            _msg(f"Force-directed layout for {name.upper()} sample", j / 2)
            net = STATE["nets"][name]
            smp = layout.build_sample(net, STATE["derived"][name])
            STATE["samples"][name] = smp
            STATE["sub_engines"][name] = simulation.CascadeEngine(smp["sub"].n, smp["src"], smp["dst"])
            STATE["results"][name]["layout"] = layout.sample_payload(
                net, STATE["derived"][name], smp, STATE["derived"][name]["node_prob"])

    _msg("Saving cache for instant start next time", 1)
    _save_cache(data, meta)


# ----------------------------------------------------------------- services used by the API
def top_accounts(name, k=10):
    net, d = STATE["nets"][name], STATE["derived"][name]
    out = {}
    for key, scores in [("degree", net.outdeg), ("bridge", d["betweenness"]), ("pagerank", d["pagerank"])]:
        rows = []
        for i in centrality.top_k(scores, k):
            rows.append({"id": str(net.ids[net.node_codes[i]]), "outdeg": int(net.outdeg[i]),
                         "indeg": int(net.indeg[i]), "btw": float(d["betweenness"][i]),
                         "pr": float(d["pagerank"][i] * net.n), "louvain": int(d["louvain"][i]),
                         "flag": float(net.flag_share_node[i]),
                         "pred": float(d["node_prob"][i]) if "node_prob" in d else None})
        out[key] = rows
    return out


def target_set(name, strategy, budget):
    net, d = STATE["nets"][name], STATE["derived"][name]
    if strategy == "degree":
        return centrality.top_k(net.outdeg, budget)
    if strategy == "bridge":
        return centrality.top_k(d["betweenness"], budget)
    if strategy == "pagerank":
        return centrality.top_k(d["pagerank"], budget)
    if strategy == "detector":
        return centrality.top_k(d["node_prob"], budget)
    if strategy == "detector_reach":
        return centrality.top_k(d["node_prob"] * net.outdeg, budget)
    raise ValueError(strategy)


def simulate(name, p=0.1, budget_pct=1.0, n_seeds=10, trials=200, strategies=None, seed=0, progress=None):
    strategies = [s for s in (strategies or ["random", "degree", "bridge"]) if s in STRATEGIES]
    net = STATE["nets"][name]
    j = config.NETWORKS.index(name)
    budget = simulation.budget_size(net.n, budget_pct)
    targets = {s: target_set(name, s, budget) for s in strategies if s != "random"}
    runs = simulation.run_trials(STATE["engines"][name], net.seed_pool, targets, p, budget,
                                 int(n_seeds), int(trials), simulation.trial_rng(j, p, int(seed)), progress)
    summ = simulation.summarise(runs)
    if "random" not in strategies:
        summ["strategies"].pop("random", None)
    for s, v in summ["strategies"].items():
        q = np.percentile(runs[s], [10, 25, 50, 75, 90])
        v["quantiles"] = [float(x) for x in q]
    summ["baseline_quantiles"] = [float(x) for x in np.percentile(runs["baseline"], [10, 25, 50, 75, 90])]
    ranked = sorted(summ["strategies"], key=lambda s: -summ["strategies"][s]["reduction"])
    if len(ranked) >= 2:
        summ["best_vs_second"] = {"best": ranked[0], "second": ranked[1],
                                  **simulation.paired_difference(runs, ranked[0], ranked[1])}
    overlaps = {}
    keys = list(targets)
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            overlaps[f"{keys[a]}|{keys[b]}"] = int(len(set(targets[keys[a]].tolist()) & set(targets[keys[b]].tolist())))
    summ.update({"network": name, "p": p, "budget_pct": budget_pct, "budget": budget, "n_seeds": int(n_seeds),
                 "graph_nodes": net.n, "seed": int(seed), "overlaps": overlaps})
    return summ


def sweep(name, ps, **kw):
    return {"network": name, "points": [simulate(name, p=float(p), **kw) for p in ps]}


def cascade(name, strategy="degree", p=0.3, budget_pct=5.0, n_seeds=3, seed=1):
    smp = STATE["samples"][name]
    sub = smp["sub"]
    eng = STATE["sub_engines"][name]
    net, d = STATE["nets"][name], STATE["derived"][name]
    g = smp["global_index"]
    rng = np.random.default_rng(int(seed))
    seedable = np.where((net.flag_share_node[g] > 0) & (sub.outdeg > 0))[0]
    seeds = rng.choice(seedable, min(int(n_seeds), len(seedable)), replace=False)
    live = rng.random(eng.E) < p
    budget = simulation.budget_size(sub.n, budget_pct)
    if strategy == "degree":
        tgt = centrality.top_k(sub.outdeg, budget)
    elif strategy == "bridge":
        tgt = centrality.top_k(smp["sub_betweenness"], budget)
    elif strategy == "pagerank":
        tgt = centrality.top_k(smp["sub_pagerank"], budget)
    elif strategy == "detector":
        tgt = centrality.top_k(d["node_prob"][g], budget)
    elif strategy == "detector_reach":
        tgt = centrality.top_k(d["node_prob"][g] * sub.outdeg, budget)
    else:
        tgt = rng.choice(sub.n, budget, replace=False)
    indptr, nbr = eng.live_graph(live)
    blocked = np.zeros(sub.n, dtype=bool)
    blocked[tgt] = True
    base = eng.spread(indptr, nbr, seeds, np.zeros(sub.n, dtype=bool), trace=True)
    inter = eng.spread(indptr, nbr, seeds, blocked, trace=True)
    return {"seeds": seeds.tolist(), "targets": np.asarray(tgt).tolist(), "budget": budget,
            "baseline": base, "intervention": inter, "n": sub.n,
            "reach_baseline": int(sum(len(w) for w in base)),
            "reach_intervention": int(sum(len(w) for w in inter)),
            "live_edges": np.where(live)[0].tolist()}


def detect(name, model="boosting", share=0.2, min_posts=3, groups=None):
    net = STATE["nets"][name]
    res, node_prob = detection.run_detection(net, STATE["derived"][name], model=model, share=float(share),
                                             min_posts=int(min_posts),
                                             groups=groups or ["behaviour", "structure", "homophily"])
    STATE["derived"][name]["node_prob"] = node_prob   # the Detector strategy now uses this model
    return res
