"""Stage 6 - Fact-check placement experiment (Independent Cascade, live-edge form).

One trial:
  1. pick seed accounts (accounts with at least one flagged post);
  2. every directed edge is independently "live" with probability p;
  3. the claim reaches every account reachable from the seeds through live edges;
  4. targeted (fact-checked) accounts can still receive the claim but never pass it on.
Every strategy is evaluated on exactly the same seeds and live edges (paired design).
"""
import math

import numpy as np

from . import config


class CascadeEngine:
    def __init__(self, n, src, dst):
        self.n = n
        self.E = len(src)
        self.order = np.argsort(src, kind="stable")
        self.s_src = src[self.order]
        self.s_dst = dst[self.order]

    def live_graph(self, live_mask):
        lm = live_mask[self.order]
        counts = np.bincount(self.s_src[lm], minlength=self.n)
        indptr = np.zeros(self.n + 1, dtype=np.int64)
        np.cumsum(counts, out=indptr[1:])
        return indptr, self.s_dst[lm]

    def spread(self, indptr, nbr, seeds, blocked, trace=False):
        """Breadth-first spread over live edges. Returns #reached (or the wave-by-wave trace)."""
        visited = np.zeros(self.n, dtype=bool)
        seeds = np.unique(seeds)
        visited[seeds] = True
        frontier = seeds
        waves = [seeds.tolist()] if trace else None
        while frontier.size:
            f = frontier[~blocked[frontier]]
            if not f.size:
                break
            starts = indptr[f]
            cnt = indptr[f + 1] - starts
            tot = int(cnt.sum())
            if not tot:
                break
            offs = np.repeat(starts - (np.cumsum(cnt) - cnt), cnt) + np.arange(tot)
            nb = nbr[offs]
            nb = np.unique(nb[~visited[nb]])
            if not nb.size:
                break
            visited[nb] = True
            frontier = nb
            if trace:
                waves.append(nb.tolist())
        return waves if trace else int(visited.sum())


def budget_size(n, pct):
    return max(1, int(math.ceil(pct / 100.0 * n)))


def trial_rng(net_index, p, seed=0):
    # seed 0 reproduces the presentation exactly
    return np.random.default_rng(config.BASE_SEED + net_index * 1000 + int(p * 1000) + seed * 7919)


def run_trials(engine, seed_pool, targets, p, budget, n_seeds, trials, rng, progress=None):
    """targets: dict strategy -> fixed index array. 'random' is redrawn inside every trial."""
    blocked = {}
    for name, idx in targets.items():
        mask = np.zeros(engine.n, dtype=bool)
        mask[np.asarray(idx, dtype=np.int64)] = True
        blocked[name] = mask
    none = np.zeros(engine.n, dtype=bool)
    runs = {"baseline": [], "random": []}
    runs.update({k: [] for k in targets})
    n_seeds = min(n_seeds, len(seed_pool))
    for t in range(trials):
        if progress and t % 10 == 0:
            progress(t / trials)
        seeds = rng.choice(seed_pool, n_seeds, replace=False)
        live = rng.random(engine.E) < p
        rand = rng.choice(engine.n, budget, replace=False)
        indptr, nbr = engine.live_graph(live)
        runs["baseline"].append(engine.spread(indptr, nbr, seeds, none))
        rmask = np.zeros(engine.n, dtype=bool)
        rmask[rand] = True
        runs["random"].append(engine.spread(indptr, nbr, seeds, rmask))
        for name, mask in blocked.items():
            runs[name].append(engine.spread(indptr, nbr, seeds, mask))
    return {k: np.asarray(v) for k, v in runs.items()}


def summarise(runs, boot=2000):
    base = runs["baseline"].astype(float)
    T = len(base)
    idx = np.random.default_rng(config.BASE_SEED).integers(0, T, (boot, T))
    out = {"trials": T, "baseline_mean": float(base.mean()), "baseline_median": float(np.median(base)),
           "strategies": {}}
    for name, vals in runs.items():
        if name == "baseline":
            continue
        v = vals.astype(float)
        red = 1 - v.mean() / base.mean() if base.mean() else 0.0
        bs = 1 - v[idx].mean(1) / base[idx].mean(1)
        lo, hi = np.quantile(bs, [0.025, 0.975])
        out["strategies"][name] = {
            "mean_reach": float(v.mean()), "median_reach": float(np.median(v)),
            "reduction": float(red), "ci_low": float(lo), "ci_high": float(hi),
            "wins_vs_baseline": float((v < base).mean()),
        }
    return out


def paired_difference(runs, a, b, boot=2000):
    """Bootstrap CI for reduction(a) - reduction(b): is one strategy really better?"""
    base = runs["baseline"].astype(float)
    T = len(base)
    idx = np.random.default_rng(config.BASE_SEED + 1).integers(0, T, (boot, T))
    ra = 1 - runs[a][idx].mean(1) / base[idx].mean(1)
    rb = 1 - runs[b][idx].mean(1) / base[idx].mean(1)
    d = ra - rb
    lo, hi = np.quantile(d, [0.025, 0.975])
    return {"diff": float(d.mean()), "ci_low": float(lo), "ci_high": float(hi),
            "significant": bool(lo > 0 or hi < 0)}
