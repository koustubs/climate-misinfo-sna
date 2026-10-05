"""Paths and fixed settings shared by every stage of the pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache"
WEB_DIR = ROOT / "web"

RAW_CSV_XZ = DATA_DIR / "network_tweets.csv.xz"   # original Zenodo file, xz-compressed (shipped)
RAW_CSV_GZ = DATA_DIR / "network_tweets.csv.gz"   # gzip version also accepted
RAW_CSV = DATA_DIR / "network_tweets.csv"         # used instead if someone drops the plain CSV in

# Zenodo record 19002468 lists this MD5 for dataset_network_tweets.csv
ZENODO_MD5 = "38511ce8fe5ab7f6ddd4356553960240"
ZENODO_URL = "https://zenodo.org/records/19002468"
PAPER_DOI = "https://doi.org/10.1007/s42001-026-00488-x"

NETWORKS = ("cop26", "cop27")                       # order matters: it fixes the random seeds
NETWORK_LABEL = {"cop26": "COP26 (Glasgow, 2021)", "cop27": "COP27 (Sharm el-Sheikh, 2022)"}

# Same seeds as the analysis behind the presentation, so the numbers reproduce exactly.
BASE_SEED = 20260929
BETWEENNESS_SAMPLES = 128
FLAG_THRESHOLD = 0.5                                 # dataset flags a post when probability >= 0.5

# Default detection settings
DEFAULT_MIN_POSTS = 3
DEFAULT_SPREADER_SHARE = 0.20

CACHE_VERSION = 4
