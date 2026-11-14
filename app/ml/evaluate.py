"""Measure categorizer quality and write docs/CATEGORIZER_EVALUATION.md.

    python -m app.ml.evaluate

Two protocols are reported:
  * random 5-fold (stratified): optimistic, because the same merchant appears in
    both train and test folds;
  * merchant-held-out 5-fold (StratifiedGroupKFold): every merchant in a test
    fold is completely unseen in training. This is the realistic number for new
    merchants.
"""
import json
import os
from datetime import date

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold, cross_val_predict
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import make_pipeline as sk_pipeline
from sklearn.svm import LinearSVC

from . import categorizer
from .dataset import MERCHANTS, generate
from .preprocess import normalize_merchant

SEED = 42
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def candidates():
    char = lambda: TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
    return {
        "Char TF-IDF + Logistic Regression": lambda: categorizer.make_pipeline("char"),
        "Word+Char TF-IDF + Logistic Regression": lambda: categorizer.make_pipeline("union"),
        "Char TF-IDF + Linear SVM": lambda: sk_pipeline(char(), LinearSVC(C=1.0)),
        "Word TF-IDF + Naive Bayes": lambda: sk_pipeline(TfidfVectorizer(analyzer="word", ngram_range=(1, 2)), MultinomialNB(alpha=0.3)),
        "Majority class (baseline)": lambda: DummyClassifier(strategy="most_frequent"),
    }


def _splitters():
    return {"random": StratifiedKFold(5, shuffle=True, random_state=SEED),
            "grouped": StratifiedGroupKFold(5, shuffle=True, random_state=SEED)}


def _scores(y, pred):
    p, r, f, _ = precision_recall_fscore_support(y, pred, average="macro", zero_division=0)
    return {"accuracy": round(float(accuracy_score(y, pred)), 4), "macro_precision": round(float(p), 4),
            "macro_recall": round(float(r), 4), "macro_f1": round(float(f), 4)}


def run(write=True):
    rows = generate()
    X = [normalize_merchant(r["description"]) for r in rows]
    y = np.array([r["category"] for r in rows])
    groups = np.array([r["merchant"] for r in rows])
    labels = list(MERCHANTS)

    table, preds = {}, {}
    for name, make in candidates().items():
        table[name] = {}
        for proto, splitter in _splitters().items():
            kw = {"groups": groups} if proto == "grouped" else {}
            pred = cross_val_predict(make(), X, y, cv=splitter, **kw)
            preds[(name, proto)] = pred
            table[name][proto] = _scores(y, pred)

    prod = "Char TF-IDF + Logistic Regression" if categorizer.PRODUCTION_VARIANT == "char" else "Word+Char TF-IDF + Logistic Regression"
    pred_g = preds[(prod, "grouped")]
    p, r, f, sup = precision_recall_fscore_support(y, pred_g, labels=labels, zero_division=0)
    per_class = {c: {"precision": round(float(p[i]), 3), "recall": round(float(r[i]), 3), "f1": round(float(f[i]), 3), "support": int(sup[i])}
                 for i, c in enumerate(labels)}
    cm = confusion_matrix(y, pred_g, labels=labels).tolist()

    hinted = np.array([r["hinted"] for r in rows])
    hint_split = {"with_hint_word": {"n": int(hinted.sum()), "accuracy": round(float(accuracy_score(y[hinted], pred_g[hinted])), 4)},
                  "without_hint_word": {"n": int((~hinted).sum()), "accuracy": round(float(accuracy_score(y[~hinted], pred_g[~hinted])), 4)}}
    proba = cross_val_predict(candidates()[prod](), X, y, cv=_splitters()["grouped"], groups=groups, method="predict_proba")
    classes = sorted(labels)
    top, top_i = proba.max(axis=1), proba.argmax(axis=1)
    hit = np.array([classes[i] for i in top_i]) == y
    confidence = []
    for t in (0.0, 0.3, 0.5, 0.7):
        keep = top >= t
        confidence.append({"threshold": t, "coverage": round(float(keep.mean()), 4),
                           "accuracy": round(float(hit[keep].mean()), 4) if keep.any() else None})

    metrics = {
        "generated": date.today().isoformat(), "model": prod, "samples": len(rows), "merchants": int(len(set(groups))),
        "categories": labels, "seed": SEED,
        "random_cv": table[prod]["random"], "grouped_cv": table[prod]["grouped"],
        "hint_split": hint_split, "confidence": confidence, "comparison": table, "per_class_grouped": per_class, "confusion_grouped": cm,
    }
    if write:
        os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
        with open(os.path.join(ROOT, "docs", "categorizer_metrics.json"), "w", encoding="utf-8") as fh:
            json.dump(metrics, fh, indent=2)
        with open(os.path.join(ROOT, "docs", "CATEGORIZER_EVALUATION.md"), "w", encoding="utf-8") as fh:
            fh.write(markdown(metrics))
    return metrics


def pct(x):
    return f"{x * 100:.1f}%"


def markdown(m):
    L = []
    L += ["# Categorizer evaluation", "",
          f"Generated {m['generated']} by `python -m app.ml.evaluate` (random seed {m['seed']}). All numbers below are measured, not estimated.", "",
          "## What was evaluated", "",
          f"- **Task:** assign one of {len(m['categories'])} spending categories ({', '.join(m['categories'])}) to a bank-statement description.",
          f"- **Data:** {m['samples']} labeled descriptions from {m['merchants']} merchants, **synthetically generated** by `app/ml/dataset.py` "
          "(merchant names combined with UPI/POS/NEFT/IMPS-style templates, reference numbers, cities and optional hint words).",
          "- **Pre-processing:** lower-casing, removal of digits/punctuation and bank noise words (UPI, NEFT, POS, ...).",
          f"- **Production model:** {m['model']}.", "",
          "## Two ways of splitting the data", "",
          "1. **Random 5-fold (stratified).** The same merchant can appear in training and test folds. This is optimistic: it measures how well the model recognises merchants it has already seen.",
          "2. **Merchant-held-out 5-fold (StratifiedGroupKFold).** Every merchant in a test fold is completely unseen during training. This is the realistic estimate for a brand-new merchant and the number to quote.", "",
          "## Headline results (production model)", "",
          "| Protocol | Accuracy | Macro precision | Macro recall | Macro F1 |", "|---|---|---|---|---|"]
    for key, label in (("random_cv", "Random 5-fold"), ("grouped_cv", "Merchant-held-out 5-fold")):
        s = m[key]
        L.append(f"| {label} | {pct(s['accuracy'])} | {pct(s['macro_precision'])} | {pct(s['macro_recall'])} | {pct(s['macro_f1'])} |")
    L += ["", "## Model comparison", "",
          "| Model | Random acc. | Random macro-F1 | Held-out acc. | Held-out macro-F1 |", "|---|---|---|---|---|"]
    for name, t in sorted(m["comparison"].items(), key=lambda kv: -kv[1]["grouped"]["macro_f1"]):
        mark = " **(production)**" if name == m["model"] else ""
        L.append(f"| {name}{mark} | {pct(t['random']['accuracy'])} | {pct(t['random']['macro_f1'])} | {pct(t['grouped']['accuracy'])} | {pct(t['grouped']['macro_f1'])} |")
    L += ["", "The majority-class row is the do-nothing baseline: always predicting the most common category.", "",
          "## Per-category results (merchant-held-out)", "", "| Category | Precision | Recall | F1 | Samples |", "|---|---|---|---|---|"]
    for c, v in m["per_class_grouped"].items():
        L.append(f"| {c} | {pct(v['precision'])} | {pct(v['recall'])} | {pct(v['f1'])} | {v['support']} |")
    L += ["", "## Confusion matrix (merchant-held-out; rows = true, columns = predicted)", "",
          "| true \\ pred | " + " | ".join(m["categories"]) + " |", "|---|" + "---|" * len(m["categories"])]
    for c, row in zip(m["categories"], m["confusion_grouped"]):
        L.append(f"| **{c}** | " + " | ".join(str(v) for v in row) + " |")
    hs = m["hint_split"]
    L += ["", "## Why held-out accuracy is lower, and what helps", "",
          "A merchant name such as \"Swiggy\" carries no category information unless the model has seen it. For brand-new merchants the model can only rely on "
          "descriptive words in the narration (\"pharmacy\", \"fuel\", \"cafe\"...).", "",
          "| Held-out rows | Samples | Accuracy |", "|---|---|---|",
          f"| Description contains a category hint word | {hs['with_hint_word']['n']} | {pct(hs['with_hint_word']['accuracy'])} |",
          f"| Merchant name only | {hs['without_hint_word']['n']} | {pct(hs['without_hint_word']['accuracy'])} |", "",
          "Accuracy when the model is confident (merchant-held-out):", "", "| Minimum confidence | Share of transactions kept | Accuracy on those |", "|---|---|---|"]
    for c in m["confidence"]:
        L.append(f"| {c['threshold']:.1f} | {pct(c['coverage'])} | {pct(c['accuracy']) if c['accuracy'] is not None else 'n/a'} |")
    L += ["", "Practical consequences for the app: (1) known merchants are categorised almost perfectly; (2) unfamiliar ones are right about half the time, "
          "so users should review them in the preview and correct mistakes, after which the same merchant is recognised from then on; "
          "(3) low-confidence predictions are the least reliable and are the ones to check first.", "",
          "## Limitations (please read)", "",
          "- The data is synthetic. Real statements have messier, shorter and more ambiguous narrations, so **real-world accuracy can be lower**. Measure on your own labeled transactions before relying on these numbers.",
          "- Merchants and templates were written by the developer, so the test set shares style with the training set even when merchants are held out.",
          "- \"Other\" is a catch-all and is intrinsically the hardest category.",
          "- The app improves with use: when a user corrects a category, that example is added (with extra weight) to that user's model. This effect is not included in the numbers above.",
          "- Model choice was made by comparing the same cross-validation scores shown here, so the headline numbers are slightly optimistic.", "",
          "## Reproduce", "", "```bash", "python -m app.ml.evaluate", "```", ""]
    return "\n".join(L)


if __name__ == "__main__":
    res = run()
    print(markdown(res))
