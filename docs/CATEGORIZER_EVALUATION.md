# Categorizer evaluation

Generated 2026-11-14 by `python -m app.ml.evaluate` (random seed 42). All numbers below are measured, not estimated.

## What was evaluated

- **Task:** assign one of 8 spending categories (Food, Transport, Shopping, Bills, Entertainment, Health, Education, Other) to a bank-statement description.
- **Data:** 1344 labeled descriptions from 192 merchants, **synthetically generated** by `app/ml/dataset.py` (merchant names combined with UPI/POS/NEFT/IMPS-style templates, reference numbers, cities and optional hint words).
- **Pre-processing:** lower-casing, removal of digits/punctuation and bank noise words (UPI, NEFT, POS, ...).
- **Production model:** Word+Char TF-IDF + Logistic Regression.

## Two ways of splitting the data

1. **Random 5-fold (stratified).** The same merchant can appear in training and test folds. This is optimistic: it measures how well the model recognises merchants it has already seen.
2. **Merchant-held-out 5-fold (StratifiedGroupKFold).** Every merchant in a test fold is completely unseen during training. This is the realistic estimate for a brand-new merchant and the number to quote.

## Headline results (production model)

| Protocol | Accuracy | Macro precision | Macro recall | Macro F1 |
|---|---|---|---|---|
| Random 5-fold | 100.0% | 100.0% | 100.0% | 100.0% |
| Merchant-held-out 5-fold | 52.2% | 52.5% | 52.2% | 52.2% |

## Model comparison

| Model | Random acc. | Random macro-F1 | Held-out acc. | Held-out macro-F1 |
|---|---|---|---|---|
| Word+Char TF-IDF + Logistic Regression **(production)** | 100.0% | 100.0% | 52.2% | 52.2% |
| Char TF-IDF + Logistic Regression | 100.0% | 100.0% | 49.9% | 49.1% |
| Char TF-IDF + Linear SVM | 100.0% | 100.0% | 49.9% | 48.9% |
| Word TF-IDF + Naive Bayes | 99.5% | 99.5% | 43.8% | 43.6% |
| Majority class (baseline) | 12.3% | 8.0% | 10.4% | 8.0% |

The majority-class row is the do-nothing baseline: always predicting the most common category.

## Per-category results (merchant-held-out)

| Category | Precision | Recall | F1 | Samples |
|---|---|---|---|---|
| Food | 39.7% | 36.9% | 38.3% | 168 |
| Transport | 50.0% | 53.0% | 51.4% | 168 |
| Shopping | 32.6% | 37.5% | 34.9% | 168 |
| Bills | 38.0% | 37.5% | 37.7% | 168 |
| Entertainment | 58.2% | 48.8% | 53.1% | 168 |
| Health | 68.5% | 72.6% | 70.5% | 168 |
| Education | 64.3% | 65.5% | 64.9% | 168 |
| Other | 68.3% | 65.5% | 66.9% | 168 |

## Confusion matrix (merchant-held-out; rows = true, columns = predicted)

| true \ pred | Food | Transport | Shopping | Bills | Entertainment | Health | Education | Other |
|---|---|---|---|---|---|---|---|---|
| **Food** | 62 | 32 | 23 | 13 | 8 | 3 | 9 | 18 |
| **Transport** | 17 | 89 | 31 | 18 | 1 | 10 | 0 | 2 |
| **Shopping** | 17 | 17 | 63 | 29 | 15 | 12 | 12 | 3 |
| **Bills** | 15 | 7 | 27 | 63 | 20 | 22 | 7 | 7 |
| **Entertainment** | 9 | 4 | 30 | 24 | 82 | 3 | 12 | 4 |
| **Health** | 11 | 12 | 2 | 6 | 8 | 122 | 1 | 6 |
| **Education** | 7 | 10 | 14 | 13 | 1 | 2 | 110 | 11 |
| **Other** | 18 | 7 | 3 | 0 | 6 | 4 | 20 | 110 |

## Why held-out accuracy is lower, and what helps

A merchant name such as "Swiggy" carries no category information unless the model has seen it. For brand-new merchants the model can only rely on descriptive words in the narration ("pharmacy", "fuel", "cafe"...).

| Held-out rows | Samples | Accuracy |
|---|---|---|
| Description contains a category hint word | 333 | 88.9% |
| Merchant name only | 1011 | 40.1% |

Accuracy when the model is confident (merchant-held-out):

| Minimum confidence | Share of transactions kept | Accuracy on those |
|---|---|---|
| 0.0 | 100.0% | 52.2% |
| 0.3 | 66.3% | 69.4% |
| 0.5 | 40.2% | 83.2% |
| 0.7 | 24.5% | 86.3% |

Practical consequences for the app: (1) known merchants are categorised almost perfectly; (2) unfamiliar ones are right about half the time, so users should review them in the preview and correct mistakes, after which the same merchant is recognised from then on; (3) low-confidence predictions are the least reliable and are the ones to check first.

## Limitations (please read)

- The data is synthetic. Real statements have messier, shorter and more ambiguous narrations, so **real-world accuracy can be lower**. Measure on your own labeled transactions before relying on these numbers.
- Merchants and templates were written by the developer, so the test set shares style with the training set even when merchants are held out.
- "Other" is a catch-all and is intrinsically the hardest category.
- The app improves with use: when a user corrects a category, that example is added (with extra weight) to that user's model. This effect is not included in the numbers above.
- Model choice was made by comparing the same cross-validation scores shown here, so the headline numbers are slightly optimistic.

## Reproduce

```bash
python -m app.ml.evaluate
```
