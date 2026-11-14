"""AI/ML expense categorisation: TF-IDF + logistic regression.

Trained on a built-in seed set plus any categories the user has confirmed.
"""
from functools import lru_cache

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from .preprocess import normalize_merchant

CATEGORIES = ["Food", "Transport", "Shopping", "Bills", "Entertainment",
              "Health", "Education", "Other"]

SEED = {
    "Food": ["swiggy order", "zomato dinner", "dominos pizza", "mcdonalds", "starbucks coffee",
             "bigbasket groceries", "supermarket", "restaurant bill", "cafe latte", "kfc",
             "blinkit grocery", "bakery", "ubereats meal", "burger king", "grocery store"],
    "Transport": ["uber ride", "ola cab", "metro card recharge", "petrol pump", "fuel station",
                  "irctc train ticket", "rapido bike", "bus pass", "parking fee", "toll plaza",
                  "indigo airlines flight", "redbus ticket", "shell fuel"],
    "Shopping": ["amazon purchase", "flipkart order", "myntra clothing", "nike shoes", "ikea furniture",
                 "zara apparel", "ebay order", "croma electronics", "decathlon sports", "h&m fashion",
                 "walmart", "meesho order"],
    "Bills": ["electricity bill", "water bill", "mobile recharge", "broadband internet bill",
              "airtel postpaid", "jio fiber", "gas cylinder", "house rent", "insurance premium",
              "property tax", "emi loan payment", "vodafone bill", "dth recharge"],
    "Entertainment": ["netflix subscription", "spotify premium", "prime video", "disney hotstar",
                      "bookmyshow movie", "youtube premium", "steam games", "playstation store",
                      "apple music", "concert tickets", "pvr cinemas", "xbox game pass"],
    "Health": ["apollo pharmacy", "doctor consultation", "gym membership", "cult fit", "hospital bill",
               "dental clinic", "medplus medicines", "lab test", "yoga class", "1mg medicine"],
    "Education": ["udemy course", "coursera subscription", "college fees", "textbook store",
                  "exam registration", "coaching class", "kindle ebook", "linkedin learning",
                  "tuition fee", "stationery"],
    "Other": ["atm withdrawal", "miscellaneous", "gift", "donation charity", "bank charges",
              "cash payment", "unknown transfer", "service fee"],
}


PRODUCTION_VARIANT = "union"  # chosen by ml/evaluate.py: best merchant-held-out score


def _seed_data():
    from .dataset import generate
    X, y = [], []
    for cat, items in SEED.items():
        for item in items:
            X.append(normalize_merchant(item))
            y.append(cat)
    for row in generate():
        X.append(normalize_merchant(row["description"]))
        y.append(row["category"])
    return X, y


def make_pipeline(variant=PRODUCTION_VARIANT):
    """Untrained classifier pipeline. Shared with ml/evaluate.py so the report measures what runs in production."""
    if variant == "union":
        from sklearn.pipeline import FeatureUnion
        feats = FeatureUnion([
            ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)),
        ])
        return make_pipeline_from(feats)
    return make_pipeline_from(TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True))


def make_pipeline_from(features):
    from sklearn.pipeline import Pipeline
    return Pipeline([("features", features), ("clf", LogisticRegression(max_iter=2000, C=10))])


@lru_cache(maxsize=64)
def _build(extra):
    X, y = _seed_data()
    for desc, cat in extra:
        if cat in CATEGORIES:
            # weight user feedback by repeating it
            X.extend([normalize_merchant(desc)] * 3)
            y.extend([cat] * 3)
    model = make_pipeline()
    model.fit(X, y)
    return model


def build_model(extra=None):
    """extra: iterable of (description, category) confirmed by the user.

    Models are cached by their training extras, so the (slow) base training
    happens once per process and users without corrections share one model.
    """
    return _build(tuple(sorted({(d, c) for d, c in (extra or [])})))


def predict(model, descriptions, min_confidence=0.2):
    """Return a category per description; low-confidence guesses become 'Other'."""
    if not descriptions:
        return []
    probs = model.predict_proba([normalize_merchant(d) for d in descriptions])
    classes = model.classes_
    out = []
    for p in probs:
        i = int(np.argmax(p))
        out.append(classes[i] if p[i] >= min_confidence else "Other")
    return out


LOW_CONFIDENCE = 0.5  # below this, predictions were right only ~half the time (see docs/CATEGORIZER_EVALUATION.md)


def predict_with_confidence(model, descriptions):
    """Return [(category, confidence 0-1)] using the same fallback to 'Other' as predict()."""
    if not descriptions:
        return []
    probs = model.predict_proba([normalize_merchant(d) for d in descriptions])
    out = []
    for p in probs:
        i = int(np.argmax(p))
        out.append((model.classes_[i] if p[i] >= 0.2 else "Other", float(p[i])))
    return out
