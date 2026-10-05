"""Stage 7 - A readable sample of the network for the browser.

13,640 nodes and 183k edges cannot be drawn legibly, so we draw the core of the
largest Louvain communities (their most connected accounts) and lay it out with a
force-directed algorithm (Fruchterman-Reingold), seeding each community in its
own region so groups stay visually separate. The cascade playground runs on this
same sampled graph.
"""
import math

import networkx as nx
import numpy as np

from .centrality import brandes_exact, pagerank


class SubNet:
    """Minimal network-like object so the cascade engine and PageRank can run on the sample."""

    def __init__(self, n, src, dst):
        self.n, self.src, self.dst = n, src, dst
        self.outdeg = np.bincount(src, minlength=n)
        self.indeg = np.bincount(dst, minlength=n)


def build_sample(net, derived, target_nodes=650, n_comms=8, seed=7):
    lab = derived["louvain"]
    sizes = np.bincount(lab)
    comms = list(range(min(n_comms, len(sizes))))
    weights = np.sqrt(sizes[comms].astype(float))
    quota = np.maximum(20, np.round(target_nodes * weights / weights.sum())).astype(int)
    deg = net.outdeg + net.indeg
    chosen = []
    for c, q in zip(comms, quota):
        members = np.where(lab == c)[0]
        members = members[np.argsort(-deg[members], kind="stable")]
        chosen.extend(members[:q].tolist())
    chosen = np.array(sorted(chosen))
    local = -np.ones(net.n, dtype=np.int64)
    local[chosen] = np.arange(len(chosen))
    m = (local[net.src] >= 0) & (local[net.dst] >= 0)
    s, d = local[net.src[m]], local[net.dst[m]]
    # drop accounts left without any edge inside the sample
    connected = np.zeros(len(chosen), dtype=bool)
    connected[s] = True
    connected[d] = True
    chosen = chosen[connected]
    local[:] = -1
    local[chosen] = np.arange(len(chosen))
    m = (local[net.src] >= 0) & (local[net.dst] >= 0)
    s, d = local[net.src[m]], local[net.dst[m]]
    k = len(chosen)

    # --- layout: communities start on a circle, then a force-directed refinement
    G = nx.Graph()
    G.add_nodes_from(range(k))
    G.add_edges_from(zip(s.tolist(), d.tolist()))
    rng = np.random.default_rng(seed)
    comm_local = lab[chosen]
    uniq = sorted(set(comm_local.tolist()))
    angle = {c: 2 * math.pi * i / len(uniq) for i, c in enumerate(uniq)}
    init = {}
    for i in range(k):
        a = angle[comm_local[i]]
        init[i] = np.array([math.cos(a), math.sin(a)]) * 1.0 + rng.normal(0, 0.18, 2)
    pos = nx.spring_layout(G, pos=init, k=1.6 / math.sqrt(k), iterations=120, seed=seed)
    xy = np.array([pos[i] for i in range(k)])
    xy = (xy - xy.min(0)) / (xy.max(0) - xy.min(0))
    xy = 0.04 + 0.92 * xy

    sub = SubNet(k, s, d)
    adj = [[] for _ in range(k)]
    for a, b in zip(s.tolist(), d.tolist()):
        adj[a].append(b)
    sub_btw = brandes_exact(adj)
    sub_pr = pagerank(sub)
    return {
        "global_index": chosen,
        "xy": xy,
        "src": s, "dst": d,
        "sub": sub,
        "sub_betweenness": sub_btw,
        "sub_pagerank": sub_pr,
        "comm": comm_local,
    }


def sample_payload(net, derived, sample, node_prob):
    g = sample["global_index"]
    ids = net.ids[net.node_codes[g]]
    nodes = []
    for i, gi in enumerate(g.tolist()):
        nodes.append({
            "id": str(ids[i]),
            "x": round(float(sample["xy"][i, 0]), 4),
            "y": round(float(sample["xy"][i, 1]), 4),
            "louvain": int(derived["louvain"][gi]),
            "infomap": int(net.infomap[gi]),
            "outdeg": int(net.outdeg[gi]),
            "indeg": int(net.indeg[gi]),
            "btw": float(derived["betweenness"][gi]),
            "pr": float(derived["pagerank"][gi] * net.n),
            "flag": round(float(net.flag_share_node[gi]), 4),
            "pred": round(float(node_prob[gi]), 4),
            "seedable": bool(net.flag_share_node[gi] > 0),
        })
    return {"nodes": nodes, "edges": np.stack([sample["src"], sample["dst"]], 1).tolist()}
