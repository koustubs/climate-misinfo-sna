# Detection and Network Analysis of Climate Change Misinformation on Social Media

This project is a local web app that runs a full social network analysis pipeline on the
**DIGSUM COP26/COP27 climate-misinformation dataset** (674,485 anonymised tweets) and lets you
explore the results in the browser.

**Question:** if fact-checkers can only reach 1% of accounts, which accounts should get a correction first?

## Run it (one click)

1. Click **Code → Download ZIP** on GitHub, or clone the repo.
2. Extract the zip. Don't run it from inside the zip.
3. Start the launcher:
   - **Windows:** double-click **`START_WINDOWS.bat`**. If you see "Windows protected your PC", click *More info → Run anyway*.
   - **macOS / Linux:** double-click `START_MAC_LINUX.command`, or run `bash START_MAC_LINUX.command`.
4. The browser opens at http://127.0.0.1:8765. Keep the console window open while you use it.

**Needs:** Python 3.10 or newer (3.14 works). When installing Python, tick **"Add python.exe to PATH"**.

**First launch** creates a private environment (`.venv`) and installs the libraries, which is about 70 MB and needs
internet once. It then processes the dataset, which takes about a minute, with progress shown in the browser. **After that the app starts in seconds and works offline.**

The dataset is already in `data/`. Nothing else needs downloading.

## What the app shows

| Tab | Contents |
|---|---|
| **01 Overview** | Dataset verified against Zenodo (MD5), key numbers and findings, the 7-stage pipeline with timings |
| **02 Network & communities** | Interactive retweet graph. **Louvain** (ours) vs **Infomap** (dataset) communities, modularity, NMI/ARI, flow matrix, most central accounts |
| **03 Spreader detection** | Logistic regression, random forest and gradient boosting detecting misinformation-spreading accounts from **network behaviour only**: ROC curve, confusion matrix, feature importance, ablation |
| **04 Fact-check experiment** | Independent Cascade simulation comparing random, degree, bridge (betweenness), PageRank and detector-guided targeting, with 95% CIs, a sweep over p, and a "Slide settings" preset that reproduces our reported numbers exactly |
| **05 Cascade playground** | One claim spreading wave by wave, side by side, with and without fact checks |
| **06 Methods** | Formulas, data, limitations and a code map |

Use the **COP26 / COP27** switch at the top right to change networks.

## Key results

| | COP26 | COP27 |
|---|---|---|
| Retweet network (nodes / edges) | 13,640 / 183,344 | 8,028 / 50,416 |
| Louvain modularity (NMI vs Infomap) | 0.742 (0.82) | 0.843 (0.79) |
| Retweets crossing communities | 11.1% | 13.1% |
| Best spreader detector (ROC-AUC) | Logistic regression, 0.767 | Logistic regression, 0.822 |
| Best placement at p = 10%, 1% budget | **Bridge: −58.8% reach** | **Degree: −41.7% reach** |
| Random placement / detector-guided placement | −3.8% / −3.0% | −1.8% / −3.1% |

Network position, not an account's likelihood of spreading misinformation, decides where a limited number of corrections works best.
The simulation assumes a fact check stops sharing completely, so these figures are best-case values.

## Repository layout

```
app.py                     Flask web server + JSON API
sna/                       Analysis pipeline
  ingest.py                  Stream the raw CSV, verify MD5, encode IDs
  graph.py                   Directed retweet networks (author -> retweeter) + statistics
  communities.py             Louvain, modularity, NMI/ARI vs Infomap, flow matrices
  centrality.py              Degree, Brandes betweenness (sampled), PageRank
  detection.py               Features, classifiers, evaluation
  simulation.py              Independent Cascade engine, paired trials, bootstrap CIs
  layout.py                  Network sample + force-directed layout for the browser
  pipeline.py                Runs the stages, reports progress, caches results in cache/
  config.py                  Settings (BASE_SEED = 20260929 reproduces every reported number)
web/                       Browser interface (HTML/CSS/JS + Chart.js)
data/                      network_tweets.csv.xz (original Zenodo file, compressed)
START_WINDOWS.bat          One-click launcher (Windows)
START_MAC_LINUX.command    One-click launcher (macOS/Linux)
```

## Data and credit

- Dataset: DIGSUM, *cop26-27-tweets*, Zenodo (2026), https://zenodo.org/records/19002468
- Context: Lundstedt & Lindgren, *Journal of Computational Social Science* (2026), https://doi.org/10.1007/s42001-026-00488-x
- Chart.js is bundled under its MIT licence (`web/vendor/CHARTJS_LICENSE.md`).

Posts date from COP26 (2021) and COP27 (2022); the dataset was released in 2026. The misinformation labels are the
dataset classifier's outputs, and the tweets contain no text.

## Troubleshooting

- **"Smart App Control blocked this file"** (Windows 11): Smart App Control blocks unsigned scripts and some library files.
  Turn it off in *Windows Security → App & browser control → Smart App Control*. Windows only lets you turn it back on by resetting the PC.
  Then open a terminal in this folder and run `py -m pip install -r requirements.txt` followed by `py app.py`.
- **Browser didn't open:** go to http://127.0.0.1:8765 manually.
- **Install failed:** usually there's no internet connection. Connect and run the launcher again.
- **Start completely fresh:** delete the `.venv` and `cache` folders and run the launcher again.
