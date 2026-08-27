"""
main_recommender.py — اختبار يدوي لنظام التوصيات (للتطوير فقط)
================================================================

وظيفة الملف:
    سكربت اختبار يدوي لخوارزمية LinUCB. يحاكي زائر بمواصفات معيّنة
    ويعرض أعلى ٥ توصيات. مفيد لتجربة الخوارزمية بدون تشغيل السيرفر كامل.

    ⚠️ هذا الملف للاختبار التطويري فقط — التطبيق الفعلي يستخدم
    annaq_agent.py الذي يدمج الـ recommender مع الـ LLM.

طريقة التشغيل:
    cd recommender
    python main_recommender.py

المكتبات المطلوبة:
    pip install numpy
"""

import numpy as np
import pickle
import os
from preference_vector import preferences_to_vector
from linucb import LinUCB
from place_vector import load_places_with_vectors

#الملف هذا للاختبار فقط ما احتاجه في النتيجة النهائية

def main():
    # 1. Load places and their vectors
    place_ids, place_names, place_vectors_27, place_vectors_36 = load_places_with_vectors('places.csv')
    n_arms = len(place_ids)
    n_features = 36

    # 2. Load or initialise bandit with warm start (using padded place vectors)
    model_file = 'bandit_model.pkl'
    if os.path.exists(model_file):
        with open(model_file, 'rb') as f:
            bandit = pickle.load(f)
        print("Loaded existing bandit model.")
    else:
        # Warm start: pass place_vectors_36 (each is 36‑dim, last 9 zeros)
        bandit = LinUCB(n_arms, n_features, alpha=1.0, arm_features=place_vectors_36, beta=0.5)
        print("Initialized new bandit model with warm start and hybrid scoring (beta=0.5).")

    # 3. Simulate a user (replace with real conversation later)
    prefs = {
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

    context = preferences_to_vector(prefs, gender, expression)
    print("Context vector (first 10):", context[:10])

    # 4. Get recommendations
    arm_indices, scores = bandit.get_recommendations(context, top_k=5)
    print("\nTop 5 recommendations:")
    for i, (arm_idx, score) in enumerate(zip(arm_indices, scores)):
        place_id = place_ids[arm_idx]
        name = place_names[place_id]
        print(f"{i+1}. {name} ({place_id}) - score: {score:.4f}")

    # 5. Simulate user feedback
    choice = input("\nWhich place did the user like? (1-5, or 0 for none): ")
    try:
        choice = int(choice)
    except:
        choice = 0

    if 1 <= choice <= 5:
        chosen_arm = arm_indices[choice-1]
        reward = 1.0
        bandit.update(chosen_arm, context, reward)
        print(f"Updated arm {chosen_arm} with reward 1.")
    else:
        print("No update.")

    # 6. Save model
    with open(model_file, 'wb') as f:
        pickle.dump(bandit, f)
    print("Model saved.")

if __name__ == '__main__':
    main()