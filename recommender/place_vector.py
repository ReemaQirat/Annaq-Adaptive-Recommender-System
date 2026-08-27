"""
place_vector.py — تحويل بيانات الأماكن إلى متجهات رقمية
==========================================================

وظيفة الملف:
    يقرأ ملف places.csv ويحوّل كل مكان إلى متجه 27 بُعد (مطابق
    لتفضيلات الزائر في preference_vector.py). هذي المتجهات تُستخدم لـ:
    1. Warm start للبانديت (يبدأ بمعرفة عن كل مكان قبل أي feedback)
    2. Static similarity في hybrid scoring (مطابقة سياق ↔ ميزات المكان)

شرح الخوارزمية:
    - نفس الـ encoding المستخدم في preference_vector.py (نفس الـ indices)
      → كذا dot product بين user_context و place_vector يعطي قياس تشابه طبيعي
    - لكل مكان نملأ ميزاته من CSV: type, budget, family_friendly, إلخ
    - rating و duration نُطبّعهم على [0, 1] قبل الحفظ
    - نخلق نسختين:
        - 27-dim: للـ static similarity في الـ scoring
        - 36-dim: للـ warm start (نضيف 9 أصفار للجنس + تعبير الوجه)

المكتبات المطلوبة:
    pip install numpy
"""

import csv
import numpy as np

# Same mappings as in preference_vector.py (first 27 indices)
TYPE_MAP = {
    'attraction': 0,
    'restaurant': 1,
    'cafe': 2,
    'mall': 3,
    'park': 4,
    'religious': 5
}
BUDGET_MAP = {
    'low': 6,
    'medium': 7,
    'high': 8,
    'luxury': 9
}
CUISINE_MAP = {
    'saudi': 13,
    'lebanese': 14,
    'american': 15,
    'seafood': 16,
    'italian': 17,
    'japanese': 18,
    'turkish': 19,
    'none': 20
}
TIME_MAP = {
    'morning': 21,
    'evening': 22,
    'anytime': 23
}

def place_to_vector(row):
    """Convert a CSV row (dict) to a 27‑dim feature vector."""
    vec = [0.0] * 27

    # Primary type
    ptype = row['primary_type']
    if ptype in TYPE_MAP:
        vec[TYPE_MAP[ptype]] = 1.0

    # Budget
    budget = row['budget']
    if budget in BUDGET_MAP:
        vec[BUDGET_MAP[budget]] = 1.0

    # Family friendly
    if row['family_friendly'] == 'yes':
        vec[10] = 1.0

    # Indoor/outdoor
    io = row['indoor_outdoor']
    if io == 'indoor':
        vec[11] = 1.0
    elif io == 'outdoor':
        vec[12] = 1.0

    # Cuisine
    cuisine = row.get('cuisine_type', 'none')
    if cuisine in CUISINE_MAP:
        vec[CUISINE_MAP[cuisine]] = 1.0
    else:
        vec[CUISINE_MAP['none']] = 1.0

    # Best time
    best_time = row.get('best_time_of_day', 'anytime')
    if best_time in TIME_MAP:
        vec[TIME_MAP[best_time]] = 1.0
    else:
        vec[TIME_MAP['anytime']] = 1.0

    # Weather sensitive
    if row['weather_sensitive'] == 'yes':
        vec[24] = 1.0

    # Rating norm
    try:
        rating = float(row['rating']) if row['rating'] else 3.0
    except:
        rating = 3.0
    vec[25] = rating / 5.0

    # Duration norm
    try:
        duration = float(row['duration_hours']) if row['duration_hours'] else 2.0
    except:
        duration = 2.0
    vec[26] = min(duration / 8.0, 1.0)

    return np.array(vec, dtype=np.float32)

def load_places_with_vectors(csv_path='places.csv'):
    """
    Returns:
        place_ids: list of place_id strings
        place_names: dict {place_id: name_ar}
        place_vectors_27: list of 27‑dim numpy arrays (order matches place_ids)
        place_vectors_36: list of 36‑dim numpy arrays (27 + 9 zeros)
    """
    place_ids = []
    place_names = {}
    place_vectors_27 = []
    place_vectors_36 = []

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row['place_id']
            name = row['name_ar']
            place_ids.append(pid)
            place_names[pid] = name
            vec27 = place_to_vector(row)
            place_vectors_27.append(vec27)
            # Pad to 36 with zeros (for gender/expression)
            vec36 = np.zeros(36, dtype=np.float32)
            vec36[:27] = vec27
            place_vectors_36.append(vec36)

    return place_ids, place_names, place_vectors_27, place_vectors_36

if __name__ == '__main__':
    ids, names, v27, v36 = load_places_with_vectors('places.csv')
    print(f"Loaded {len(ids)} places.")
    print("First place:", ids[0], names[ids[0]])
    print("27‑dim vector:", v27[0][:5], "...")
    print("36‑dim vector (padded):", v36[0][:5], "... (last 9 are zeros)")