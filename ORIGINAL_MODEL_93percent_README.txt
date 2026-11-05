⭐ ORIGINAL MODEL FILE — GUIDE (93.6% accuracy)
=====================================================================

ORIGINAL / PUSH KARNE WALI FILES (naam change na karein —
web app inhi exact naamon se model load karta hai):

  delivery_time_model.pkl      <-- ASLI ORIGINAL (R² = 0.936 ≈ 94%)
      • Model: HistGradientBoostingRegressor (scikit-learn)
      • Trained: 2026-11-04, scripts/train_model.py
      • Data: data/ml/delivery_time_dataset.csv (13,314 orders)
      • Accuracy: MAE ~3.4 min | 96% ETAs ±10 min | R² 0.936
      • Size ~791 KB, date 04-Nov-2026 (nayi)

  model_features.pkl           <-- ORIGINAL feature list
      • delivery_time_model.pkl ke sath wali (same date/time)

NOT ORIGINAL / PUSH NA KREIN (.bak = purane 75% accuracy backups):

  delivery_time_model.pkl.bak      (1,887 KB, Oct 30 — purana model)
  model_features.pkl.bak           (Oct 30 — purani feature list)

  .gitignore in dono .bak files ko skip kar raha hai, is liye
  GitHub repo mein yeh nahi jayengi. App in files ka kuch
  istemaal nahi karta — sirf safety copies hain.

ZAROORI NOTE:
  delivery_time_model.pkl ka naam kabhi change na karein.
  ml/predictor.py bilkul yehi naam expect karta hai:
  MODEL_PATH = <project root>/delivery_time_model.pkl
=====================================================================
