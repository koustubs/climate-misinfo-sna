"""Stage 5 - Detecting misinformation-spreading accounts from network behaviour.

Question: can we tell which accounts spread misinformation from *how they sit in the
network and how they behave*, without reading their posts?

Label   : an account (>= min_posts posts) is a "spreader" when at least `share` of its
          posts were flagged by the dataset's text classifier (probability >= 0.5).
Features: never use the account's own flags/probabilities or the dataset's
          disinfo-derived community categories. Three groups:
            behaviour  - how the account posts
            structure  - where it sits in the retweet graph (SNA measures)
            homophily  - how many of its network neighbours are *known* spreaders
                         (computed from training accounts only, so no test labels leak)
Split   : stratified 70/30 train/test, fixed seed.
"""
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, average_precision_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score, roc_curve)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = {
    "behaviour": [
        ("log_posts", "Posts (log)"),
        ("rt_share", "Retweet share"),
        ("qt_share", "Quote share"),
        ("rp_share", "Reply share"),
        ("active_days", "Active days"),
        ("posts_per_day", "Posts per active day"),
    ],
    "structure": [
        ("log_outdeg", "Out-degree: retweeters (log)"),
        ("log_indeg", "In-degree: accounts retweeted (log)"),
        ("pagerank", "PageRank (log)"),
        ("betweenness", "Betweenness (log)"),
        ("kcore", "k-core number"),
        ("reciprocity", "Reciprocity"),
        ("comm_size", "Community size (log)"),
    ],
    "homophily": [
        ("src_spreaders", "Retweets known spreaders"),
        ("aud_spreaders", "Retweeted by known spreaders"),
        ("comm_spreaders", "Known spreaders in community"),
    ],
}
GROUP_ORDER = ["behaviour", "structure", "homophily"]
MODELS = {
    "boosting": "Gradient boosting",
    "forest": "Random forest",
    "logreg": "Logistic regression",
}


def _make_model(kind):
    if kind == "logreg":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             LogisticRegression(max_iter=3000, class_weight="balanced"))
    if kind == "forest":
        return make_pipeline(SimpleImputer(strategy="median"),
                             RandomForestClassifier(n_estimators=150, min_samples_leaf=3,
                                                    class_weight="balanced_subsample",
                                                    n_jobs=1, random_state=0))
    return HistGradientBoostingClassifier(class_weight="balanced", random_state=0)


def base_features(net, derived):
    """Features that do not depend on labels, one row per posting account."""
    st = net.poster_stats
    P = len(net.posters)
    X = {
        "log_posts": np.log1p(st["n_posts"]),
        "rt_share": st["rt_share"],
        "qt_share": st["qt_share"],
        "rp_share": st["rp_share"],
        "active_days": st["active_days"].astype(float),
        "posts_per_day": st["n_posts"] / np.maximum(st["active_days"], 1),
    }
    node_of = np.full(P, -1)
    node_of[net.node_poster] = np.arange(net.n)
    in_graph = node_of >= 0
    g = node_of[in_graph]

    def per_poster(node_values, fill=0.0):
        out = np.full(P, fill, dtype=float)
        out[in_graph] = node_values[g]
        return out

    # reciprocity: share of an account's neighbours that it both retweets and is retweeted by
    pairs_fwd = set(zip(net.src.tolist(), net.dst.tolist()))
    recip_edges = np.array([(b, a) in pairs_fwd for a, b in zip(net.src.tolist(), net.dst.tolist())])
    recip = np.bincount(net.src, weights=recip_edges, minlength=net.n) + \
        np.bincount(net.dst, weights=recip_edges, minlength=net.n)
    deg = net.outdeg + net.indeg
    comm_sizes = np.bincount(derived["louvain"])
    X.update({
        "log_outdeg": per_poster(np.log1p(net.outdeg)),
        "log_indeg": per_poster(np.log1p(net.indeg)),
        "pagerank": per_poster(np.log10(derived["pagerank"] * net.n), fill=np.nan),
        "betweenness": per_poster(np.log1p(derived["betweenness"])),
        "kcore": per_poster(derived["kcore"].astype(float)),
        "reciprocity": per_poster(recip / np.maximum(deg, 1)),
        "comm_size": per_poster(np.log1p(comm_sizes[derived["louvain"]]), fill=0.0),
    })
    return X, node_of


def homophily_features(net, derived, node_of, y_poster, train_mask_poster):
    """Neighbour-label features using TRAINING labels only."""
    n = net.n
    known = np.zeros(n, dtype=bool)
    spread = np.zeros(n, dtype=bool)
    in_graph = node_of >= 0
    known_p = train_mask_poster & in_graph
    known[node_of[known_p]] = True
    spread[node_of[known_p & (y_poster == 1)]] = True
    s, d = net.src, net.dst
    # accounts a node retweets = its sources (edges s -> node)
    src_known = np.bincount(d, weights=known[s], minlength=n)
    src_spread = np.bincount(d, weights=spread[s], minlength=n)
    aud_known = np.bincount(s, weights=known[d], minlength=n)
    aud_spread = np.bincount(s, weights=spread[d], minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        src_share = np.where(src_known > 0, src_spread / src_known, np.nan)
        aud_share = np.where(aud_known > 0, aud_spread / aud_known, np.nan)
    lab = derived["louvain"]
    C = lab.max() + 1
    c_known = np.bincount(lab, weights=known, minlength=C)
    c_spread = np.bincount(lab, weights=spread, minlength=C)
    with np.errstate(invalid="ignore", divide="ignore"):
        comm_rate = np.where(c_known[lab] > 0, c_spread[lab] / c_known[lab], np.nan)
    P = len(node_of)

    def per_poster(v):
        out = np.full(P, np.nan)
        out[in_graph] = v[node_of[in_graph]]
        return out

    return {"src_spreaders": per_poster(src_share), "aud_spreaders": per_poster(aud_share),
            "comm_spreaders": per_poster(comm_rate)}


def _matrix(X, names, rows):
    return np.column_stack([X[k][rows] for k in names])


def run_detection(net, derived, model="boosting", share=0.20, min_posts=3,
                  groups=("behaviour", "structure", "homophily"), compare=True, importance=True):
    st = net.poster_stats
    labelled = st["n_posts"] >= min_posts
    y_all = ((st["n_flag"] / st["n_posts"]) >= share).astype(int)
    rows = np.where(labelled)[0]
    y = y_all[rows]
    if y.sum() < 20 or (len(y) - y.sum()) < 20:
        raise ValueError("Too few spreaders/non-spreaders for this threshold - try another value.")
    tr, te = train_test_split(rows, test_size=0.3, stratify=y, random_state=42)
    train_mask = np.zeros(len(net.posters), dtype=bool)
    train_mask[tr] = True

    X, node_of = base_features(net, derived)
    # Homophily features, out-of-fold: a training account only sees labels from the
    # other 4 training folds (never its own); test accounts see all training labels.
    H = homophily_features(net, derived, node_of, y_all, train_mask)
    rng = np.random.default_rng(0)
    fold_of = np.full(len(net.posters), -1)
    fold_of[tr] = rng.permutation(len(tr)) % 5
    for k in range(5):
        in_k = fold_of == k
        Hk = homophily_features(net, derived, node_of, y_all, train_mask & ~in_k)
        for f in H:
            H[f][in_k] = Hk[f][in_k]
    X.update(H)

    groups = [g for g in GROUP_ORDER if g in groups] or ["behaviour"]
    names = [f for g in groups for f, _ in FEATURES[g]]
    label_of = {f: lbl for g in GROUP_ORDER for f, lbl in FEATURES[g]}
    group_of = {f: g for g in GROUP_ORDER for f, _ in FEATURES[g]}

    def fit_eval(feat_names):
        m = _make_model(model)
        m.fit(_matrix(X, feat_names, tr), y_all[tr])
        prob = m.predict_proba(_matrix(X, feat_names, te))[:, 1]
        return m, prob

    clf, prob = fit_eval(names)
    yt = y_all[te]
    pred = (prob >= 0.5).astype(int)
    fpr, tpr, _ = roc_curve(yt, prob)
    keep = np.unique(np.linspace(0, len(fpr) - 1, min(len(fpr), 120)).astype(int))
    cm = confusion_matrix(yt, pred, labels=[0, 1])
    res = {
        "settings": {"model": model, "model_label": MODELS.get(model, model), "share": share,
                     "min_posts": min_posts, "groups": groups},
        "counts": {"accounts": int(len(rows)), "spreaders": int(y.sum()),
                   "base_rate": float(y.mean()), "train": int(len(tr)), "test": int(len(te))},
        "metrics": {
            "accuracy": float(accuracy_score(yt, pred)),
            "precision": float(precision_score(yt, pred, zero_division=0)),
            "recall": float(recall_score(yt, pred, zero_division=0)),
            "f1": float(f1_score(yt, pred, zero_division=0)),
            "roc_auc": float(roc_auc_score(yt, prob)),
            "avg_precision": float(average_precision_score(yt, prob)),
        },
        "confusion": cm.tolist(),
        "roc": {"fpr": fpr[keep].round(4).tolist(), "tpr": tpr[keep].round(4).tolist()},
    }

    if importance:
        imp = permutation_importance(clf, _matrix(X, names, te), yt, scoring="roc_auc",
                                     n_repeats=5, random_state=0)
        order = np.argsort(-imp.importances_mean)
        res["importance"] = [{"feature": names[i], "label": label_of[names[i]], "group": group_of[names[i]],
                              "value": float(imp.importances_mean[i])} for i in order]

    if compare:
        comp = []
        for k in range(1, len(GROUP_ORDER) + 1):
            gs = GROUP_ORDER[:k]
            fn = [f for g in gs for f, _ in FEATURES[g]]
            if fn == names:
                p_ = prob
            else:
                _, p_ = fit_eval(fn)
            comp.append({"groups": gs, "label": " + ".join(g.capitalize() for g in gs),
                         "roc_auc": float(roc_auc_score(yt, p_)),
                         "f1": float(f1_score(yt, (p_ >= 0.5).astype(int), zero_division=0))})
        res["comparison"] = comp

    # spreader probability for every account in the graph (used by the "Detector" strategy)
    node_rows = net.node_poster
    node_prob = clf.predict_proba(_matrix(X, names, node_rows))[:, 1]
    # show the highest-scoring *test* accounts with their true label
    test_top = te[np.argsort(-prob)[:10]]
    res["top_test_accounts"] = [{
        "account": str(net.ids[net.posters[r]]) if hasattr(net, "ids") else int(net.posters[r]),
        "score": float(prob[np.where(te == r)[0][0]]),
        "flagged_share": float(st["n_flag"][r] / st["n_posts"][r]),
        "posts": int(st["n_posts"][r]),
        "is_spreader": int(y_all[r]),
    } for r in test_top]
    return res, node_prob
