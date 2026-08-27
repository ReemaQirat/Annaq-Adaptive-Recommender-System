"""
preference_vector.py — تحويل تفضيلات الزائر إلى متجه رقمي
============================================================

وظيفة الملف:
    يحوّل تفضيلات الزائر (نوع المكان، الميزانية، الجو، إلخ) من dict عربي
    إلى numpy array بـ 36 بُعد (27 ميزة + 2 جنس + 7 تعبير وجه).
    هذا الـ vector هو "الـ context" اللي يستخدمه LinUCB لاختيار التوصيات.

شرح الخوارزمية:
    - One-hot encoding: لكل ميزة فئوية (مثل primary_type)، فقط الـ index
      المناسب يصير 1.0 والباقي 0.0
    - الميزات (27 بُعد الأساسية):
        [0-5]  نوع المكان: attraction, restaurant, cafe, mall, park, religious
        [6-9]  الميزانية: low, medium, high, luxury
        [10]   مناسب للعائلات (boolean)
        [11-12] داخلي / خارجي
        [13-20] نوع المطبخ (سعودي، لبناني، أمريكي، إلخ)
        [21-23] أفضل وقت: صباح، مساء، أي وقت
        [24]   حساس للطقس
        [25]   التقييم (مُطبَّع 0-1)
        [26]   المدة (مُطبَّعة)
    - الميزات الإضافية (9 بُعد):
        [27-28] الجنس: ذكر / أنثى
        [29-35] تعبير الوجه: happy/neutral/sad/surprised/bored/angry/other

المكتبات المطلوبة:
    pip install numpy
"""

import numpy as np

# ============================================================
# Feature names (27 base features)
# ============================================================
BASE_FEATURES = [
    # Type (0-5)
    'type_attraction', 'type_restaurant', 'type_cafe', 'type_mall', 'type_park', 'type_religious',
    # Budget (6-9)
    'budget_low', 'budget_medium', 'budget_high', 'budget_luxury',
    # Family friendly (10)
    'family_friendly',
    # Indoor/Outdoor (11-12)
    'indoor', 'outdoor',
    # Cuisine (13-20)
    'cuisine_saudi', 'cuisine_lebanese', 'cuisine_american', 'cuisine_seafood',
    'cuisine_italian', 'cuisine_japanese', 'cuisine_turkish', 'cuisine_none',
    # Best time (21-23)
    'time_morning', 'time_evening', 'time_anytime',
    # Weather sensitive (24)
    'weather_sensitive',
    # Rating norm (25)
    'rating_norm',
    # Duration norm (26)
    'duration_norm'
]

# Helper: create mapping from short value to index
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

def preferences_to_vector(prefs, gender=None, expression=None):
    """
    prefs: dict with keys:
        primary_type, budget, family_friendly, indoor_outdoor,
        cuisine, best_time, weather_sensitive_ok
    gender: 'male', 'female', or None
    expression: string from set {'happy','neutral','sad','surprised','bored','angry','other'}
    Returns 36-dim numpy array.
    """
    # 1. Base 27 features (all zeros)
    vec = [0.0] * 27

    # Primary type
    if 'primary_type' in prefs:
        t = prefs['primary_type']
        if t in TYPE_MAP:
            vec[TYPE_MAP[t]] = 1.0

    # Budget
    if 'budget' in prefs:
        b = prefs['budget']
        if b in BUDGET_MAP:
            vec[BUDGET_MAP[b]] = 1.0

    # Family friendly
    if prefs.get('family_friendly'):
        vec[10] = 1.0

    # Indoor/outdoor
    io = prefs.get('indoor_outdoor', 'either')
    if io == 'indoor':
        vec[11] = 1.0
    elif io == 'outdoor':
        vec[12] = 1.0

    # Cuisine
    if 'cuisine' in prefs:
        c = prefs['cuisine']
        if c in CUISINE_MAP:
            vec[CUISINE_MAP[c]] = 1.0
        else:
            vec[20] = 1.0   # cuisine_none

    # Best time
    if 'best_time' in prefs:
        tm = prefs['best_time']
        if tm in TIME_MAP:
            vec[TIME_MAP[tm]] = 1.0
        else:
            vec[23] = 1.0   # time_anytime

    # Weather sensitive ok
    if prefs.get('weather_sensitive_ok'):
        vec[24] = 1.0

    # rating_norm and duration_norm remain 0 (user does not specify)

    # 2. Append gender features (2)
    if gender == 'male':
        vec.extend([1.0, 0.0])
    elif gender == 'female':
        vec.extend([0.0, 1.0])
    else:
        vec.extend([0.0, 0.0])

    # 3. Append expression features (7)
    expr_order = ['happy', 'neutral', 'sad', 'surprised', 'bored', 'angry', 'other']
    expr_vec = [0.0] * 7
    if expression in expr_order:
        expr_vec[expr_order.index(expression)] = 1.0
    vec.extend(expr_vec)

    return np.array(vec, dtype=np.float32)


if __name__ == '__main__':
    # Test with a realistic preference dictionary
    test_prefs = {
        'primary_type': 'restaurant',
        'budget': 'low',
        'family_friendly': True,
        'indoor_outdoor': 'indoor',
        'cuisine': 'saudi',
        'best_time': 'evening',
        'weather_sensitive_ok': False
    }
    gender = 'female'
    expression = 'happy'

    vec = preferences_to_vector(test_prefs, gender, expression)
    print("Vector shape:", vec.shape)
    print("First 27 base features:")
    for i, val in enumerate(vec[:27]):
        if val != 0:
            print(f"  Index {i} ({BASE_FEATURES[i]}) = {val}")
    print("\nGender features (indices 27-28):", vec[27:29])
    print("Expression features (indices 29-35):", vec[29:36])