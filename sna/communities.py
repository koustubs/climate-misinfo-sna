"""Stage 3 - Community detection.

We run our own Louvain community detection (modularity maximisation) on the
undirected, weighted retweet graph and compare it with the Infomap communities
that ship with the dataset.
"""
import networkx as nx
import numpy as np
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

from .graph import flow_matrix


def undirected_graph(net):
    G = nx.Graph()
    G.add_nodes_from(range(net.n))
    w = {}
    for a, b, c in zip(net.src.tolist(), net.dst.tolist(), net.weight.tolist()):
        key = (a, b) if a < b else (b, a)
        w[key] = w.get(key, 0) + c
    G.add_weighted_edges_from((a, b, c) for (a, b), c in w.items())
    return G


def louvain(net, seed=42, resolution=1.0):
    G = undirected_graph(net)
    comms = nx.community.louvain_communities(G, weight="weight", resolution=resolution, seed=seed)
    comms = sorted(comms, key=len, reverse=True)            # community 0 = largest
    labels = np.empty(net.n, dtype=np.int64)
    for i, c in enumerate(comms):
        labels[list(c)] = i
    Q = nx.community.modularity(G, comms, weight="weight")
    return labels, float(Q), G


def summarise(net, labels, Q):
    """Numbers for the Network tab: quality, agreement with Infomap, cross-group sharing, flows."""
    # map matched retweet events (account codes) to Louvain labels
    code_to_node = {int(c): i for i, c in enumerate(net.node_codes)}
    t_nodes = np.array([code_to_node.get(int(c), -1) for c in net.matched_tgt])
    u_nodes = np.array([code_to_node.get(int(c), -1) for c in net.matched_usr])
    ok = (t_nodes >= 0) & (u_nodes >= 0)
    lt, lu = labels[t_nodes[ok]], labels[u_nodes[ok]]
    # events we cannot place are self-retweets -> same community
    cross_louvain = float((lt != lu).sum() / len(net.matched_tgt))

    sizes = np.bincount(labels)
    n_comm = int(len(sizes))
    top = list(range(min(6, n_comm)))
    M_louvain = flow_matrix(lt, lu, top)
    info_top = [int(c) for c in net.infomap_rank[:6]]
    M_info = flow_matrix(net.com_of[net.matched_tgt], net.com_of[net.matched_usr], info_top)

    table = []
    for c in range(min(10, n_comm)):
        members = np.where(labels == c)[0]
        inside = (labels[net.src] == c) & (labels[net.dst] == c)
        info_vals, info_counts = np.unique(net.infomap[members], return_counts=True)
        dom = int(info_vals[np.argmax(info_counts)])
        table.append({
            "community": c,
            "accounts": int(len(members)),
            "share_of_graph": float(len(members) / net.n),
            "internal_edges": int(inside.sum()),
            "flagged_share": float(np.mean(net.flag_share_node[members])),
            "hub_outdegree": int(net.outdeg[members].max()),
            "main_infomap": dom,
            "main_infomap_overlap": float(info_counts.max() / len(members)),
        })
    return {
        "louvain_communities": n_comm,
        "louvain_modularity": Q,
        "infomap_communities": int(len(np.unique(net.infomap))),
        "nmi_vs_infomap": float(normalized_mutual_info_score(net.infomap, labels)),
        "ari_vs_infomap": float(adjusted_rand_score(net.infomap, labels)),
        "cross_share_louvain": cross_louvain,
        "cross_share_infomap": net.stats["cross_community_share"],
        "sizes_top": [int(s) for s in sizes[:12]],
        "table": table,
        "flow_louvain": {"labels": [f"L{c}" for c in top], "matrix": M_louvain.tolist()},
        "flow_infomap": {"labels": [f"C{c}" for c in info_top], "matrix": M_info.tolist()},
    }
