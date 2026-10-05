"""Stage 2 - Build one directed retweet network per conference.

Rules (identical to the analysis in the presentation):
  * only retweets are used (a retweet is an unambiguous "pass it on");
  * a retweet is kept when the original author also posted in the same conference subset;
  * edge direction = original author -> retweeter (direction information flows);
  * repeated retweets between the same pair collapse to one edge; self-retweets are dropped.
"""
import numpy as np


class Network:
    """Plain container for one conference's graph and per-account statistics."""

    def __init__(self, name):
        self.name = name


def build_network(data, subset_code, name):
    m = data["subset"] == subset_code
    user = data["user"][m].astype(np.int64)
    rt = data["rt"][m].astype(np.int64)
    qt = data["qt"][m]
    rp = data["rp"][m]
    com = data["community"][m]
    cat = data["category"][m]
    flag = data["flag"][m]
    day = data["day"][m]
    n_ids = len(data["ids"])

    net = Network(name)
    posters = np.unique(user)
    pairs = np.unique(np.stack([user, com.astype(np.int64)], 1), axis=0)
    if len(pairs) != len(posters):
        raise ValueError("An account has more than one community label inside one conference.")
    com_of = np.full(n_ids, -1, dtype=np.int64)
    com_of[pairs[:, 0]] = pairs[:, 1]
    cat_of = np.full(n_ids, -1, dtype=np.int64)
    cat_of[user] = cat
    is_poster = np.zeros(n_ids, dtype=bool)
    is_poster[posters] = True

    # ---- retweets whose original author is inside the released subset ("matched")
    has_rt = rt >= 0
    known = has_rt & is_poster[np.maximum(rt, 0)]
    tgt, usr = rt[known], user[known]

    # ---- unique directed edges, in first-occurrence order
    key = tgt * n_ids + usr
    uniq, first, counts = np.unique(key, return_index=True, return_counts=True)
    order = np.argsort(first, kind="stable")
    e_t, e_u, e_w = tgt[first[order]], usr[first[order]], counts[order]
    keep = e_t != e_u
    self_loops = int((~keep).sum())
    e_t, e_u, e_w = e_t[keep], e_u[keep], e_w[keep]
    node_codes = np.unique(np.concatenate([e_t, e_u]))
    src = np.searchsorted(node_codes, e_t)
    dst = np.searchsorted(node_codes, e_u)
    n = len(node_codes)

    net.node_codes = node_codes
    net.n = n
    net.src, net.dst, net.weight = src.astype(np.int64), dst.astype(np.int64), e_w.astype(np.int64)
    net.outdeg = np.bincount(src, minlength=n)       # distinct accounts that retweeted this account
    net.indeg = np.bincount(dst, minlength=n)        # distinct accounts this account retweeted
    net.infomap = com_of[node_codes]                 # community supplied with the dataset
    net.com_of = com_of
    net.matched_tgt, net.matched_usr = tgt, usr      # every matched retweet event

    # ---- per posting-account statistics (used by detection and tooltips)
    pidx = np.searchsorted(posters, user)
    P = len(posters)
    n_posts = np.bincount(pidx, minlength=P)
    n_flag = np.bincount(pidx, weights=flag, minlength=P)
    n_rt = np.bincount(pidx, weights=has_rt, minlength=P)
    n_qt = np.bincount(pidx, weights=qt >= 0, minlength=P)
    n_rp = np.bincount(pidx, weights=rp >= 0, minlength=P)
    ud = np.unique(np.stack([pidx, day.astype(np.int64)], 1), axis=0)
    active_days = np.bincount(ud[:, 0], minlength=P)
    net.posters = posters
    net.poster_stats = {
        "n_posts": n_posts, "n_flag": n_flag, "rt_share": n_rt / n_posts,
        "qt_share": n_qt / n_posts, "rp_share": n_rp / n_posts, "active_days": active_days,
    }
    # map graph nodes -> poster rows (every graph node is a posting account)
    net.node_poster = np.searchsorted(posters, node_codes)
    net.flag_share_node = n_flag[net.node_poster] / n_posts[net.node_poster]

    flagged_accounts = posters[n_flag > 0]
    net.seed_pool = np.searchsorted(node_codes, np.intersect1d(flagged_accounts, node_codes))

    # ---- descriptive statistics shown in the app and on slides 3-4
    in_diff_comm = com_of[tgt] != com_of[usr]
    in_diff_cat = cat_of[tgt] != cat_of[usr]
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    ncomp, labels = connected_components(
        csr_matrix((np.ones(len(src)), (src, dst)), shape=(n, n)), directed=True, connection="weak")
    net.stats = {
        "records": int(m.sum()),
        "accounts": int(P),
        "flagged_records": int(flag.sum()),
        "flagged_share": float(flag.mean()),
        "retweet_records": int(has_rt.sum()),
        "quote_records": int((qt >= 0).sum()),
        "reply_records": int((rp >= 0).sum()),
        "matched_retweets": int(known.sum()),
        "match_share": float(known.sum() / max(has_rt.sum(), 1)),
        "cross_community_retweets": int(in_diff_comm.sum()),
        "cross_community_share": float(in_diff_comm.mean()),
        "cross_category_share": float(in_diff_cat.mean()),
        "communities_in_records": int(len(np.unique(com))),
        "graph_nodes": int(n),
        "graph_edges": int(len(src)),
        "self_loops_removed": self_loops,
        "largest_component": int(np.bincount(labels).max()),
        "seed_pool": int(len(net.seed_pool)),
        "density": float(len(src) / (n * (n - 1))),
        "mean_out_degree": float(len(src) / n),
    }
    # communities ranked by number of records (for the flow matrix)
    cvals, ccounts = np.unique(com, return_counts=True)
    net.infomap_rank = cvals[np.argsort(-ccounts, kind="stable")]
    return net


def flow_matrix(tgt_comm, usr_comm, top):
    """Retweet counts between the given communities. Row = original author's, column = retweeter's."""
    k = len(top)
    pos = {c: i for i, c in enumerate(top)}
    M = np.zeros((k, k), dtype=np.int64)
    for a, b in zip(tgt_comm, usr_comm):
        i, j = pos.get(int(a)), pos.get(int(b))
        if i is not None and j is not None:
            M[i, j] += 1
    return M
