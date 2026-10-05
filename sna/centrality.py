"""Stage 4 - Centrality: degree, sampled betweenness (Brandes) and PageRank."""
from collections import deque

import numpy as np


def adjacency(net):
    adj = [[] for _ in range(net.n)]
    for a, b in zip(net.src.tolist(), net.dst.tolist()):
        adj[a].append(b)
    return adj


def brandes_sampled(adj, k=128, seed=10, progress=None):
    """Directed, unweighted betweenness estimated from k random source nodes (Brandes, 2001).

    Exact betweenness needs one BFS per node (13,640 BFS runs for COP26); sampling
    k sources gives an unbiased estimate of the same ranking at a fraction of the cost.
    """
    n = len(adj)
    scores = np.zeros(n)
    rng = np.random.default_rng(seed)
    sources = rng.choice(n, min(n, k), replace=False)
    for t, source in enumerate(sources):
        if progress and t % 16 == 0:
            progress(t / len(sources))
        stack = []
        pred = [[] for _ in range(n)]
        sigma = np.zeros(n)
        sigma[source] = 1
        dist = np.full(n, -1)
        dist[source] = 0
        q = deque([int(source)])
        while q:
            v = q.popleft()
            stack.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = np.zeros(n)
        for w in reversed(stack):
            if sigma[w]:
                coefficient = (1 + delta[w]) / sigma[w]
                for v in pred[w]:
                    delta[v] += sigma[v] * coefficient
            if w != source:
                scores[w] += delta[w]
    return scores


def brandes_exact(adj):
    return brandes_sampled(adj, k=len(adj), seed=0)


def pagerank(net, damping=0.85, tol=1e-10, max_iter=200):
    """PageRank on the reversed graph (retweeter -> author), so accounts retweeted by
    influential accounts score highly. Dangling mass is spread uniformly."""
    n = net.n
    r_src, r_dst = net.dst, net.src
    outw = np.bincount(r_src, minlength=n).astype(float)
    pr = np.full(n, 1.0 / n)
    dangling = outw == 0
    for _ in range(max_iter):
        share = np.where(dangling, 0.0, pr / np.where(dangling, 1.0, outw))
        new = np.bincount(r_dst, weights=share[r_src], minlength=n)
        new = (1 - damping) / n + damping * (new + pr[dangling].sum() / n)
        if np.abs(new - pr).sum() < tol:
            pr = new
            break
        pr = new
    return pr / pr.sum()


def top_k(scores, k):
    """Indices of the k highest scores; ties broken by node order (deterministic)."""
    return np.argsort(-np.asarray(scores), kind="stable")[:k]
