"""Stage 1 - Ingest the raw Zenodo CSV into compact numpy arrays.

The original file (674,485 rows, 92.8 MB) ships xz-compressed in data/.
We stream it once, check its MD5 against the value published on Zenodo,
and encode every anonymised account ID as an integer.
"""
import csv
import gzip
import hashlib
import io
import lzma

import numpy as np

from . import config

CATEGORY_CODE = {"non-disinfo": 0, "mixed": 1, "disinfo": 2}
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


class _HashingLines:
    """Iterate decoded text lines while hashing the raw bytes (for the integrity check)."""

    def __init__(self, fh):
        self.fh = fh
        self.md5 = hashlib.md5()

    def __iter__(self):
        for raw in self.fh:
            self.md5.update(raw)
            yield raw.decode("utf-8")


def _open_raw():
    if config.RAW_CSV.exists():
        return open(config.RAW_CSV, "rb"), config.RAW_CSV.name
    if config.RAW_CSV_XZ.exists():
        return lzma.open(config.RAW_CSV_XZ, "rb"), config.RAW_CSV_XZ.name
    if config.RAW_CSV_GZ.exists():
        return gzip.open(config.RAW_CSV_GZ, "rb"), config.RAW_CSV_GZ.name
    raise FileNotFoundError(
        "Dataset not found. Put network_tweets.csv.xz (or the plain CSV) in the data/ folder. "
        f"Source: {config.ZENODO_URL}")


def _day_key(created_at):
    """Both timestamp styles in the file -> yyyymmdd.
    "Wed Oct 27 13:59:54 +0000 2021" (Twitter API v1) or "2021-11-10T23:59:48.000Z" (API v2)."""
    if created_at[:1].isdigit():
        return int(created_at[0:4]) * 10000 + int(created_at[5:7]) * 100 + int(created_at[8:10])
    parts = created_at.split()
    if len(parts) == 6:
        return int(parts[5]) * 10000 + MONTHS[parts[1]] * 100 + int(parts[2])
    return 0


def ingest(progress=lambda msg, frac: None):
    fh, source_name = _open_raw()
    lines = _HashingLines(fh)
    reader = csv.reader(lines)
    header = next(reader)
    col = {name: i for i, name in enumerate(header)}
    need = ["user_id_anon", "subset", "created_at", "like_count", "retweeted_user_anon",
            "quoted_user_anon", "replied_user_anon", "community", "community_category",
            "disinfo_probability", "is_disinfo", "tweet_id"]
    missing = [c for c in need if c not in col]
    if missing:
        raise ValueError(f"Unexpected CSV format, missing columns: {missing}")

    code = {}

    def enc(s):
        if not s:
            return -1
        c = code.get(s)
        if c is None:
            c = code[s] = len(code)
        return c

    cols = {k: [] for k in ["user", "subset", "rt", "qt", "rp", "community", "category",
                            "prob", "flag", "day", "likes"]}
    seen_tweets = set()
    duplicates = 0
    i_user, i_sub, i_day = col["user_id_anon"], col["subset"], col["created_at"]
    i_rt, i_qt, i_rp = col["retweeted_user_anon"], col["quoted_user_anon"], col["replied_user_anon"]
    i_com, i_cat = col["community"], col["community_category"]
    i_prob, i_flag, i_like, i_tid = col["disinfo_probability"], col["is_disinfo"], col["like_count"], col["tweet_id"]
    subsets = {}
    for n, row in enumerate(reader):
        if n % 50000 == 0:
            progress(f"Reading records... {n:,}", min(n / 674485, 1.0))
        tid = row[i_tid]
        if tid in seen_tweets:
            duplicates += 1
        seen_tweets.add(tid)
        cols["user"].append(enc(row[i_user]))
        cols["subset"].append(subsets.setdefault(row[i_sub], len(subsets)))
        cols["rt"].append(enc(row[i_rt]))
        cols["qt"].append(enc(row[i_qt]))
        cols["rp"].append(enc(row[i_rp]))
        com = row[i_com]
        cols["community"].append(int(float(com)) if com else -1)
        cols["category"].append(CATEGORY_CODE.get(row[i_cat], -1))
        cols["prob"].append(float(row[i_prob]))
        cols["flag"].append(int(row[i_flag]))
        cols["day"].append(_day_key(row[i_day]))
        lk = row[i_like]
        cols["likes"].append(float(lk) if lk else 0.0)
    fh.close()
    md5 = lines.md5.hexdigest()

    # Re-number IDs so that integer order == string order (keeps node ordering identical
    # to the original pandas analysis, which sorted the string IDs).
    ids = np.array(list(code.keys()))
    order = np.argsort(ids, kind="stable")
    rank = np.empty(len(ids), dtype=np.int64)
    rank[order] = np.arange(len(ids))
    ids_sorted = ids[order]

    def remap(lst):
        a = np.asarray(lst, dtype=np.int64)
        out = np.where(a >= 0, rank[np.maximum(a, 0)], -1)
        return out.astype(np.int32)

    subset_names = [None] * len(subsets)
    for name, k in subsets.items():
        subset_names[k] = name
    data = {
        "user": remap(cols["user"]),
        "subset": np.asarray(cols["subset"], dtype=np.int8),
        "rt": remap(cols["rt"]),
        "qt": remap(cols["qt"]),
        "rp": remap(cols["rp"]),
        "community": np.asarray(cols["community"], dtype=np.int32),
        "category": np.asarray(cols["category"], dtype=np.int8),
        "prob": np.asarray(cols["prob"], dtype=np.float32),
        "flag": np.asarray(cols["flag"], dtype=np.int8),
        "day": np.asarray(cols["day"], dtype=np.int32),
        "likes": np.asarray(cols["likes"], dtype=np.float32),
        "ids": ids_sorted,
    }
    meta = {
        "source_file": source_name,
        "rows": int(len(data["user"])),
        "md5": md5,
        "md5_expected": config.ZENODO_MD5,
        "md5_ok": md5 == config.ZENODO_MD5,
        "duplicate_tweet_ids": duplicates,
        "distinct_accounts": int(len(np.unique(data["user"]))),
        "subset_names": subset_names,
    }
    progress("Records loaded", 1.0)
    return data, meta
