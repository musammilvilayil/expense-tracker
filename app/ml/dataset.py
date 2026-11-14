"""Synthetic labeled bank-style transactions for training and evaluating the categorizer.

IMPORTANT: this data is generated, not collected from real customers. Each
merchant is combined with common bank narration templates (UPI/POS/NEFT...),
reference numbers, cities and optional hint words. It is realistic in *form*,
but real-world accuracy must still be checked on real transactions.
"""
import random

MERCHANTS = {
    "Food": ["swiggy", "zomato", "dominos pizza", "mcdonalds", "kfc", "starbucks", "cafe coffee day", "burger king", "subway",
             "pizza hut", "bigbasket", "blinkit", "zepto", "haldirams", "barbeque nation", "chai point", "faasos", "dunzo",
             "reliance fresh", "dmart", "more supermarket", "ubereats", "behrouz biryani", "baskin robbins"],
    "Transport": ["uber", "ola cabs", "rapido", "irctc", "redbus", "indigo airlines", "air india", "makemytrip", "indian oil",
                  "hp petrol pump", "bharat petroleum", "shell fuel", "fastag", "delhi metro", "bmtc bus", "abhibus",
                  "goibibo", "yulu bikes", "spicejet", "vistara", "parking plaza", "namma yatri", "blu smart", "cleartrip"],
    "Shopping": ["amazon", "flipkart", "myntra", "ajio", "nykaa", "meesho", "croma", "reliance digital", "decathlon", "ikea",
                 "zara", "h and m", "lifestyle stores", "shoppers stop", "westside", "pantaloons", "tata cliq", "snapdeal",
                 "lenskart", "firstcry", "pepperfry", "uniqlo", "bata shoes", "titan watches"],
    "Bills": ["bescom electricity", "tata power", "adani electricity", "airtel", "jio", "vodafone idea", "bsnl", "act fibernet",
              "hathway broadband", "tata sky", "dish tv", "indane gas", "lic premium", "hdfc life", "icici lombard",
              "bajaj finserv emi", "house rent", "water board", "municipal tax", "star health insurance", "sun direct",
              "mahanagar gas", "piped gas", "maintenance charges"],
    "Entertainment": ["netflix", "spotify", "amazon prime video", "disney hotstar", "youtube premium", "bookmyshow", "pvr cinemas",
                      "inox movies", "sony liv", "zee5", "apple music", "steam games", "playstation store", "xbox game pass",
                      "gaana", "jiocinema", "audible", "nintendo eshop", "wynk music", "epic games", "twitch", "paytm insider",
                      "dream11", "bowling arcade"],
    "Health": ["apollo pharmacy", "medplus", "netmeds", "pharmeasy", "1mg", "practo", "fortis hospital", "max healthcare",
               "manipal hospital", "cult fit", "gold gym", "anytime fitness", "dr lal pathlabs", "thyrocare", "dental clinic",
               "eye care centre", "wellness forever", "healthkart", "aster clinic", "narayana health", "yoga studio",
               "cure fit", "tata 1mg", "diagnostic centre"],
    "Education": ["udemy", "coursera", "byjus", "unacademy", "vedantu", "upgrad", "simplilearn", "linkedin learning", "skillshare",
                  "college tuition", "university fees", "exam registration", "crossword books", "kindle books", "toppr",
                  "great learning", "edx", "pluralsight", "school fees", "coding bootcamp", "cbse board", "ielts registration",
                  "stationery mart", "duolingo"],
    "Other": ["atm cash withdrawal", "bank service charge", "annual card fee", "sms alert charges", "donation", "ngo contribution",
              "temple trust", "gift voucher", "self transfer", "cash payment", "cheque issued", "miscellaneous", "late payment fee",
              "gst charges", "forex markup", "greeting cards", "postal services", "courier charges", "notary fees",
              "unknown merchant", "wedding gift", "charity fund", "stamp duty", "convenience fee"],
}

HINTS = {
    "Food": ["restaurant", "foods", "cafe", "kitchen", "dining"], "Transport": ["ride", "travels", "fuel", "ticket", "cab"],
    "Shopping": ["store", "retail", "fashion", "mart", "online"], "Bills": ["bill", "recharge", "premium", "emi", "dues"],
    "Entertainment": ["premium", "movies", "tickets", "subscription", "games"], "Health": ["pharmacy", "clinic", "hospital", "labs", "care"],
    "Education": ["course", "fees", "academy", "learning", "class"], "Other": ["charges", "fee", "misc", "transfer", "payment"],
}
CITIES = ["mumbai", "bangalore", "delhi", "chennai", "pune", "hyderabad", "kolkata", "gurgaon", "noida", "kochi"]
HANDLES = ["okaxis", "oksbi", "okicici", "okhdfcbank", "ybl", "paytm"]
TEMPLATES = [
    "{m}", "{M}", "UPI/{M}/{ref}", "UPI-{M}-{ref}@{h}", "POS {num} {M} {city}", "{M} {city}", "NEFT-{M}-{ref}",
    "IMPS/{ref}/{M}", "CARD PAYMENT {M} {city}", "ACH D- {M}-{ref}", "{M} ONLINE {ref}", "PAYTM-{M}", "{m} order {n}",
    "UPI/{ref}/{M}/PAYMENT", "BILLDESK {M}", "VPS*{M} {city}",
]


def generate(per_merchant=7, seed=7):
    """Return a list of dicts: description, category, merchant, hinted (has a category hint word). Deterministic for a given seed."""
    rng = random.Random(seed)
    rows = []
    for cat, merchants in MERCHANTS.items():
        for m in merchants:
            for _ in range(per_merchant):
                name, hinted = m, False
                if rng.random() < 0.25:
                    name, hinted = f"{m} {rng.choice(HINTS[cat])}", True
                text = rng.choice(TEMPLATES).format(
                    m=name, M=name.upper(), ref=rng.randint(10**8, 10**11), num=rng.randint(1000, 9999),
                    city=rng.choice(CITIES).upper(), n=rng.randint(100, 99999), h=rng.choice(HANDLES))
                rows.append({"description": text, "category": cat, "merchant": m, "hinted": hinted})
    return rows
