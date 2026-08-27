"""
Annaq Agent — chatbot logic for the tourism kiosk.

Based on Groq's official conversational chatbot example:
https://github.com/groq/groq-api-cookbook/blob/main/tutorials/01-quickstart/groq-quickstart-conversational-chatbot/main.py
"""

import os
import json
import pickle
import csv
import random
from dotenv import load_dotenv

load_dotenv()

from groq import Groq
from recommender.preference_vector import preferences_to_vector
from recommender.linucb import LinUCB
from recommender.place_vector import load_places_with_vectors


CSV_PATH = os.path.join(os.path.dirname(__file__), 'places.csv')
BANDIT_MODEL_PATH = os.path.join(os.path.dirname(__file__), 'bandit_model.pkl')


def load_place_details(csv_path=CSV_PATH):
    """Load all place details from CSV into a dict keyed by place_id."""
    details = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row['place_id']
            details[pid] = {
                'id': pid,
                'name': row.get('name_ar', ''),
                'name_en': row.get('name_en', ''),
                'city': row.get('city', ''),
                'district': row.get('district', ''),
                'type': row.get('primary_type', ''),
                'category': row.get('category', ''),
                'budget': row.get('budget', ''),
                'rating': row.get('rating', ''),
                'description': row.get('description_ar', ''),
                'highlights': row.get('highlights', ''),
                'tags': row.get('tags', ''),
                'indoor_outdoor': row.get('indoor_outdoor', ''),
                'family_friendly': row.get('family_friendly', ''),
                'best_time': row.get('best_time_of_day', ''),
                'duration_hours': row.get('duration_hours', ''),
                'latitude': row.get('latitude', ''),
                'longitude': row.get('longitude', ''),
                'maps_url': row.get('google_maps_url', ''),
                'website': row.get('website', ''),
                'image': row.get('image_url', '') or '',
                'gallery': [u.strip() for u in (row.get('gallery_urls', '') or '').split('|') if u.strip()],
                'featured': (row.get('featured', '') or '').strip().lower() in ('1', 'yes', 'true', 'y'),
                'phone': row.get('phone_number', ''),
            }
    return details


ANNAQ_PERSONALITY = """أنت عنّاق، رفيق رقمي سعودي ذكي ولطيف.
تتكلم لهجة سعودية بيضاء، لطيف وحماسي بدون مبالغة.
تساعد الزوار يكتشفون أماكن سياحية بالسعودية.

ممنوعات لغوية (لا تستخدم كلمات مصرية):
كمان←بعد، عايز←أبي، حاجة←شيء، دلوقتي←الحين، بتحب←تحب

أمثلة ترحيب: "هلا والله! وش تبي تسوي اليوم؟" أو "حياك الله! قولي وش يهمك"
وداع: "الله يسعدك! إن شاء الله نشوفك مرة ثانية"

ردودك قصيرة (3-4 جمل) وبدون إيموجي.
"""


class AnnaqAgent:

    DIALECT_FIXES = {
        "كمان": "بعد",
        "بتحب": "تحب",
        "بتبي": "تبي",
        "عايز": "أبي",
        "عاوز": "أبي",
        "حاجة": "شيء",
        "دلوقتي": "الحين",
        "كده": "كذا",
        "بتاع": "حق",
        "ازيك": "كيف حالك",
        "متتنسيش": "ما تنتسى",
        "ماتنسيش": "ما تنتسى",
        "يارب": "إن شاء الله",
        "أكتر": "أكثر",
        "تانية": "ثانية",
        "تاني": "ثاني",
        "تعمل": "تسوي",
        "نعمل": "نسوي",
        "أعمل": "أسوي",
        "إزاي": "كيف",
        "فين": "وين",
    }

    def __init__(self):
        self.client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        self.model = "meta-llama/llama-4-scout-17b-16e-instruct"
        self.history = [
            {"role": "system", "content": ANNAQ_PERSONALITY}
        ]
        
        self.current_gender = None
        self.current_emotion = None

    

    # ======== تحميل بيانات الأماكن ونظام التوصيات ========
        try:
            place_ids, place_names, _, place_vectors_36 = load_places_with_vectors(CSV_PATH)
            self.place_ids = place_ids
            self.place_names = place_names
            self.place_vectors_36 = place_vectors_36
            self.place_details = load_place_details(CSV_PATH)

            n_arms = len(place_ids)
            if os.path.exists(BANDIT_MODEL_PATH):
                with open(BANDIT_MODEL_PATH, 'rb') as f:
                    self.recommender = pickle.load(f)
                print(f"Loaded recommender model ({n_arms} places)")
            else:
                self.recommender = LinUCB(
                    n_arms, n_features=36, alpha=1.0,
                    arm_features=place_vectors_36, beta=0.5
                )
                print(f"New recommender model ({n_arms} places)")

            self.last_context = None
            self.last_arm_indices = None
            self.session_ended = False

        except Exception as e:
            print(f"Failed to load recommender: {e}")
            self.recommender = None
            self.place_ids = []
            self.place_names = {}
            self.place_details = {}
            self.last_context = None
            self.last_arm_indices = None


    def set_user_attributes(self, gender=None, emotion=None):
        if gender:
            self.current_gender = gender
        if emotion:
            self.current_emotion = emotion


    def _fix_dialect(self, text: str) -> str:
        for eg, sa in self.DIALECT_FIXES.items():
            text = text.replace(eg, sa)
        return text


#استخراج التفضيلات من حديث الزائر

    def extract_preferences(self, user_message: str) -> dict:
        """Extract user preferences from message using LLM."""
        prompt = f"""استخرج من كلام الزائر JSON فقط بدون أي نص إضافي.

الحقول الممكنة:
- primary_type: attraction, restaurant, cafe, mall, park, religious
- budget: low, medium, high, luxury
- family_friendly: true/false
- indoor_outdoor: indoor, outdoor, either
- cuisine: saudi, lebanese, american, seafood, italian, japanese, turkish, none
- best_time: morning, evening, anytime
- weather_sensitive_ok: true/false

إذا ما ذكر الزائر شيء، لا تضمنه.

كلام الزائر: "{user_message}"

JSON:"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=200,
            )
            content = response.choices[0].message.content.strip()

            # تنظيف markdown
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            prefs = json.loads(content)

            for key in ['family_friendly', 'weather_sensitive_ok']:
                if key in prefs and isinstance(prefs[key], str):
                    prefs[key] = prefs[key].lower() == 'true'

            return prefs
        except Exception as e:
            print(f"Failed to extract preferences: {e}")
            return {}


    def _normalize_arabic(self, text: str) -> str:
        """Normalize hamzas, ta marbuta, and ya for matching."""
        text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
        text = text.replace('ة', 'ه')
        text = text.replace('ى', 'ي')
        return text

    # Saudi cities map: normalized Arabic -> English name as in CSV
    CITY_MAP = {
        'الرياض': 'Riyadh', 'رياض': 'Riyadh',
        'جده': 'Jeddah',
        'مكه': 'Makkah', 'مكه المكرمه': 'Makkah',
        'المدينه': 'Madinah', 'المدينه المنوره': 'Madinah',
        'الدمام': 'Dammam', 'دمام': 'Dammam',
        'الخبر': 'Khobar', 'خبر': 'Khobar',
        'الطايف': 'Taif', 'طايف': 'Taif', 'الطائف': 'Taif',
        'ابها': 'Abha',
        'تبوك': 'Tabuk',
        'حايل': 'Hail', 'حائل': 'Hail',
        'بريده': 'Buraydah', 'القصيم': 'Buraydah',  # القصيم منطقة، عاصمتها بريدة
        'العلا': 'AlUla',
        'الدرعيه': 'Diriyah',
        'نجران': 'Najran',
        'جازان': 'Jazan', 'جيزان': 'Jazan',
        'الباحه': 'Al Baha', 'الباحة': 'Al Baha',
        'القطيف': 'Qatif',
        'الاحساء': 'Al-Ahsa', 'الهفوف': 'Al-Ahsa',
        'الظهران': 'Dhahran',
        'عرعر': 'Arar',
        'دومة الجندل': 'Dumat Al-Jandal', 'دومه الجندل': 'Dumat Al-Jandal',
        'رابغ': 'Rabigh',
        'سكاكا': 'Sakaka', 'الجوف': 'Sakaka',
        'شرورة': 'Sharurah',
        'طريف': 'Turaif',
        'املج': 'Umluj',
        'اشيقر': 'Ushaiger',
        'ينبع': 'Yanbu',  # احتياطي — مو موجود حالياً في CSV
    }

    def _detect_city(self, message: str) -> str | None:
        """Detect a Saudi city in the message, return English name from CSV."""
        msg = self._normalize_arabic(message)
        # sort longest-first so "مكه المكرمه" matches before "مكه"
        for ar in sorted(self.CITY_MAP.keys(), key=len, reverse=True):
            if ar in msg:
                return self.CITY_MAP[ar]
        return None

    def _filter_by_city(self, arm_indices: list, target_city: str) -> list:
        """Keep only places in the target city."""
        target = target_city.strip().lower()
        result = []
        for arm_idx in arm_indices:
            pid = self.place_ids[int(arm_idx)]
            place_city = (self.place_details.get(pid, {}).get('city') or '').strip().lower()
            if place_city == target:
                result.append(arm_idx)
        return result

    def _get_featured_indices(self, target_city: str | None = None) -> list:
        """Return featured place indices, optionally filtered by city."""
        result = []
        for i, pid in enumerate(self.place_ids):
            place = self.place_details.get(pid, {})
            if not place.get('featured'):
                continue
            if target_city:
                place_city = (place.get('city') or '').strip().lower()
                if place_city != target_city.strip().lower():
                    continue
            result.append(i)
        return result

    # Keywords for detecting place type
    PRIMARY_TYPE_KEYWORDS = {
        'restaurant': ['مطعم', 'مطاعم', 'اكل', 'اكله', 'طعام', 'وجبه', 'غدا', 'عشا'],
        'cafe':       ['كافيه', 'كافيهات', 'قهوه', 'كوفي', 'مقهى', 'مقاهي'],
        'mall':       ['مول', 'مولات', 'تسوق', 'مركز تجاري', 'سوق'],
        'park':       ['حديقه', 'حدائق', 'متنزه', 'منتزه', 'حديقة'],
        'attraction': ['معلم', 'سياحي', 'سياحه', 'مزار', 'وجهه', 'سياحية'],
        'religious':  ['مسجد', 'مساجد', 'جامع', 'حرم'],
    }

    # Map mood keywords (in user message) to CSV tags
    MOOD_TO_TAGS = {
        # عائلة وأطفال
        'عائلي':     ['عائلات', 'اطفال', 'عائله'],
        'عائليه':    ['عائلات', 'اطفال'],
        'العائله':   ['عائلات', 'اطفال'],
        'الاهل':     ['عائلات'],
        'الاطفال':   ['اطفال', 'عائلات'],
        'الصغار':    ['اطفال', 'عائلات'],
        'مع الاطفال': ['اطفال', 'عائلات'],
        # أصدقاء وشباب
        'الاصدقاء':  ['ترفيه'],
        'الشلة':     ['ترفيه'],
        'الشلله':    ['ترفيه'],
        'الشباب':    ['ترفيه', 'مغامره'],
        'للشباب':    ['ترفيه', 'مغامره'],
        # هدوء واسترخاء
        'هادي':      ['طبيعه', 'اطلاله'],
        'هادئ':      ['طبيعه', 'اطلاله'],
        'هادئه':     ['طبيعه', 'اطلاله'],
        'استرخاء':   ['طبيعه', 'اطلاله'],
        'استجمام':   ['طبيعه', 'اطلاله'],
        'تامل':      ['طبيعه'],
        # تراث وثقافة
        'تراثي':     ['تراث', 'تاريخ', 'عماره', 'تقليدي'],
        'تراثيه':    ['تراث', 'تاريخ', 'تقليدي'],
        'التراث':    ['تراث', 'تاريخ'],
        'تاريخي':    ['تاريخ', 'تراث'],
        'تاريخيه':   ['تاريخ', 'تراث'],
        'التاريخ':   ['تاريخ', 'تراث'],
        'قديم':      ['تاريخ', 'تراث'],
        'قديمه':     ['تاريخ', 'تراث'],
        'ثقافي':     ['ثقافه', 'متحف'],
        'ثقافيه':    ['ثقافه', 'متحف'],
        'ثقافه':     ['ثقافه'],
        'متحف':      ['متحف', 'ثقافه'],
        'متاحف':     ['متحف', 'ثقافه'],
        # مغامرة (مع الجموع)
        'مغامره':    ['مغامره'],
        'مغامرات':   ['مغامره'],
        'مغامراتي':  ['مغامره'],
        'مغامرتي':   ['مغامره'],
        'اثاره':     ['مغامره'],
        'مثيره':     ['مغامره'],
        'حماس':      ['مغامره'],
        'تطعيس':     ['مغامره', 'صحراء'],
        'تسلق':      ['مغامره', 'جبال'],
        'رياضه':     ['مغامره'],
        'غوص':       ['غوص', 'مغامره', 'بحر'],
        # إطلالات وطبيعة
        'اطلاله':    ['اطلاله'],
        'اطلالات':   ['اطلاله'],
        'منظر':      ['اطلاله', 'غروب'],
        'مناظر':     ['اطلاله', 'غروب'],
        'غروب':      ['غروب', 'اطلاله'],
        'بحر':       ['بحر', 'شاطئ'],
        'شاطئ':      ['شاطئ', 'بحر'],
        'شواطئ':     ['شاطئ', 'بحر'],
        'البحر':     ['بحر', 'شاطئ'],
        'جبل':       ['جبال'],
        'الجبل':     ['جبال'],
        'الجبال':    ['جبال'],
        'صحراء':     ['صحراء'],
        'الصحراء':   ['صحراء'],
        'صحاري':     ['صحراء'],
        'الطبيعه':   ['طبيعه'],
        'طبيعه':     ['طبيعه'],
        'طبيعي':     ['طبيعه'],
        'طبيعيه':    ['طبيعه'],
        # تصوير
        'تصوير':     ['تصوير'],
        'صور':       ['تصوير'],
        # ديني
        'ديني':      ['ديني', 'اسلامي'],
        'دينيه':     ['ديني', 'اسلامي'],
        'حرم':       ['ديني', 'اسلامي'],
        # طعام شعبي
        'مشاوي':     ['مشاوي', 'مطاعم'],
        'كبسه':      ['سعودي', 'تقليدي'],
        'مندي':      ['سعودي', 'تقليدي'],
        'فطور':      ['كافيه'],
        # تسوق
        'هدايا':     ['تسوق'],
        'الهدايا':   ['تسوق'],
    }

    # ميزانية: تطبيق "رخيص/فاخر" يوجّه لمستوى budget معيّن في CSV
    BUDGET_KEYWORDS = {
        'low':    ['رخيص', 'اقتصادي', 'بسيط', 'شعبي'],
        'medium': ['متوسط'],
        'high':   ['غالي', 'مرتفع'],
        'luxury': ['فاخر', 'راقي', 'فخم', 'لكشري'],
    }

    def _detect_primary_type(self, message: str) -> str | None:
        """Detect the requested place type from message."""
        msg = self._normalize_arabic(message)
        for ptype, keywords in self.PRIMARY_TYPE_KEYWORDS.items():
            for kw in keywords:
                if self._normalize_arabic(kw) in msg:
                    return ptype
        return None

    def _filter_by_type(self, arm_indices: list, target_type: str) -> list:
        """Keep only places of the target type."""
        target = target_type.strip().lower()
        result = []
        for arm_idx in arm_indices:
            pid = self.place_ids[int(arm_idx)]
            place_type = (self.place_details.get(pid, {}).get('type') or '').strip().lower()
            if place_type == target:
                result.append(arm_idx)
        return result

    def _sort_by_rating(self, arm_indices: list) -> list:
        """Sort by rating descending. Missing ratings treated as 0."""
        def rating_of(arm_idx):
            pid = self.place_ids[int(arm_idx)]
            try:
                return float(self.place_details.get(pid, {}).get('rating') or 0)
            except (ValueError, TypeError):
                return 0.0
        return sorted(arm_indices, key=rating_of, reverse=True)

    def _diverse_pick(self, sorted_candidates: list, k: int = 5) -> list:
        """Pick k random items from the top 2k for variety."""
        if len(sorted_candidates) <= k:
            return list(sorted_candidates)
        pool = list(sorted_candidates[:k * 2])
        random.shuffle(pool)
        return pool[:k]

    def _wrap_place_names(self, text: str, places: list) -> str:
        """Wrap place names with **markdown** if not already wrapped by the LLM."""
        if not text or not places:
            return text
        # sort longest-first so "مول العرب جدة" wraps before "مول"
        names = sorted(
            [p.get('name', '').strip() for p in places if p.get('name')],
            key=len, reverse=True
        )
        for name in names:
            if not name:
                continue
            if f'**{name}**' in text:
                continue
            idx = text.find(name)
            if idx >= 0:
                text = text[:idx] + f'**{name}**' + text[idx + len(name):]
        return text

    def _build_personalized_reply(self, user_message: str, top_places: list) -> str:
        """Build a reply that introduces all top places with bolded names."""
        if not top_places:
            return ""

        # نبني وصف مختصر لكل مكان من البيانات الموجودة (نأخذ المتاح، قد يكون أقل من ٥)
        places_info = []
        actual_places = top_places[:5]  # حد أقصى ٥
        for i, place in enumerate(actual_places, 1):
            name = place.get('name', '')
            desc = (place.get('description') or '')[:180]
            tags = place.get('tags', '')
            city = place.get('city', '')
            ptype = place.get('type', '')
            info = f"{i}. {name}"
            if city:
                info += f" ({city})"
            info += f" — نوع: {ptype}"
            if tags:
                info += f" | تصنيف: {tags[:60]}"
            if desc:
                info += f"\n   وصف: {desc}"
            places_info.append(info)

        n = len(actual_places)
        count_note = (
            f"اخترت له {n} أماكن (هذا العدد الفعلي — لا تذكر أكثر، لا تخترع أسماء):"
            if n > 1 else
            f"اخترت له مكان واحد فقط (هذا اللي يطابق طلبه):"
        )

        prompt = f"""أنت عنّاق، رفيق سياحي سعودي. الزائر قال: "{user_message}"

{count_note}
{chr(10).join(places_info)}

اكتب رد قصير-متوسط (٢-٥ جمل) بلهجة سعودية بيضاء طبيعية:
- اذكر **فقط** هذي الأماكن المعطاة لك بأسماءها (لا تخترع أسماء جديدة)
- ضع كل اسم بين علامتي ** ** (مثلاً: **المسجد الحرام**) — لتبريزه
- لكل مكان: جملة موجزة عن ميزته أو سبب اختياره
- لو كان فيه مكان واحد بس، اشرحه بـ ٢-٣ جمل (لا تجبر نفسك تذكر ٥)
- اختم بسؤال طبيعي مثل: "أيهم يلفت نظرك؟" أو "تبي تعرف عنه أكثر؟"

ممنوعات صارمة:
- ممنوع تخترع أسماء أماكن غير موجودة في القائمة فوق
- ممنوع كلمة "كاردز" أو أي كلمة أجنبية
- ممنوع مفاهيم رومنسية أو مواعدة
- لا تخترع معلومات غير موجودة في الوصف

الرد فقط (بدون مقدمة):"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=300,
            )
            reply = response.choices[0].message.content.strip()
            reply = self._fix_dialect(reply)
            # ضمان التبريز: نلف أسماء الأماكن بـ ** حتى لو LLM ما عملها
            reply = self._wrap_place_names(reply, top_places)
            return reply
        except Exception as e:
            print(f"Failed to build personalized reply: {e}")
            return ""

    def _build_deep_reply(self, place_id: str) -> str:
        """Build a deep-dive reply when the user picks a specific place."""
        place = self.place_details.get(place_id, {})
        if not place:
            return ""

        name = place.get('name', '')
        desc = place.get('description', '')
        highlights = place.get('highlights', '')
        tags = place.get('tags', '')
        city = place.get('city', '')
        district = place.get('district', '')
        ptype = place.get('type', '')
        budget = place.get('budget', '')
        family = place.get('family_friendly', '')
        best_time = place.get('best_time', '')
        rating = place.get('rating', '')

        info = f"الاسم: {name}\n"
        if city:
            info += f"المدينة: {city}"
            if district:
                info += f" / {district}"
            info += "\n"
        info += f"النوع: {ptype}\n"
        if rating:
            info += f"التقييم: {rating}\n"
        if budget:
            info += f"الميزانية: {budget}\n"
        if best_time:
            info += f"أفضل وقت: {best_time}\n"
        if family:
            info += f"عائلي: {family}\n"
        if desc:
            info += f"وصف: {desc}\n"
        if highlights:
            info += f"أبرز المميزات: {highlights}\n"
        if tags:
            info += f"التصنيف: {tags}\n"

        prompt = f"""أنت عنّاق، رفيق سياحي سعودي. الزائر اختار هذا المكان:

{info}

اكتب رد ممتع (٤-٦ جمل، لا يتجاوز ٨٠ كلمة) بلهجة سعودية بيضاء، يتعمق في المكان:
- ابدأ بحماس "ممتاز اختيارك!" أو "روعة!"
- ضع اسم المكان مرة واحدة على الأقل بين ** **
- اذكر شيئين-ثلاثة من مميزاته الفعلية (من الوصف والتصنيف)
- نصيحة عملية: "أنصحك تجي وقت كذا" أو "لا تفوّت كذا"
- اختم بسؤال طبيعي مثل: "تبي أعطيك توصية أخرى؟" أو "تبي أعرّفك على مكان قريب؟"

ممنوعات:
- ممنوع كلمات أجنبية
- ممنوع مفاهيم رومنسية أو مواعدة
- لا تخترع معلومات

الرد فقط:"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=300,
            )
            reply = response.choices[0].message.content.strip()
            reply = self._fix_dialect(reply)
            # ضمان التبريز للاسم في رد التعمّق
            reply = self._wrap_place_names(reply, [place])
            return reply
        except Exception as e:
            print(f"Failed to build deep reply: {e}")
            # احتياطي: نرجع وصف بسيط
            fallback = f"ممتاز اختيارك! **{name}** "
            if desc:
                fallback += desc[:200]
            if highlights:
                fallback += f" أبرز مميزاته: {highlights}"
            return fallback

    def _detect_moods(self, message: str) -> list:
        """Detect mood/occasion tags from the message."""
        msg = self._normalize_arabic(message)
        matched_tags = []
        seen = set()
        # sort longest-first
        for phrase in sorted(self.MOOD_TO_TAGS.keys(), key=len, reverse=True):
            phrase_norm = self._normalize_arabic(phrase)
            if phrase_norm in msg:
                for tag in self.MOOD_TO_TAGS[phrase]:
                    if tag not in seen:
                        matched_tags.append(tag)
                        seen.add(tag)
        return matched_tags

    def _detect_budget(self, message: str) -> str | None:
        """Detect budget level from message."""
        msg = self._normalize_arabic(message)
        for level, keywords in self.BUDGET_KEYWORDS.items():
            for kw in keywords:
                if self._normalize_arabic(kw) in msg:
                    return level
        return None

    def _score_place(self, arm_idx: int, target_city: str | None,
                     target_type: str | None, mood_tags: list,
                     target_budget: str | None) -> float:
        """Score a place: +1 per matched tag, +1.5 for budget match, +0.5 * rating."""
        pid = self.place_ids[int(arm_idx)]
        place = self.place_details.get(pid, {})
        score = 0.0

        # tag matches
        if mood_tags:
            place_tags_raw = (place.get('tags') or '').split(',')
            place_tags_norm = {self._normalize_arabic(t.strip()) for t in place_tags_raw if t.strip()}
            for tag in mood_tags:
                if self._normalize_arabic(tag) in place_tags_norm:
                    score += 1.0

        # budget match
        if target_budget:
            place_budget = (place.get('budget') or '').strip().lower()
            if place_budget == target_budget.lower():
                score += 1.5

        # rating boost
        try:
            rating = float(place.get('rating') or 0)
            score += rating * 0.5
        except (ValueError, TypeError):
            pass

        return score

    def _diversify_by_type(self, sorted_candidates: list, k: int = 5) -> list:
        """Round-robin pick across place types for variety."""
        by_type = {}
        order = []
        for arm_idx in sorted_candidates:
            pid = self.place_ids[int(arm_idx)]
            ptype = (self.place_details.get(pid, {}).get('type') or 'other').strip().lower()
            if ptype not in by_type:
                by_type[ptype] = []
                order.append(ptype)
            by_type[ptype].append(arm_idx)

        result = []
        while len(result) < k:
            added = False
            for ptype in order:
                if by_type[ptype]:
                    result.append(by_type[ptype].pop(0))
                    added = True
                    if len(result) >= k:
                        break
            if not added:
                break
        return result

    def _is_recommendation_request(self, message: str) -> bool:
        """Check if the user is asking for a recommendation."""
        message_norm = self._normalize_arabic(message)

        # strong verbs - explicit recommendation request
        strong_verbs = [
            "اقترح", "اقتراح", "اقتراحات", "اقتراحاتك",
            "توصيه", "توصيات", "رشح", "رشحلي",
            "تنصح", "نصيحه",
            "وش تنصح", "وش رايك", "وش تقترح", "ايش تقترح",
            "دلني", "دلوني",
        ]
        for verb in strong_verbs:
            if verb in message_norm:
                return True

        # place nouns - implicit recommendation request
        place_nouns = [
            "مطعم", "مطاعم", "اكل", "طعام", "وجبه",
            "مكان", "اماكن", "موقع", "مواقع",
            "مقهى", "مقاهي", "كافيه", "كوفي", "قهوه",
            "مول", "مولات", "تسوق", "اسواق",
            "متحف", "متاحف", "معلم", "معالم",
            "حديقه", "حدائق", "منتزه", "منتزهات", "بارك",
            "مسجد", "مساجد", "جامع",
            "فندق", "فنادق", "اقامه",
            "شارع", "حي", "منطقه",
            "ساحه", "كورنيش", "بحر", "صحراء",
            "ترفيه", "تفسح", "تنزه", "نشاط", "فعاليه",
            "سياحه", "سياحي", "زياره", "رحله", "سفر",
            "عائلي", "عائلات",
        ]
        for noun in place_nouns:
            if noun in message_norm:
                return True

        # weak verbs - need place-action context
        weak_verbs = [
            "ممكن", "ابي", "ابغى", "اريد", "اود", "ودي",
            "وين", "اين", "فين", "ما هي", "ما هو", "ما اجمل", "ما احلى",
            "افضل", "احسن", "اجمل", "احلى", "اشهر", "اروع",
        ]
        place_actions = ["روح", "زور", "شوف", "طلع", "سو", "اسوي", "افضي"]
        for verb in weak_verbs:
            if verb in message_norm:
                for action in place_actions:
                    if action in message_norm:
                        return True
        return False

    def _is_feedback_response(self, message: str):
        """Return chosen place number (1-5) or None. Supports number or name."""
        if self.last_arm_indices is None:
            return None

        message_norm = self._normalize_arabic(message)

        # match by number
        num_words = {
            "الاول": 1, "اول": 1, "1": 1, "واحد": 1,
            "الثاني": 2, "ثاني": 2, "2": 2, "اثنين": 2,
            "الثالث": 3, "ثالث": 3, "3": 3, "ثلاثه": 3,
            "الرابع": 4, "رابع": 4, "4": 4, "اربعه": 4,
            "الخامس": 5, "خامس": 5, "5": 5, "خمسه": 5,
        }
        for word, num in num_words.items():
            if word in message_norm and num <= len(self.last_arm_indices):
                return num

        # match by name
        best_match_pos = -1
        best_match_idx = None
        for i, arm_idx in enumerate(self.last_arm_indices):
            pid = self.place_ids[int(arm_idx)]
            place_name = self.place_details.get(pid, {}).get('name', '')
            if not place_name:
                continue
            place_norm = self._normalize_arabic(place_name)
            if place_norm in message_norm:
                return i + 1
            words = [w for w in place_norm.split() if len(w) > 3]
            for w in words:
                if w in message_norm:
                    pos = message_norm.find(w)
                    if best_match_pos < 0 or pos < best_match_pos:
                        best_match_pos = pos
                        best_match_idx = i + 1
        return best_match_idx

    def _match_place_by_name(self, message: str):
        """Return place number (1-5) if user mentioned its name, else None."""
        if self.last_arm_indices is None:
            return None
        message_norm = self._normalize_arabic(message)
        stopwords = {"مطعم", "مكان", "مول", "حديقه", "متحف", "منتزه", "كافيه", "مسجد", "ال", "في", "من"}

        best_match = None
        for i, arm_idx in enumerate(self.last_arm_indices):
            pid = self.place_ids[int(arm_idx)]
            place = self.place_details.get(pid, {})
            name = place.get('name', '')
            if not name:
                continue
            name_norm = self._normalize_arabic(name)
            significant_words = [w for w in name_norm.split() if len(w) > 2 and w not in stopwords]
            if not significant_words:
                if name_norm in message_norm:
                    return i + 1
                continue
            matches = sum(1 for w in significant_words if w in message_norm)
            score = matches / len(significant_words)
            # accept >= 60% match
            if score >= 0.6:
                if best_match is None or score > best_match[1]:
                    best_match = (i + 1, score)
        return best_match[0] if best_match else None

    def _recommend(self, user_message: str):
        """Generate recommendations based on user message."""
        prefs = self.extract_preferences(user_message)
        if not prefs:
            prefs = {}

        gender = self.current_gender
        expression = self.current_emotion
        context = preferences_to_vector(prefs, gender, expression)

        target_city = self._detect_city(user_message)
        target_type = self._detect_primary_type(user_message)
        mood_tags = self._detect_moods(user_message)
        target_budget = self._detect_budget(user_message)

        if target_city:
            print(f"city: {target_city}")
        if target_type:
            print(f"type: {target_type}")
        if mood_tags:
            print(f"tags: {mood_tags}")
        if target_budget:
            print(f"budget: {target_budget}")

        # get initial ranking from bandit
        all_indices, _ = self.recommender.get_recommendations(
            context, top_k=self.recommender.n_arms
        )
        candidates = [int(i) for i in all_indices]

        # apply hard filters (city + type), skip filter if no matches
        if target_city:
            filtered = self._filter_by_city(candidates, target_city)
            if filtered:
                candidates = filtered
            else:
                print(f"No places in {target_city} - skipping city filter")
        if target_type:
            filtered = self._filter_by_type(candidates, target_type)
            if filtered:
                candidates = filtered
            else:
                print(f"No {target_type} found - skipping type filter")

        # soft scoring (tags + budget + rating)
        scored = [
            (idx, self._score_place(idx, target_city, target_type, mood_tags, target_budget))
            for idx in candidates
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        ranked = [idx for idx, _ in scored]

        # final pick with diversity
        if target_type or mood_tags:
            arm_indices = self._diverse_pick(ranked, k=5)
        else:
            arm_indices = self._diversify_by_type(ranked, k=5)

        self.last_context = context
        self.last_arm_indices = arm_indices

        top_places = []
        for idx in arm_indices[:5]:
            pid = self.place_ids[int(idx)]
            place = self.place_details.get(pid, {})
            if place:
                top_places.append(place)

        reply = self._build_personalized_reply(user_message, top_places)
        if reply:
            return reply

        # fallback if LLM fails
        if top_places:
            names = [f"**{p.get('name', '')}**" for p in top_places if p.get('name')]
            if names:
                joined = '، '.join(names[:-1]) + f"، و{names[-1]}" if len(names) > 1 else names[0]
                return f"تمام! انتقيت لك {joined}. أيهم يعجبك؟"
        return "تمام! انتقيت لك أماكن مميزة. أيهم يلفت نظرك؟"

    def _handle_feedback(self, chosen_num: int) -> str:
        """الزائر اختار توصية، حدّث النموذج وأعطي تفاصيل."""
        chosen_arm = self.last_arm_indices[chosen_num - 1]

        self.recommender.update(chosen_arm, self.last_context, reward=1.0)

        try:
            with open(BANDIT_MODEL_PATH, 'wb') as f:
                pickle.dump(self.recommender, f)
        except Exception as e:
            print(f"Failed to save model: {e}")

        pid = self.place_ids[chosen_arm]
        place = self.place_details.get(pid, {})
        name = place.get('name', pid)
        desc = place.get('description', '')
        highlights = place.get('highlights', '')

        self.last_context = None
        self.last_arm_indices = None

        reply = f"اختيار موفق! {name}"
        if desc:
            short_desc = desc[:200] + "..." if len(desc) > 200 else desc
            reply += f"\n\n{short_desc}"
        if highlights:
            reply += f"\n\nأبرز المميزات: {highlights}"
        reply += "\n\nتبي أقترح عليك مكان ثاني؟"
        return reply

    def chat(self, user_message: str) -> str:
        # check for goodbye
        user_norm = self._normalize_arabic(user_message)
        bye_words = [
            "مع السلامه", "السلامه", "سلام عليكم", "يلا باي", "باي", "وداعا",
            "تصبح على خير", "الى اللقاء", "اللقاء",
            "شكرا لك", "شكرن لك", "شكر لك",
            "يعطيك العافيه", "الله يعطيك العافيه",
            "تسلم", "تسلمو", "تسلمي",
            "في امان الله", "بامان الله", "فمان الله",
            "كفايه", "خلاص", "انتهيت",
        ]
        if any(word in user_norm for word in bye_words):
            reply = "الله يسعدك! إن شاء الله نشوفك مرة ثانية."
            self.history.append({"role": "user", "content": user_message})
            self.history.append({"role": "assistant", "content": reply})
            self.session_ended = True
            return reply

        # check if user is responding to a previous recommendation
        if self.recommender and self.last_arm_indices is not None:
            chosen = self._is_feedback_response(user_message)
            if chosen is not None:
                reply = self._handle_feedback(chosen)
                self.history.append({"role": "user", "content": user_message})
                self.history.append({"role": "assistant", "content": reply})
                return reply

        # check if user is asking for a recommendation
        if self.recommender and self._is_recommendation_request(user_message):
            reply = self._recommend(user_message)
            if reply:
                self.history.append({"role": "user", "content": user_message})
                self.history.append({"role": "assistant", "content": reply})
                return reply

        # otherwise: regular chat
        self.history.append({"role": "user", "content": user_message})
        messages = [self.history[0]] + self.history[-20:]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=300,
        )

        reply = response.choices[0].message.content.strip()
        reply = self._fix_dialect(reply)
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def get_last_recommendations(self) -> list:
        """Return last recommendations with full info for the frontend."""
        if self.last_arm_indices is None:
            return []
        indices = list(self.last_arm_indices)
        if len(indices) == 0:
            return []
        recs = []
        for arm_idx in indices:
            pid = self.place_ids[int(arm_idx)]
            place = self.place_details.get(pid, {})
            # نبني قائمة الصور: الجاليري لو موجود، وإلا نرجع للصورة الواحدة
            gallery = place.get('gallery', []) or []
            if not gallery and place.get('image'):
                gallery = [place.get('image')]

            recs.append({
                'id': pid,
                'name': place.get('name', pid),
                'name_en': place.get('name_en', ''),
                'city': place.get('city', ''),
                'description': place.get('description', '')[:200],
                'rating': place.get('rating', ''),
                'image': place.get('image', ''),
                'images': gallery,
                'maps_url': place.get('maps_url', ''),
                'type': place.get('type', ''),
                'category': place.get('category', ''),
                'highlights': place.get('highlights', ''),
            })
        return recs

    def give_feedback(self, place_id: str, reward: float = 1.0) -> bool:
        """Heart click = like. Update the bandit with positive reward."""
        if self.last_context is None or self.last_arm_indices is None:
            return False
        try:
            arm_idx = self.place_ids.index(place_id)
        except ValueError:
            return False
        if arm_idx not in self.last_arm_indices:
            return False

        self.recommender.update(arm_idx, self.last_context, reward=reward)
        try:
            with open(BANDIT_MODEL_PATH, 'wb') as f:
                pickle.dump(self.recommender, f)
        except Exception as e:
            print(f"Failed to save model: {e}")
        return True

    def select_place(self, place_id: str) -> str:
        """User clicked on a place card - generate a deep-dive reply."""
        return self._build_deep_reply(place_id)

    def reset(self):
        self.history = [
            {"role": "system", "content": ANNAQ_PERSONALITY}
        ]
        self.last_context = None
        self.last_arm_indices = None
        self.session_ended = False

    # mood-based intros (used when camera detected emotion)
    MOOD_INTROS = {
        'happy':     "هلا والله! يبان عليك مزاج حلو. أنا عنّاق دليلك للسعودية، تبي نسوي شي يستاهل اليوم؟",
        'sad':       "حياك الله! أنا عنّاق رفيقك السياحي. خلني أساعدك تكتشف شي يطيّب خاطرك.",
        'angry':     "أهلاً فيك! أنا عنّاق. عندي أماكن هادية تروّق فيها، تبي ترتاح شوي؟",
        'surprised': "هلا والله! يبان عليك حماس، أنا عنّاق ومعي أماكن حماسية تستاهل.",
        'neutral':   "حياك الله! أنا عنّاق، دليلك السياحي بالسعودية. وش رايك نكتشف شي حلو سوا؟",
    }

    def get_intro(self, emotion: str = None) -> str:
        """Get a greeting message. If emotion is provided, return a mood-matched intro."""
        self.session_ended = False
        if emotion and emotion in self.MOOD_INTROS:
            return self.MOOD_INTROS[emotion]
        # default random intros
        intros = [
            "هلا والله! أنا عنّاق، رفيقك الذكي ودليلك الشخصي للسعودية. من جبال أبها الباردة لرمال العلا الذهبية، من شواطئ أملج لتراث الدرعية، عندي مئات الأماكن بانتظارك. قول لي وش يجذبك اليوم!",
            "أهلاً فيك! اسمي عنّاق ومتخصص في كنوز السعودية. تراث، طبيعة، مغامرات، أكل شعبي، إطلالات خرافية — كل اللي تتخيله عندي. خلني أرشّح لك مكان يناسب مزاجك!",
            "حيّاك الله! أنا عنّاق، أعرف السعودية شبر شبر. تبي مغامرة في النفود؟ تراث في الدرعية؟ هدوء بين جبال السروات؟ بحر في أملج؟ كل شي عندي، بس قول لي.",
            "هلا والله، أنا عنّاق! من تطعيس الكثبان لتلفريك أبها، من إثراء الظهران لمدائن صالح في العلا — السعودية كلها بين يديك. قول لي ايش تحب وأنا أرتّب لك الأماكن.",
            "أبشر! أنا عنّاق رفيقك السياحي. السعودية فيها كنوز ما تتخيلها — قمم خضراء، جزر مرجانية، تاريخ آلاف السنين، أكل شعبي يفوّت العقل. خل نبدأ، قول لي وش جوّك اليوم!",
        ]
        return random.choice(intros)


if __name__ == "__main__":
    if not os.environ.get("GROQ_API_KEY"):
        print("Missing GROQ_API_KEY. Add it to .env")
        exit(1)

    agent = AnnaqAgent()
    print("Annaq agent ready. Type 'q' to quit, 'new' to reset.")

    while True:
        user_input = input("\nأنت: ").strip()

        if user_input in ["خروج", "exit", "q"]:
            print("عنّاق: الله يسعدك!")
            break

        if user_input in ["جديد", "new", "reset"]:
            agent.reset()
            print("بدأنا محادثة جديدة!")
            continue

        if not user_input:
            continue

        reply = agent.chat(user_input)
        print(f"\nعنّاق: {reply}")

        recs = agent.get_last_recommendations()
        if recs:
            print(f"\n[{len(recs)} توصية جاهزة للفرنت إند]")

        if any(word in reply for word in ["السلامة", "يحفظك", "نشوفك"]):
            break
