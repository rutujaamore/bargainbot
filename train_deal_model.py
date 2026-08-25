"""
Trains the "Deal Score" model - answers: is this live price good compared
to what similar products in this category typically cost?

Why this design
----------------
Our live scraper only gets a product's title and price - no discount %,
no MRP, no rating. So the only thing we can realistically feed the model
at prediction time is the product's CATEGORY (guessed from its title).
That means the honest, correct model here is: "what's the typical price
for this category, based on real data?" - not a fake absolute price
forecast.

We use scikit-learn's LinearRegression with one-hot encoded category as
input and log(price) as the target. With fit_intercept=False, each
category's coefficient IS simply that category's average log-price - so
this is mathematically equivalent to "the average price per category,"
but it's a genuine trained sklearn model, and this same structure could
take on more features later without changing the approach.

Three real data sources, combined
----------------------------------
The original Amazon dataset is dominated by cheap accessories (₹100s),
so real phones and laptops always looked "impossibly expensive" against
it and got flagged as low-confidence. Rather than force those into a
category the data doesn't support, we add two DEDICATED datasets with
real price ranges for those product types:
  - amazon_raw.csv    -> general accessories/electronics/kitchen (as before)
  - mobiles_raw.csv    -> real 2025 phone prices (₹8k - ₹2L+ range)
  - laptop_raw.csv     -> real laptop prices (₹9k - ₹3L+ range)

Since fit_intercept=False and every category is a separate one-hot
column, combining these into one fit is mathematically identical to
training each category separately - categories don't influence each
other's numbers, so mixing three files is safe.

We only trust categories with enough real samples (30+ rows). Categories
with 1-2 rows get merged into "Other" - training on 1 data point and
pretending it's reliable would be dishonest.
"""

import json
import os
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MODEL_PATH = os.path.join(os.path.dirname(__file__), "deal_model.json")

MIN_SAMPLES_TO_TRUST = 30  # categories below this get folded into "Other"


def load_amazon():
    """General accessories/electronics/kitchen - the original dataset.

    IMPORTANT REFINEMENT: the raw "Electronics" bucket used to lump TVs,
    smartwatches, earbuds, cameras and speakers into ONE typical price
    (dominated by ~Rs.200 earbuds) - so a real Rs.17,000 TV looked
    "wildly overpriced" even at a completely normal price. The dataset's
    own category path is more specific than that (e.g.
    "Electronics|HomeTheater,TV&Video|Televisions|SmartTelevisions").
    We now pull out three sub-categories that individually have 60+ real
    samples - enough to trust on their own, same bar used for
    Mobiles/Laptops - and only fall back to the broad "Electronics"
    label for products that don't have their own well-sampled bucket
    (cameras, speakers, tablets: too few real rows to trust separately).
    """
    az = pd.read_csv(os.path.join(DATA_DIR, "amazon_raw.csv"))
    az["price"] = (
        az["discounted_price"].str.replace("₹", "").str.replace(",", "").astype(float)
    )

    parts = az["category"].str.split("|")
    lvl1 = parts.str[0]
    lvl2 = parts.str[1]
    lvl3 = parts.str[2]

    # Only split out sub-categories we've verified have enough real rows
    # (checked against MIN_SAMPLES_TO_TRUST before wiring this in - see
    # train_deal_model.py history/README for the counts).
    main_category = lvl1.copy()
    main_category = main_category.where(lvl3 != "Televisions", "Televisions")
    main_category = main_category.where(lvl2 != "WearableTechnology", "Wearables")
    main_category = main_category.where(
        lvl2 != "Headphones,Earbuds&Accessories", "Headphones&Earbuds"
    )

    az["main_category"] = main_category
    return az[["price", "main_category"]]


def load_mobiles():
    """Real 2025 phone prices - dedicated dataset so phones stop being
    judged against ₹200 cables."""
    mob = pd.read_csv(os.path.join(DATA_DIR, "mobiles_raw.csv"), encoding="latin-1")
    mob["price"] = (
        mob["Launched Price (India)"]
        .str.replace("INR ", "", regex=False)
        .str.replace(",", "")
        .astype(float)
    )
    mob["main_category"] = "Mobiles"
    return mob[["price", "main_category"]]


def load_laptops():
    """Real laptop prices - dedicated dataset, same reasoning as mobiles."""
    lap = pd.read_csv(os.path.join(DATA_DIR, "laptop_raw.csv"))
    lap["price"] = lap["Price"].astype(float)
    lap["main_category"] = "Laptops"
    return lap[["price", "main_category"]]


def load_and_clean():
    combined = pd.concat([load_amazon(), load_mobiles(), load_laptops()], ignore_index=True)

    # Drop non-positive/missing prices (shouldn't exist, but real data
    # can surprise you)
    combined = combined[combined["price"] > 0].dropna(subset=["price", "main_category"])

    counts = combined["main_category"].value_counts()
    trusted_categories = counts[counts >= MIN_SAMPLES_TO_TRUST].index.tolist()
    combined["model_category"] = combined["main_category"].where(
        combined["main_category"].isin(trusted_categories), "Other"
    )

    return combined, trusted_categories


def train():
    data, trusted_categories = load_and_clean()

    data["log_price"] = np.log(data["price"])
    dummies = pd.get_dummies(data["model_category"])
    X = dummies.values.astype(float)
    y = data["log_price"].values

    model = LinearRegression(fit_intercept=False)
    model.fit(X, y)

    predictions = model.predict(X)
    residuals = y - predictions

    # Per-category spread (std of residuals within that category) - needed
    # to turn "how far from typical" into a 0-100 score later.
    data["residual"] = residuals
    category_std = data.groupby("model_category")["residual"].std().to_dict()

    category_stats = {}
    for i, cat in enumerate(dummies.columns):
        cat_prices = data.loc[data["model_category"] == cat, "price"]
        category_stats[cat] = {
            "log_mean_price": float(model.coef_[i]),
            "typical_price": float(np.exp(model.coef_[i])),
            "std": float(category_std.get(cat, 0.5)) or 0.5,  # avoid 0-std edge case
            "sample_count": int((data["model_category"] == cat).sum()),
            "min_price": float(cat_prices.min()),
            "max_price": float(cat_prices.max()),
        }

    with open(MODEL_PATH, "w") as f:
        json.dump({
            "categories": category_stats,
            "trusted_categories": trusted_categories,
        }, f, indent=2)

    print(f"Trained on {len(data)} real product rows across 3 datasets.")
    print(f"Categories kept separate: {trusted_categories}")
    print(f"Everything else merged into 'Other'.")
    print()
    print("Learned typical price per category:")
    for cat, stats in sorted(category_stats.items(), key=lambda x: -x[1]["typical_price"]):
        print(f"  {cat:25s} typical ₹{stats['typical_price']:>9,.0f}   "
              f"(n={stats['sample_count']}, range ₹{stats['min_price']:,.0f}-₹{stats['max_price']:,.0f})")
    print()
    print(f"Saved model to {MODEL_PATH}")


if __name__ == "__main__":
    train()
