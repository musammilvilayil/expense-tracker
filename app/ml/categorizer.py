"""AI/ML expense categorisation: TF-IDF + logistic regression.

Trained on a built-in seed set plus any categories the user has confirmed.
"""
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

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


def _seed_data():
    X, y = [], []
    for cat, items in SEED.items():
        for item in items:
            X.append(normalize_merchant(item))
            y.append(cat)
    return X, y


def build_model(extra=None):
    """extra: iterable of (description, category) confirmed by the user."""
    X, y = _seed_data()
    for desc, cat in extra or []:
        if cat in CATEGORIES:
            # weight user feedback by repeating it
            X.extend([normalize_merchant(desc)] * 3)
            y.extend([cat] * 3)
    model = make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True),
        LogisticRegression(max_iter=1000, C=10),
    )
    model.fit(X, y)
    return model


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
