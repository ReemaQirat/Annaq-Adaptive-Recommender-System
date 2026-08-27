"""
linucb.py — خوارزمية LinUCB Bandit للتوصيات
==============================================

وظيفة الملف:
    تنفيذ خوارزمية Linear Upper Confidence Bound (LinUCB) — وحدة من خوارزميات
    الـ Contextual Bandit المستخدمة في أنظمة التوصية. تتعلم من التفاعل
    وتختار أفضل arm (مكان) لكل context (سياق الزائر).

شرح الخوارزمية:
    - كل "arm" = مكان (٢٠٠ مكان عندنا)
    - كل "context" = vector 36 بُعد يصف تفضيلات الزائر الحالية
    - لكل arm نحفظ: مصفوفة A (covariance) ومتجه b (reward-weighted features)
    - الاختيار: نحسب UCB score = mean + alpha × sqrt(uncertainty)
      → mean: المكافأة المتوقعة (theta · context)
      → uncertainty: مدى الثقة في التقدير (يقلّ كلما تعلّمنا أكثر)
    - alpha يحدد توازن exploration vs exploitation:
      → alpha صغير: نختار اللي نعرف يعجبه (exploit)
      → alpha كبير: نجرّب أماكن جديدة (explore)

التحسينات الخاصة بنا:
    - Warm start: نهيّء b بمتجهات الأماكن الفعلية (ما نبدأ من صفر)
    - Hybrid scoring: نضيف static similarity مع الـ UCB (beta × dot product)
      → يعطي نتائج معقولة من البداية حتى قبل ما نتعلم

المكتبات المطلوبة:
    pip install numpy
"""

import numpy as np

class LinUCB:
    def __init__(self, n_arms, n_features, alpha=1.0, arm_features=None, beta=0.5):
        """
        n_arms: number of places
        n_features: dimension of context (36)
        alpha: exploration parameter
        arm_features: list of 36‑dim numpy arrays (one per arm), used for warm start
        beta: weight for static similarity in hybrid scoring (0 = pure bandit, 1 = pure static)
        """
        self.n_arms = n_arms
        self.n_features = n_features
        self.alpha = alpha
        self.beta = beta
        self.A = [np.identity(n_features) for _ in range(n_arms)]
        if arm_features is not None:
            # Warm start: set b = arm_feature (scaled by beta? No, we set b = arm_feature * 1.0)
            # This gives a prior that the arm is good for contexts that match its features.
            self.b = [f.copy() for f in arm_features]
        else:
            self.b = [np.zeros(n_features) for _ in range(n_arms)]
        # Store arm_features for hybrid scoring (optional, but we'll use them if provided)
        self.arm_features = arm_features

    def get_recommendations(self, context, top_k=5):
        """
        context: 36‑dim numpy array (user preference + gender + expression)
        Returns (arm_indices, scores)

        خوارزمية الترتيب:
        لكل arm (مكان) نحسب الـ UCB score:
            theta = A^-1 · b              (المعاملات المتعلّمة)
            mean = theta · context         (المكافأة المتوقعة)
            confidence = alpha · sqrt(context · A^-1 · context)
            ucb = mean + confidence
        ثم نضيف static score (لو في warm start):
            static = beta · (context[:27] · arm_features[:27])
            final_score = ucb + static
        ونرجع أعلى top_k arms.
        """
        context = np.asarray(context).reshape(-1)
        scores = []
        for arm in range(self.n_arms):
            A_inv = np.linalg.inv(self.A[arm])
            theta = A_inv @ self.b[arm]
            mean = theta @ context
            confidence = self.alpha * np.sqrt(context @ A_inv @ context)
            ucb = mean + confidence
            # Hybrid: add static dot‑product if arm_features exist
            if self.arm_features is not None and self.beta > 0:
                # static score = beta * (user_vec[:27] · place_vec[:27])
                static = self.beta * (context[:27] @ self.arm_features[arm][:27])
                ucb += static
            scores.append(ucb)
        top_indices = np.argsort(scores)[-top_k:][::-1]
        top_scores = [scores[i] for i in top_indices]
        return top_indices, top_scores

    def update(self, arm_index, context, reward):
        """Update bandit with observed reward (0 or 1).

        خوارزمية التحديث (Sherman-Morrison incremental update):
            A_arm += context · context^T   (نزيد ثقتنا بهذا الـ arm لهذا الـ context)
            b_arm += reward · context       (نزيد المكافأة المتراكمة)
        كل ضغطة قلب من المستخدم = reward=1 → تجعل المكان يبرز للسياقات
        المشابهة في المستقبل.
        """
        context = np.asarray(context).reshape(-1)
        self.A[arm_index] += np.outer(context, context)
        self.b[arm_index] += reward * context