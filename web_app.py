"""
web_app.py — السيرفر الرئيسي للكشك (Web + Socket.IO)
=======================================================

وظيفة الملف في المشروع:
    السيرفر الرئيسي اللي يربط الفرنت (المتصفح) مع الـ AI agent.
    يستقبل أحداث Socket.IO من الزائر، يمررها للـ agent والـ TTS،
    ويرجع الردود + الصوت + التوصيات.

    هذا الملف اللي تشغّلينه: python web_app.py
    ثم يفتح المتصفح على http://localhost:5000

أحداث Socket.IO المدعومة:
    - connect / disconnect: لما الزائر يفتح/يقفل الصفحة
    - user_message: استلام رسالة نصية (من Web Speech API بالمتصفح)، توليد رد + صوت + توصيات
    - feedback: ضغط القلب → تحديث البانديت يتعلم تفضيلات الزائر
    - select_place: فتح كارد للتفاصيل → عنّاق يتعمّق في المكان بصوته
    - reset: إعادة تعيين الجلسة (الزائر ضغط الرئيسية)
    - request_intro: طلب التحية الافتتاحية (أول ضغطة على الشاشة)

المكتبات المطلوبة:
    pip install aiohttp python-socketio[asyncio] groq python-dotenv
    + مفتاح GROQ_API_KEY في ملف .env
    + pip install opencv-python cvlib tensorflow ,keras

الخوارزميات الرئيسية:
    1. build_place_timeline: يحسب متى يجب تنشيط كل كارد ليتزامن مع
       نطق عنّاق لاسمه — مبني على موقع الـ **name** في النص ومعدل النطق العربي
"""

import os
import base64
import re
from aiohttp import web
import socketio
import asyncio
from dotenv import load_dotenv
load_dotenv()  # Load API key from .env

from annaq_agent import AnnaqAgent
from tts_module import AnnaqTTS

import cv2
import cvlib as cv
import numpy as np
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing.image import img_to_array
from deepface import DeepFace


# Create Socket.IO server
sio = socketio.AsyncServer(cors_allowed_origins='*', async_mode='aiohttp')
app = web.Application()
sio.attach(app)

# Create agent and TTS
agent = AnnaqAgent()
tts = AnnaqTTS()

# ---------------------- Face & Gender Detection ----------------------


# DeepFace يكشف الجنس + المشاعر معاً — أدق من النموذج المحلي
# (النموذج المحلي model_file.keras كان يعطي "غاضب" بشكل دائم تقريباً)
# warm-up: نحمّل النموذج مرة وحدة ببداية السيرفر عشان أول request يكون سريع
try:
    _warmup = np.zeros((100, 100, 3), dtype=np.uint8)
    DeepFace.analyze(img_path=_warmup, actions=['gender', 'emotion'],
                     enforce_detection=False, silent=True)
    print("✅ DeepFace ready (gender + emotion)")
    deepface_ready = True
except Exception as e:
    print(f"⚠️ Failed to warm up DeepFace: {e}")
    deepface_ready = False

# تحويل أسماء المشاعر من DeepFace إلى الصيغة اللي يقبلها preference_vector.py
# DeepFace يرجع: angry, disgust, fear, happy, sad, surprise, neutral
# preference_vector يقبل: happy, neutral, sad, surprised, bored, angry, other
EMOTION_MAP = {
    'happy': 'happy',
    'neutral': 'neutral',
    'sad': 'sad',
    'surprise': 'surprised',
    'angry': 'angry',
    # disgust/fear ما نخليها "غاضب" لأنها غالباً false positive من تعابير محايدة
    'disgust': 'neutral',
    'fear': 'neutral',
}

def analyze_face(image_bytes):
    """تستقبل صورة (bytes) وتحلل الوجه الأول لتعيد (gender, emotion).

    قاعدة مهمة: لو ما فيه وجه فعلي بالصورة، نرجّع (None, None) — ما نخمّن.
    أهم من إجابة غلط = لا إجابة، عشان لوحة الترحيب ما تظهر بدون مبرر.
    """
    if not deepface_ready:
        return None, None
    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        return None, None

    faces, _ = cv.detect_face(frame)
    if not faces:
        return None, None  # ما فيه وجه — لا نتائج

    # نحدّ إحداثيات الوجه داخل حدود الصورة (cvlib أحياناً يرجع قيم خارج الإطار)
    h_img, w_img = frame.shape[:2]
    x, y, x2, y2 = faces[0]
    x = max(0, min(x, w_img)); x2 = max(0, min(x2, w_img))
    y = max(0, min(y, h_img)); y2 = max(0, min(y2, h_img))
    if x2 <= x or y2 <= y:
        return None, None  # إحداثيات خربانة

    # حجم الوجه لازم يكون معقول — لو صغير جداً غالباً false positive
    face_w = x2 - x
    face_h = y2 - y
    if face_w < 60 or face_h < 60:
        return None, None

    face_crop = frame[y:y2, x:x2]
    if face_crop.size == 0:
        return None, None

    # مكالمة DeepFace وحدة تجيب الجنس + المشاعر معاً
    try:
        df = DeepFace.analyze(
            img_path=face_crop, actions=['gender', 'emotion'],
            enforce_detection=False, silent=True
        )
        df = df[0] if isinstance(df, list) else df
        gender = 'female' if df.get('dominant_gender') == 'Woman' else 'male'
        emotion_raw = df.get('dominant_emotion', 'neutral')
        emotion = EMOTION_MAP.get(emotion_raw, 'neutral')
        print(f"📊 Face detected ({face_w}x{face_h}): gender={gender}  emotion={emotion} (raw={emotion_raw})")
        return gender, emotion
    except Exception as e:
        print(f"⚠️ DeepFace failed: {e}")
        return None, None

@sio.event
async def capture_face(sid, data):
    """يستقبل صورة base64 ويعيد التحليل (بدون أي إشعار للمستخدم)"""
    try:
        image_b64 = data.get('image', '')
        if not image_b64:
            await sio.emit('face_analysis', {'gender': None, 'emotion': None}, room=sid)
            return
        if ',' in image_b64:
            image_b64 = image_b64.split(',')[1]
        image_bytes = base64.b64decode(image_b64)
        gender, emotion = await asyncio.to_thread(analyze_face, image_bytes)
        await sio.emit('face_analysis', {'gender': gender, 'emotion': emotion}, room=sid)
    except Exception as e:
        print(f"Face analysis error: {e}")
        await sio.emit('face_analysis', {'gender': None, 'emotion': None}, room=sid)
   #end of face detection and analysis code

# ========== MAIN CHAT HANDLER ==========
def build_place_timeline(reply: str, recs: list) -> list:
    """يحسب موقع كل اسم مكان في النص (نسبي).

    لا نحسب التوقيت بالـ ms هنا لأن تخمين سرعة النطق غير دقيق — سرعة Groq Orpheus
    تتفاوت حسب الجملة وعلامات الترقيم. بدلاً من ذلك نرسل الموقع النسبي
    (char_position / total_chars) والفرنت يضربه في مدة الصوت الفعلية
    من audio.duration للحصول على توقيت دقيق متزامن مع نطق عنّاق.
    """
    if not reply or not recs:
        return []
    rec_by_name = {r.get('name', ''): r for r in recs}
    total_chars = len(reply)
    timeline = []
    seen_ids = set()
    for match in re.finditer(r'\*\*([^*]+)\*\*', reply):
        name = match.group(1).strip()
        rec = rec_by_name.get(name)
        if not rec:
            continue
        place_id = rec.get('id')
        if not place_id or place_id in seen_ids:
            continue
        seen_ids.add(place_id)
        timeline.append({
            'place_id': place_id,
            'char_position': match.start(),
            'total_chars': total_chars,
        })
    return timeline

@sio.event
async def user_message(sid, data):
    message = data.get('message', '')
    gender = data.get('gender')
    emotion = data.get('emotion')
    
    if (gender or emotion) and hasattr(agent, 'set_user_attributes'):
        agent.set_user_attributes(gender=gender, emotion=emotion)
    
    print(f'Message from {sid}: {message}')

    # Get agent reply
    reply = await asyncio.to_thread(agent.chat, message)

    # Get recommendations if any
    recs = []
    if hasattr(agent, 'get_last_recommendations'):
        recs = agent.get_last_recommendations()

    # Generate audio for the reply
    audio_b64 = await asyncio.to_thread(tts.get_audio_base64, reply)

    # نقرأ علم نهاية الجلسة قبل ما نعمل reset
    ended = getattr(agent, 'session_ended', False)

    # نحسب timeline لتزامن الكاروسيل مع كلام عنّاق
    timeline = build_place_timeline(reply, recs)

    await sio.emit('agent_reply', {
        'reply': reply,
        'recommendations': recs,
        'audio_base64': audio_b64,
        'ended': ended,
        'place_timeline': timeline,
    }, room=sid)

    # لو المستخدم ودّع، نعيد تعيين الـ agent عشان الجلسة الجاية تبدأ نظيفة
    if ended:
        agent.reset()

# ========== FEEDBACK (heart click — تتبع التفضيلات للبانديت) ==========
@sio.event
async def feedback(sid, data):
    place_id = data.get('place_id')
    print(f'❤️ Heart click from {sid}: {place_id}')

    if not hasattr(agent, 'give_feedback'):
        await sio.emit('feedback_ack', {'status': 'error'}, room=sid)
        return

    ok = await asyncio.to_thread(agent.give_feedback, place_id)
    await sio.emit('feedback_ack', {
        'status': 'ok' if ok else 'error',
        'place_id': place_id
    }, room=sid)

# ========== SELECT PLACE (card click — عنّاق يتعمّق في المكان) ==========
@sio.event
async def select_place(sid, data):
    place_id = data.get('place_id')
    print(f'👆 Selected place from {sid}: {place_id}')

    if not hasattr(agent, 'select_place'):
        return

    deep_reply = await asyncio.to_thread(agent.select_place, place_id)
    if not deep_reply:
        return

    audio_b64 = await asyncio.to_thread(tts.get_audio_base64, deep_reply)
    await sio.emit('agent_reply', {
        'reply': deep_reply,
        'recommendations': [],  # ما نغيّر التوصيات الموجودة في الكاروسيل
        'audio_base64': audio_b64,
        'ended': False,
    }, room=sid)

# ========== RESET ==========
@sio.event
async def reset(sid, data):
    print(f'Reset requested from {sid}')
    agent.reset()
    await sio.emit('reset_ack', {'status': 'ok'}, room=sid)

# ========== INTRO ==========
# الفرنت يطلبها أول ما الزائر يبدأ — عنّاق يقدّم نفسه بصوته
# لو فيه مزاج/جنس مكتشف من الكاميرا، التحية تتخصّص بصوت عنّاق
@sio.event
async def request_intro(sid, data=None):
    data = data or {}
    emotion = data.get('emotion')
    gender = data.get('gender')
    print(f'Intro requested by {sid}  (gender={gender}, emotion={emotion})')
    if (gender or emotion) and hasattr(agent, 'set_user_attributes'):
        agent.set_user_attributes(gender=gender, emotion=emotion)
    intro = agent.get_intro(emotion=emotion)
    audio_b64 = await asyncio.to_thread(tts.get_audio_base64, intro)
    await sio.emit('agent_reply', {
        'reply': intro,
        'recommendations': [],
        'audio_base64': audio_b64,
        'ended': False,
    }, room=sid)

# ========== CONNECTION EVENTS ==========
@sio.event
async def connect(sid, environ):
    print(f'Client {sid} connected')
    await sio.emit('connected', {'data': 'Connected to Annaq backend'}, room=sid)

@sio.event
async def disconnect(sid):
    print(f'Client {sid} disconnected')

# ========== STATIC FILES ==========
async def serve_index(request):
    return web.FileResponse('index.html')

async def serve_static(request):
    path = request.match_info['path']
    return web.FileResponse(path)

app.router.add_get('/', serve_index)
app.router.add_get('/{path:.*}', serve_static)

# ========== RUN SERVER ==========
if __name__ == '__main__':
    web.run_app(app, host='0.0.0.0', port=5000)