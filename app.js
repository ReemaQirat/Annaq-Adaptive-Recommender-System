import {
    renderLayout,
    renderCarousel,
    renderDetails,
    renderList,
    renderInitialScreen,
    buildGalleryHTML,
    updateMoodPanel
} from "./ui.js";

// ===== KIOSK SCALING =====
// الكشك صُمّم على 1920×1080. نوسع/نصغّر #app بنسبة موحدة حسب الشاشة الفعلية
// عشان كل العناصر تحافظ على نسبها وما تتداخل على أي جهاز.
const DESIGN_WIDTH = 1920;
const DESIGN_HEIGHT = 1080;

function scaleToFit() {
    const scale = Math.min(
        window.innerWidth / DESIGN_WIDTH,
        window.innerHeight / DESIGN_HEIGHT
    );
    const offsetX = (window.innerWidth - DESIGN_WIDTH * scale) / 2;
    const offsetY = (window.innerHeight - DESIGN_HEIGHT * scale) / 2;
    const app = document.getElementById('app');
    if (app) {
        app.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
    }
}
window.addEventListener('resize', scaleToFit);

// ===== GLOBAL STATE =====
let isAgentProcessing = false;
let currentRecommendations = [];
// الأماكن اللي حط لها قلب — تتراكم عبر الجلسة، تتمسح عند restart/reset
// زر "جميع الاقتراحات" يعرضها (الـ ❤️ له وظيفتين: تعليم البانديت + بناء قائمة المفضلة)
let likedPlaces = [];
// آخر بيانات معروضة في قائمة switchToList — نتذكرها عشان زر "رجوع" من التفاصيل
// يرد لنفس القائمة (مفضلة أو توصيات حالية)، مو دائماً للتوصيات الحالية
let lastListData = null;
// مرجع لصوت عنّاق الحالي عشان نقدر نوقفه (نمنع feedback loop)
let currentAgentAudio = null;
// مثيل Web Speech Recognition (VAD مدمج، بدون hallucinations)
let recognition = null;
// راية: عنّاق يتكلم الحين، نوقف الاستماع لئلا نسجّل صوته
let isAgentSpeaking = false;
// منع تكرار الرسائل (نفس الجملة لو وصلت مرتين خلال 3 ثواني نتجاهلها)
let lastTranscript = "";
let lastTranscriptTime = 0;
// راية: الجلسة انتهت، ما نرجع نستمع تلقائياً (المستخدم لازم يضغط الشاشة)
let sessionEnded = false;
// idle timer: لو المستخدم سكت طويل، عنّاق يودّع تلقائياً
let idleTimer = null;
let videoStream = null;          // حفظ تيار الكاميرا
let faceInterval = null;         // معرف المؤقت لالتقاط الصور
let lastGender = null;           // آخر جنس تم اكتشافه
let lastEmotion = null;     // آخر عاطفة تم اكتشافها
const IDLE_TIMEOUT_MS = 60000; // 60 ثانية بدون تفاعل = انتهاء جلسة تلقائي

// ===== SOCKET.IO =====
const socket = io('http://localhost:5000');
// نعرض socket للنافذة العامة عشان نقدر نختبر من Console (DevTools)
window.socket = socket;

socket.on('connect', () => {
    console.log('Connected to Annaq backend');
    showToast("اضغط على الشاشة لبدء المحادثة", 3000);
    // نستنى ضغطة واحدة من المستخدم (مطلوبة لتفعيل المايك في المتصفح) ثم نبدأ الاستماع المستمر
    document.body.addEventListener('click', () => {
        initContinuousListening();
        initFaceCapture();
        resetIdleTimer();
    }, { once: true });
});

socket.on('face_analysis', (data) => {
    if (data.gender) {
        lastGender = data.gender;
        lastEmotion = data.emotion;
        // نحدّث لوحة الترحيب لو الزائر بالشاشة الرئيسية
        // (الدالة تتجاهل بصمت لو الواجهة بشاشة ثانية)
        updateMoodPanel(data.emotion, data.gender);
        // أول كشف للوجه: لو الـ intro لسه ما انرسل، نرسله الحين بالمزاج المكتشف
        // عشان عنّاق يحيّي الزائر بصوت يناسب مزاجه
        if (!introSent) {
            introSent = true;
            if (introTimeoutId) { clearTimeout(introTimeoutId); introTimeoutId = null; }
            socket.emit('request_intro', { gender: lastGender, emotion: lastEmotion });
        }
    }
});

// نتحكم في توقيت إرسال الـ intro: نستنى أول كشف للكاميرا (مدّة قصيرة) عشان
// التحية تطلع بصوت متخصّص حسب المزاج. لو الكاميرا ما اشتغلت، نرسل intro عام.
let introSent = false;
let introTimeoutId = null;



// تهيئة الاستماع المستمر باستخدام Web Speech Recognition (VAD ذكي مدمج)
function initContinuousListening() {
    console.log("Initializing continuous speech recognition...");
    if (!setupSpeechRecognition()) {
        // المتصفح لا يدعم Web Speech (Firefox/Safari غير مدعومين)
        showToast("متصفحك لا يدعم التعرف الصوتي — استخدم Chrome أو Edge", 8000);
        return;
    }
    startContinuousListening();
    setTimeout(attachMicButton, 200);
    // ما نطلق intro هنا. الـ intro راح يطلق إما من:
    // 1) face_analysis handler (لو الكاميرا كشفت مزاج) — تحية متخصّصة
    // 2) initFaceCapture .catch (لو الكاميرا مرفوضة) — تحية عامة فوراً
    // 3) safety fallback بعد ١٠ ثواني (لو الكاميرا اشتغلت بس ما لقت وجه)
    introTimeoutId = setTimeout(() => {
        if (!introSent) {
            console.log("⏱️ No face detected within 10s — falling back to generic intro");
            introSent = true;
            socket.emit('request_intro', {});
        }
    }, 10000);
}

function initFaceCapture() {
    if (videoStream) return; // سبق أن طلبنا الصلاحية

    navigator.mediaDevices.getUserMedia({ video: true })
        .then(stream => {
            videoStream = stream;
            // ننشئ عنصر فيديو مخفياً
            const video = document.createElement('video');
            video.srcObject = stream;
            video.setAttribute('playsinline', '');
            video.style.display = 'none';   // إخفاء الفيديو تماماً
            document.body.appendChild(video);
            video.play();

            // دالة التقاط: تستخدم لأول لقطة سريعة + اللقطات الدورية
            const capture = () => {
                if (video.videoWidth === 0) return;
                const canvas = document.createElement('canvas');
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                const imageData = canvas.toDataURL('image/jpeg', 0.7);
                socket.emit('capture_face', { image: imageData });
                console.log("📸 Captured frame", canvas.width + 'x' + canvas.height);
            };

            // نلتقط أول لقطة فور ما الفيديو يكون جاهز فعلاً (videoWidth > 0)
            // بدل ما نستخدم setTimeout اللي ممكن يطلق قبل ما الفيديو يجهز
            const fireFirstCapture = () => {
                if (video.videoWidth > 0) {
                    capture();
                } else {
                    setTimeout(fireFirstCapture, 200);  // نعيد الفحص كل 200ms
                }
            };
            video.addEventListener('playing', fireFirstCapture, { once: true });

            // بعدها كل 5 ثوانٍ — لتحديث المزاج بشكل مستمر
            faceInterval = setInterval(capture, 5000);
        })
        .catch(err => {
            // الكاميرا مرفوضة أو غير موجودة — نطلق التحية العامة فوراً عشان الزائر ما ينتظر
            console.warn("Camera not allowed, face features disabled");
            if (!introSent) {
                introSent = true;
                if (introTimeoutId) { clearTimeout(introTimeoutId); introTimeoutId = null; }
                socket.emit('request_intro', {});
            }
        });
}

// إعداد كائن Web Speech Recognition بإعدادات العربية والاستماع المستمر
function setupSpeechRecognition() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return false;

    recognition = new SR();
    recognition.lang = 'ar-SA';           // العربية السعودية
    recognition.continuous = true;        // يستمر يستمع، ما يوقف بعد كل جملة
    recognition.interimResults = false;   // نتائج نهائية فقط (مو وسطية)
    recognition.maxAlternatives = 1;

    // كل ما يلتقط جملة كاملة، نرسلها للسيرفر
    recognition.onresult = (event) => {
        // ما نقبل شي وعنّاق يتكلم (نمنع feedback من السمّاعة)
        if (isAgentSpeaking || isAgentProcessing) {
            console.log("Ignored speech — agent is busy");
            return;
        }
        const last = event.results.length - 1;
        const transcript = event.results[last][0].transcript.trim();
        if (!transcript || transcript.length < 2) return;

        // منع تكرار: لو نفس الجملة وصلت خلال آخر 3 ثواني، نتجاهلها
        const now = Date.now();
        if (transcript === lastTranscript && (now - lastTranscriptTime) < 3000) {
            console.log("Ignored duplicate:", transcript);
            return;
        }
        lastTranscript = transcript;
        lastTranscriptTime = now;

        console.log("🎤 Heard:", transcript);
        showToast(`أنت: ${transcript}`, 2500);
        resetIdleTimer(); // أي تفاعل من المستخدم يعيد ضبط المؤقت

        // قبل ما نرسل للـ agent، نشوف إذا الكلام أمر تنقّل في الواجهة
        if (handleVoiceCommand(transcript)) {
            console.log("✓ Voice command handled locally");
            return;
        }

        isAgentProcessing = true;
        socket.emit('user_message', { 
        message: transcript,
        gender: lastGender,
        emotion: lastEmotion
        });
    };

    recognition.onerror = (event) => {
        console.warn("Speech recognition error:", event.error);
        // أخطاء no-speech و audio-capture طبيعية — نكمل
        if (event.error === 'not-allowed') {
            showToast("الرجاء السماح بالوصول للمايك", 4000);
        }
    };

    // لما يتوقف لأي سبب (network, no-speech, إلخ) نعيد تشغيله تلقائياً
    recognition.onend = () => {
        console.log("Recognition ended");
        // ما نعيد التشغيل لو عنّاق يتكلم أو الجلسة منتهية
        if (isAgentSpeaking || sessionEnded) return;
        setTimeout(() => {
            try { recognition.start(); } catch (e) { /* قد يكون شغّال */ }
        }, 300);
    };

    return true;
}

function startContinuousListening() {
    if (!recognition) return;
    try {
        recognition.start();
        setMicColor(true);
        console.log("✅ Continuous listening started");
    } catch (e) {
        console.warn("Could not start recognition:", e.message);
    }
}

function pauseContinuousListening() {
    if (!recognition) return;
    try {
        recognition.stop();
        setMicColor(false);
    } catch (e) { /* تجاهل */ }
}

// زر المايك يعمل كـ backup — لو المستخدم أراد إيقاف/تشغيل يدوي
function attachMicButton() {
    const mic = document.getElementById('micIndicator');
    if (!mic) {
        setTimeout(attachMicButton, 500);
        return;
    }
    mic.style.cursor = 'pointer';
    mic.onclick = (e) => {
        e.stopPropagation();
        if (isAgentSpeaking) {
            // المستخدم يبي يقاطع عنّاق
            stopAgentAudio();
            isAgentSpeaking = false;
            startContinuousListening();
            return;
        }
        // toggle الاستماع
        if (recognition) {
            try { recognition.stop(); } catch (e) {}
            setMicColor(false);
            showToast("تم إيقاف الاستماع — اضغط لاستئناف", 2000);
        }
    };
}

// نحفظ مؤقتات تنشيط الكاردز عشان نقدر نلغيها لو وصل رد جديد
let cardSyncTimers = [];

function clearCardSyncTimers() {
    cardSyncTimers.forEach(t => clearTimeout(t));
    cardSyncTimers = [];
}

socket.on('agent_reply', (data) => {
    const { reply, recommendations, audio_base64, ended, place_timeline } = data;
    console.log('Agent reply:', reply, 'recs:', recommendations, 'timeline:', place_timeline);
    // نلغي أي مؤقتات سابقة لتجنّب تشغيل تنشيط من رد قديم
    clearCardSyncTimers();
    // نمسح أي نص ظاهر من رد سابق (لو كان حد Groq خلص واشتغل عرض النص)
    clearTextDisplay();

    // نوقف الاستماع المستمر فوراً عشان ما نسجّل صوت عنّاق من السمّاعة
    isAgentSpeaking = true;
    pauseContinuousListening();
    // لو الجلسة انتهت، نضع الراية ونلغي مؤقت السكوت
    if (ended) {
        sessionEnded = true;
        if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
    }

    const hasAudio = audio_base64 && audio_base64.length > 0;

    // ١. أولاً: تحويل الشاشة للكاروسيل لو فيه توصيات جديدة.
    // المهم نسوي التحويل قبل عرض النص — switchToCarousel يستدعي clearTextDisplay،
    // فلو عرضنا النص قبل التحويل راح ينمسح فوراً.
    if (recommendations && recommendations.length) {
        currentRecommendations = recommendations;
        switchToCarousel(recommendations);
        // الكاروسيل يفسح zone من renderLayout — لازم نعيد ربط زر المايك
        setTimeout(attachMicButton, 100);
        // ملاحظة: تزامن الكاردز مع نطق عنّاق يحصل في playAudioBase64 (يستخدم مدة الصوت الفعلية)
        // أو في فرع "ما فيه صوت" (يستخدم مدة مقدّرة). مو هنا.
    }

    // ٢. تشغيل الصوت أو عرض النص بدله — لو ما فيه TTS من Groq نعرض النص فقط
    if (hasAudio) {
        playAudioBase64(audio_base64, place_timeline);
    } else {
        // ما فيه صوت — نقرأ النص فقط ونرجع للاستماع بعد فترة كافية للقراءة
        // التأخير محسوب على طول النص (~80ms لكل حرف، حد أدنى 2.5 ثانية)
        const readTimeMs = Math.max(2500, (reply || '').length * 80);
        // ننشّط الكاردز بناءً على المدة المقدّرة (لا يوجد صوت لقياس مدته الفعلية)
        if (place_timeline && place_timeline.length) {
            setTimeout(() => scheduleCardActivations(place_timeline, readTimeMs), 200);
        }
        // عرض النص جملة جملة — يبقى ظاهر للقراءة (لين الزائر ينقّل أو يجي رد جديد)
        if (reply) {
            showTextLines(reply, readTimeMs);
        }
        scheduleListeningResume(readTimeMs);
    }
    isAgentProcessing = false;
    // ملاحظة: الاستماع يرجع تلقائياً من audio.onended أو utterance.onend
    // (شوف playAudioBase64 و speak) — مو هنا. هذا أدق لأنه يستنى الصوت يخلص فعلاً

    // كل ما عنّاق يرد، نعيد ضبط مؤقت السكوت (دور المستخدم يبدأ الحين)
    resetIdleTimer();

    // لو الجلسة انتهت، نرجع للشاشة الأولى ونستنى ضغطة جديدة لبدء محادثة
    if (ended) {
        console.log("Session ended — resetting to initial screen in 4s");
        setTimeout(() => {
            renderInitialScreen();
            currentRecommendations = [];
            showToast("اضغط على الشاشة لبدء محادثة جديدة", 5000);
            // نربط ضغطة الشاشة لإعادة بدء الجلسة
            document.body.addEventListener('click', restartSession, { once: true });
        }, 4000);
    }
});

// إعادة بدء الجلسة بعد الوداع
function restartSession() {
    console.log("Restarting session...");
    sessionEnded = false;
    isAgentSpeaking = false;
    isAgentProcessing = false;
    lastTranscript = "";
    likedPlaces = []; // زائر جديد = مفضلة جديدة
    lastListData = null;
    clearTextDisplay();
    startContinuousListening();
    resetIdleTimer();
    // عنّاق يرحّب من جديد بزائر جديد
    socket.emit('request_intro');
    if (faceInterval) {
        clearInterval(faceInterval);
        faceInterval = null;
    }
    if (videoStream) {
        videoStream.getTracks().forEach(track => track.stop());
        videoStream = null;
    }
    // نعيد تفعيل التقاط الوجه للجلسة الجديدة
    initFaceCapture();
}

// يعيد ضبط مؤقت السكوت — يُستدعى في كل تفاعل (رسالة، رد، تنقل)
function resetIdleTimer() {
    if (idleTimer) clearTimeout(idleTimer);
    if (sessionEnded) return;
    idleTimer = setTimeout(() => {
        if (sessionEnded || isAgentProcessing || isAgentSpeaking) {
            // ما نرسل لو فيه شي شغال — نعيد المحاولة بعد شوي
            resetIdleTimer();
            return;
        }
        console.log("⏰ Idle timeout — ending session automatically");
        // نرسل "مع السلامة" تلقائياً عشان عنّاق يودّع بصوته الطبيعي
        isAgentProcessing = true;
        socket.emit('user_message', { message: 'مع السلامة' });
    }, IDLE_TIMEOUT_MS);
}

socket.on('feedback_ack', (data) => {
    console.log('❤️ Like recorded', data);
    if (data.status === 'ok') {
        showToast('تم تسجيل إعجابك ✓', 1800);
    }
});

// ===== UI Helpers =====
// يحوّل **text** إلى <strong>text</strong> (تبريز أسماء الأماكن)
// نهرب أي HTML آخر بعدها يدوياً للأمان
function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}
function renderMarkdownBold(text) {
    return escapeHtml(text).replace(/\*\*([^*]+)\*\*/g,
        '<strong style="color:#ffffff; background:rgba(0,0,0,0.25); padding:2px 8px; border-radius:6px;">$1</strong>');
}

function showToast(message, duration = 3000) {
    const toast = document.createElement('div');
    toast.innerHTML = renderMarkdownBold(message);
    toast.style.position = 'fixed';
    toast.style.bottom = '120px';
    toast.style.left = '50%';
    toast.style.transform = 'translateX(-50%)';
    toast.style.background = '#ff7849';
    toast.style.color = 'white';
    toast.style.padding = '12px 24px';
    toast.style.borderRadius = '30px';
    toast.style.zIndex = 1000;
    toast.style.maxWidth = '80vw';
    toast.style.textAlign = 'center';
    toast.style.lineHeight = '1.6';
    toast.style.fontSize = '18px';
    document.body.appendChild(toast);
    if (duration > 0) {
        setTimeout(() => toast.remove(), duration);
    }
}

// ===== TEXT LINES (شرح كلام عنّاق لما الصوت ما يشتغل) =====
// نقسّم الرد لجمل ونعرضها واحدة وراء الثانية في نفس المكان (ما تتراكم)
let textDisplayTimers = [];

function clearTextDisplay() {
    textDisplayTimers.forEach(t => clearTimeout(t));
    textDisplayTimers = [];
    document.querySelectorAll('.annaq-text-line').forEach(el => el.remove());
}

function showTextLines(text, totalDurationMs) {
    clearTextDisplay();
    if (!text) return;

    // نقسم على علامات الترقيم العربية والإنجليزية + سطر جديد
    const sentences = text
        .split(/(?<=[.!؟?،])\s+|\n+/)
        .map(s => s.trim())
        .filter(s => s.length > 0);

    if (sentences.length === 0) return;

    // وقت كل جملة بالتناسب مع طولها (الجمل الطويلة تأخذ وقت أكثر)
    const totalLength = sentences.reduce((sum, s) => sum + s.length, 0) || 1;
    let cumulativeDelay = 0;

    sentences.forEach(sentence => {
        const proportion = sentence.length / totalLength;
        const sentenceDuration = Math.max(1500, Math.round(totalDurationMs * proportion));

        const showTimer = setTimeout(() => {
            // شيل أي سطر سابق قبل عرض الجديد
            document.querySelectorAll('.annaq-text-line').forEach(el => el.remove());

            const line = document.createElement('div');
            line.className = 'annaq-text-line';
            line.innerHTML = renderMarkdownBold(sentence);
            line.style.position = 'fixed';
            line.style.bottom = '120px';
            line.style.left = '50%';
            line.style.transform = 'translateX(-50%)';
            line.style.background = '#ff7849';
            line.style.color = 'white';
            line.style.padding = '12px 24px';
            line.style.borderRadius = '30px';
            line.style.zIndex = 1000;
            line.style.maxWidth = '80vw';
            line.style.textAlign = 'center';
            line.style.lineHeight = '1.6';
            line.style.fontSize = '18px';
            document.body.appendChild(line);

            const removeTimer = setTimeout(() => line.remove(), sentenceDuration);
            textDisplayTimers.push(removeTimer);
        }, cumulativeDelay);

        textDisplayTimers.push(showTimer);
        cumulativeDelay += sentenceDuration + 100; // فاصل صغير بين الجمل
    });
}

function setMicColor(listening) {
    const indicator = document.getElementById('micIndicator');
    if (!indicator) return;
    if (listening) {
        indicator.classList.remove('grey');
    } else {
        indicator.classList.add('grey');
    }
}

// ===== AUDIO PLAYBACK =====
function playAudioBase64(base64String, timeline) {
    if (!base64String || base64String.length === 0) {
        // ما فيه صوت — نرجع نستمع فوراً (مع تأخير صغير)
        scheduleListeningResume(500);
        return;
    }
    stopAgentAudio();
    const base64Data = base64String.includes('base64,')
        ? base64String.split('base64,')[1]
        : base64String;
    const binaryString = atob(base64Data);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    const blob = new Blob([bytes], { type: 'audio/wav' });
    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    currentAgentAudio = audio;

    // لما تحمّل مدة الصوت الفعلية، نجدول تنشيط الكاردز بناءً عليها
    // (هذا أدق من تخمين سرعة النطق على السيرفر)
    let cardsScheduled = false;
    audio.onloadedmetadata = () => {
        if (cardsScheduled) return;
        cardsScheduled = true;
        const durationMs = (audio.duration || 0) * 1000;
        if (timeline && timeline.length && durationMs > 0) {
            // ننتظر شوي حتى ينرسم الكاروسيل قبل ما نشغّل التنشيط
            setTimeout(() => scheduleCardActivations(timeline, durationMs), 200);
        }
    };

    audio.play().catch(e => {
        console.warn("Audio play failed:", e);
        scheduleListeningResume(500); // فشل التشغيل = نرجع نستمع
    });
    // نربط نهاية الاستماع بنهاية الصوت الفعلية (مو تقدير زمني)
    audio.onended = () => {
        URL.revokeObjectURL(audioUrl);
        if (currentAgentAudio === audio) currentAgentAudio = null;
        // تأخير 800ms بعد نهاية صوت عنّاق عشان أي صدى متبقي يهدأ
        scheduleListeningResume(800);
    };
}

// يجدول تنشيط الكاردز بناءً على مدة فعلية (أو مقدّرة لو ما فيه صوت).
// timeline يجي من السيرفر بصيغة {place_id, char_position, total_chars}.
// التحويل للوقت يضمن إن كل كارد ينشّط بالضبط لما عنّاق يبدأ ينطق اسمه.
function scheduleCardActivations(timeline, durationMs) {
    if (!timeline || !timeline.length || !durationMs) return;
    const INITIAL_DELAY_MS = 400;  // أول كارد ما يطلع قبل هذا الحد
    const MIN_GAP_MS = 600;        // فاصل أدنى صغير بين الكاردز (احتياط لو الأسماء متلاصقة)
    let lastTime = 0;

    timeline.forEach((item, i) => {
        let time_ms;
        if (typeof item.char_position === 'number' && item.total_chars > 0) {
            // الموقع نسبي → نضربه في المدة الفعلية للحصول على توقيت دقيق
            const ratio = item.char_position / item.total_chars;
            time_ms = Math.round(ratio * durationMs);
        } else if (typeof item.time_ms === 'number') {
            // توافق رجعي مع timeline قديمة (لو السيرفر القديم لسا شغّال)
            time_ms = item.time_ms;
        } else {
            return;
        }

        if (i === 0 && time_ms < INITIAL_DELAY_MS) {
            time_ms = INITIAL_DELAY_MS;
        }
        if (i > 0 && time_ms < lastTime + MIN_GAP_MS) {
            time_ms = lastTime + MIN_GAP_MS;
        }
        lastTime = time_ms;

        const t = setTimeout(() => activateCardById(item.place_id), time_ms);
        cardSyncTimers.push(t);
    });
}

// نضمن إن الاستماع يرجع لما عنّاق يخلص يتكلم (مع تأخير لتجنب الصدى)
function scheduleListeningResume(delayMs) {
    setTimeout(() => {
        isAgentSpeaking = false;
        // لو الجلسة انتهت (ودّع المستخدم) ما نرجع نستمع — نستنى ضغطة جديدة
        if (sessionEnded) {
            console.log("Session ended — not resuming listening");
            return;
        }
        if (recognition) {
            startContinuousListening();
        }
    }, delayMs);
}

// دالة لإيقاف صوت عنّاق (تستخدم قبل بدء التسجيل + قبل تشغيل صوت جديد)
function stopAgentAudio() {
    if (currentAgentAudio) {
        try {
            currentAgentAudio.pause();
            currentAgentAudio.currentTime = 0;
        } catch (e) { /* تجاهل */ }
        currentAgentAudio = null;
    }
    // نوقف أيضاً Web Speech API (لو speak() كان شغّال)
    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }
}

// ملاحظة: حذفنا دالة speak() اللي كانت تستخدم browser SpeechSynthesis كـ fallback
// — الآن لو الصوت الأساسي ما اشتغل، نعرض النص فقط ونعطي وقت كافي للقراءة

// ===== VIEW MANAGEMENT =====
function switchToCarousel(recommendations) {
    clearTextDisplay(); // امسح أي رد قديم لسا ظاهر من شاشة سابقة
    renderLayout();
    renderCarousel(recommendations);
    attachCarouselEvents();
}

// مسافة السحب الأخيرة بالماوس — نستخدمها عشان نميّز السحب من الكلك
let lastDragDistance = 0;

function attachCarouselEvents() {
    const cards = document.querySelectorAll('.card');
    cards.forEach(card => {
        // ضغطة على جسم الكارد:
        //  - الكارد غير النشط → ينشّط ويتمركز
        //  - الكارد النشط → يفتح صفحة التفاصيل
        card.addEventListener('click', (e) => {
            // لو الضغطة كانت على القلب، نتجاهل لأن له هاندلر مستقل
            if (e.target.closest('.card-heart')) return;
            // لو كان فيه سحب بالماوس، ما نحسبها كلك
            if (lastDragDistance > 5) { lastDragDistance = 0; return; }
            e.stopPropagation();

            const placeId = card.dataset.id;
            const rec = currentRecommendations.find(r => r.id === placeId);

            if (card.classList.contains('active')) {
                // ضغطة ثانية على الكارد النشط = افتح التفاصيل
                if (rec) switchToDetails(rec, 'carousel');
                return;
            }

            // ضغطة أولى = ننشّط الكارد ونوسّطه
            cards.forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            focusCard(card);
        });
    });

    // تفاعل الماوس: عجلة (wheel) + سحب وإفلات
    attachCarouselMouseScroll();

    // الضغط على القلب = إرسال إعجاب + تبديل الحالة بصرياً + ضمّه للمفضلة
    const hearts = document.querySelectorAll('.card-heart');
    hearts.forEach(btn => {
        const placeId = btn.dataset.id;
        // طبّق حالة الإعجاب لو المكان موجود في likedPlaces (مثلاً جا في توصيات جديدة)
        if (likedPlaces.some(p => p.id === placeId)) {
            btn.classList.add('liked');
        }

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const card = btn.closest('.card');
            const placeName = card?.querySelector('h2')?.textContent || 'المكان';

            // toggle: لو ممتلئ نلغي، لو فاضي نعجب ونرسل
            const wasLiked = btn.classList.contains('liked');
            if (wasLiked) {
                btn.classList.remove('liked');
                likedPlaces = likedPlaces.filter(p => p.id !== placeId);
                showToast(`أزلت إعجابك بـ ${placeName}`, 1800);
                return;
            }

            // إعجاب جديد — نضيف للمفضلة (عدة قلوب تقدر تكون ممتلئة بنفس الوقت)
            btn.classList.add('liked');
            const rec = currentRecommendations.find(r => r.id === placeId);
            if (rec && !likedPlaces.some(p => p.id === placeId)) {
                likedPlaces.push(rec);
            }
            socket.emit('feedback', { place_id: placeId });
            showToast(`اختيارك: ${placeName} ✓`, 2500);

            // نفعّل الكارد المرتبط بالقلب بصرياً ونوسّطه
            if (card) {
                cards.forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                focusCard(card);
            }
        });
    });

    // زر "جميع الاقتراحات" → يعرض الأماكن اللي حط لها قلب فقط
    const showAllBtn = document.getElementById('showAllBtn');
    if (showAllBtn) {
        showAllBtn.onclick = (e) => {
            e.stopPropagation();
            if (likedPlaces.length === 0) {
                showToast("ما عجبك أي اقتراح بعد — اضغط على القلب لاختياراتك", 3500);
                return;
            }
            switchToList(likedPlaces);
        };
    }

    // بعد ما الكاروسيل يرسم، نوسّط الكارد النشط بحساب يدوي
    // (scrollIntoView ما يشتغل صح أحياناً مع padding + RTL)
    setTimeout(() => {
        const carousel = document.getElementById('carousel');
        const activeCard = carousel?.querySelector('.card.active');
        if (!carousel || !activeCard) return;
        const cardCenter = activeCard.offsetLeft + activeCard.offsetWidth / 2;
        const viewportCenter = carousel.clientWidth / 2;
        carousel.scrollLeft = cardCenter - viewportCenter;
    }, 60);
}

// ===== LIST VIEW =====
function switchToList(recommendations) {
    if (!recommendations || !recommendations.length) {
        showToast("ما عندنا اقتراحات حالياً", 2000);
        return;
    }
    // نتذكر القائمة المعروضة عشان زر "رجوع" من التفاصيل يردنا لها (مفضلة أو حالية)
    lastListData = recommendations;
    clearTextDisplay(); // امسح أي رد قديم لسا ظاهر من شاشة سابقة
    renderLayout();
    renderList(recommendations);
    attachListEvents();
    setTimeout(attachMicButton, 100);
}

function attachListEvents() {
    document.querySelectorAll('.list-card').forEach(card => {
        card.addEventListener('click', (e) => {
            // تجاهل الضغط على QR نفسه (الزائر بيمسحه بالموبايل)
            if (e.target.closest('.qr')) return;
            const placeId = card.dataset.id;
            // نبحث في القائمة المعروضة فعلياً (المفضلة أو الحالية)، مو دائماً currentRecommendations
            // لأن المفضلة قد تحتوي أماكن من جلسات سابقة مو موجودة في التوصيات الحالية
            const source = lastListData || currentRecommendations;
            const rec = source.find(r => r.id === placeId);
            if (rec) switchToDetails(rec, 'list');
        });
    });

    // زر "رجوع" يرجّع للكاروسيل
    const backBtn = document.getElementById('backBtn');
    if (backBtn) {
        backBtn.onclick = (e) => {
            e.stopPropagation();
            switchToCarousel(currentRecommendations);
        };
    }
}

// نتذكر الشاشة اللي قبل التفاصيل عشان زر "رجوع" يرجّع لها
let detailsCameFrom = 'carousel';

// ===== DETAILS VIEW =====
function switchToDetails(rec, cameFrom = 'carousel') {
    detailsCameFrom = cameFrom;
    // نلغي مؤقتات تنشيط الكاردز (الزائر ترك الكاروسيل)
    clearCardSyncTimers();
    clearTextDisplay(); // امسح أي رد قديم لسا ظاهر من شاشة سابقة
    renderLayout();
    renderDetails(rec);
    attachDetailsEvents(rec);
    setTimeout(attachMicButton, 100);
    // الزائر اختار المكان → عنّاق يتعمّق فيه بصوته
    if (rec && rec.id) {
        socket.emit('select_place', { place_id: rec.id });
    }
}

function attachDetailsEvents(rec) {
    const backBtn = document.getElementById('backBtn');
    if (backBtn) {
        backBtn.onclick = (e) => {
            e.stopPropagation();
            // الرجوع يرد للشاشة اللي جينا منها (الكاروسيل أو القائمة)
            if (detailsCameFrom === 'list') {
                // نرجع لنفس القائمة اللي جينا منها (مفضلة أو حالية) — مو دائماً للحالية
                switchToList(lastListData || currentRecommendations);
            } else {
                switchToCarousel(currentRecommendations);
            }
        };
    }
    attachGalleryEvents();
}

// تنقل الجاليري: ضغطة على صورة جانبية = تصير main، ونعيد بناء الـ HTML
function attachGalleryEvents() {
    const gallery = document.querySelector('.details-gallery');
    if (!gallery) return;
    let images;
    try {
        images = JSON.parse(decodeURIComponent(gallery.dataset.images || '[]'));
    } catch (e) {
        images = [];
    }
    if (images.length < 2) return; // ما فيه تنقل لو وحدة بس

    gallery.addEventListener('click', (e) => {
        const img = e.target.closest('img');
        if (!img) return;
        const idx = parseInt(img.dataset.idx, 10);
        const current = parseInt(gallery.dataset.current, 10);
        if (isNaN(idx) || idx === current) return;

        gallery.dataset.current = idx;
        gallery.innerHTML = buildGalleryHTML(images, idx);
    });
}

// تفاعل الماوس مع الكاروسيل: عجلة + سحب وإفلات
// نسجل الهاندلرز على document مرة وحدة فقط (نتجنب التراكم مع re-renders)
let carouselMouseAttached = false;
let dragState = { active: false, startX: 0, startScrollLeft: 0 };

function attachCarouselMouseScroll() {
    const carousel = document.getElementById('carousel');
    if (carousel) carousel.style.cursor = 'grab';

    if (carouselMouseAttached) return;
    carouselMouseAttached = true;

    // العجلة → سكرول أفقي
    document.addEventListener('wheel', (e) => {
        const c = document.getElementById('carousel');
        if (!c || !c.contains(e.target)) return;
        if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
            e.preventDefault();
            c.scrollLeft += e.deltaY;
        }
    }, { passive: false });

    // بدء السحب
    document.addEventListener('mousedown', (e) => {
        const c = document.getElementById('carousel');
        if (!c || !c.contains(e.target)) return;
        if (e.target.closest('.card-heart')) return;
        dragState.active = true;
        dragState.startX = e.pageX;
        dragState.startScrollLeft = c.scrollLeft;
        lastDragDistance = 0;
        c.style.cursor = 'grabbing';
        c.style.scrollBehavior = 'auto';
    });

    // أثناء السحب
    document.addEventListener('mousemove', (e) => {
        if (!dragState.active) return;
        const c = document.getElementById('carousel');
        if (!c) { dragState.active = false; return; }
        e.preventDefault();
        const deltaX = e.pageX - dragState.startX;
        lastDragDistance = Math.abs(deltaX);
        c.scrollLeft = dragState.startScrollLeft - deltaX;
    });

    // نهاية السحب
    document.addEventListener('mouseup', () => {
        if (!dragState.active) return;
        dragState.active = false;
        const c = document.getElementById('carousel');
        if (c) {
            c.style.cursor = 'grab';
            c.style.scrollBehavior = 'smooth';
        }
    });
}

function focusCard(card) {
    const carousel = document.getElementById("carousel");
    if (!carousel || !card) return;
    // حساب يدوي لتوسيط الكارد (أدق من scrollIntoView مع RTL + padding)
    const cardCenter = card.offsetLeft + card.offsetWidth / 2;
    const viewportCenter = carousel.clientWidth / 2;
    carousel.scrollTo({
        left: cardCenter - viewportCenter,
        behavior: 'smooth'
    });
}

function resetToInitial() {
    pauseContinuousListening();
    socket.emit('reset', {});
    renderInitialScreen();
    isAgentProcessing = false;
    currentRecommendations = [];
    likedPlaces = [];
    lastListData = null;
    clearTextDisplay();
    // لو سبق وكشفت الكاميرا مزاج الزائر، نرجّع شارة المزاج فوراً
    // بدل ما ننتظر 5 ثواني للقطة الجاية
    if (lastEmotion) updateMoodPanel(lastEmotion, lastGender);
    // إعادة تعيين علم الـ intro عشان لما الزائر يبدأ جلسة جديدة، نطلب تحية جديدة
    // متخصّصة بمزاجه الحالي. نرسلها فوراً لأن المزاج موجود من جلسة سابقة.
    introSent = false;
    if (introTimeoutId) { clearTimeout(introTimeoutId); introTimeoutId = null; }
    if (lastEmotion) {
        introSent = true;
        socket.emit('request_intro', { gender: lastGender, emotion: lastEmotion });
    } else {
        introTimeoutId = setTimeout(() => {
            if (!introSent) { introSent = true; socket.emit('request_intro', {}); }
        }, 3000);
    }
    setTimeout(() => startContinuousListening(), 500);
}

window.resetToInitial = resetToInitial;

function requestFullscreen() {
    const el = document.documentElement;
    if (el.requestFullscreen) {
        el.requestFullscreen().catch(() => console.log("Fullscreen denied"));
    }
}

// يعرض overlay فيه QR لخريطة مكان معين — يمسحه الزائر بجواله
function showMapQR(rec) {
    // لو فيه overlay مفتوح أصلاً، نشيله
    document.querySelector('.map-qr-overlay')?.remove();

    const mapsUrl = rec.maps_url
        || `https://www.google.com/maps/search/${encodeURIComponent(rec.name)}`;
    const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=320x320&margin=0&data=${encodeURIComponent(mapsUrl)}`;

    const overlay = document.createElement('div');
    overlay.className = 'map-qr-overlay';
    overlay.innerHTML = `
        <div class="map-qr-modal">
            <h2>خريطة ${rec.name}</h2>
            <p>امسح الكود بكاميرا جوالك لفتح الموقع في الخرائط</p>
            <div class="map-qr-img"><img src="${qrUrl}" alt="QR map" /></div>
            <button class="btn-outline" id="closeMapQR">إغلاق</button>
        </div>
    `;
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    overlay.querySelector('#closeMapQR').onclick = close;
    // إغلاق لما يضغط برّا الـ modal
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) close();
    });
}

// ===== VOICE COMMANDS (UI navigation by speech) =====
// تطبّع النص العربي للمقارنة (تشيل التشكيل، توحّد الحروف)
function normalizeArabic(s) {
    return (s || '')
        .replace(/[ً-ٰٟ]/g, '') // تشكيل
        .replace(/[إأآا]/g, 'ا')
        .replace(/ى/g, 'ي')
        .replace(/ة/g, 'ه')
        .replace(/[ؤئء]/g, 'ء')
        .replace(/\s+/g, ' ')
        .trim()
        .toLowerCase();
}

// مطابقة اسم مكان: نقبل المطابقة الكاملة أو الجزئية (كلمة من الاسم)
function matchPlaceName(transcript, placeName) {
    const t = normalizeArabic(transcript);
    const p = normalizeArabic(placeName);
    if (!t || !p) return false;
    if (t.includes(p) || p.includes(t)) return true;
    // كلمات الاسم اللي ٣ حروف فأكثر، نشوف هل أحدها مذكور في الكلام
    const words = p.split(' ').filter(w => w.length >= 3);
    return words.some(w => t.includes(w));
}

// تنشيط كارد بمعرف مكان (في الكاروسيل) — يحطه active ويوسّطه
function activateCardById(placeId) {
    const cards = document.querySelectorAll('.card');
    let target = null;
    cards.forEach(c => {
        if (c.dataset.id === placeId) {
            c.classList.add('active');
            target = c;
        } else {
            c.classList.remove('active');
        }
    });
    if (target) focusCard(target);
    return !!target;
}

// أوامر الصوت → ترجع true لو نفذنا الأمر محلياً، false لو نرسله للـ agent
function handleVoiceCommand(transcript) {
    const t = normalizeArabic(transcript);
    if (!t) return false;

    // معرفة الشاشة الحالية
    const inDetails = !!document.querySelector('.details-card');
    const inList = !!document.querySelector('.list-view');
    const inCarousel = !!document.querySelector('.carousel-view');

    // "الرئيسية" / "روح للرئيسية"
    if (/الرئيسيه|رجع.*رئيسي/.test(t)) {
        if (window.resetToInitial) window.resetToInitial();
        return true;
    }

    // "رجوع" / "ارجع"
    if (/^(رجوع|ارجع|رجع)$/.test(t) || /رجع.*خلف|رجع.*ورا/.test(t)) {
        if (inDetails) {
            const backBtn = document.getElementById('backBtn');
            if (backBtn) { backBtn.click(); return true; }
        }
        if (inList) {
            switchToCarousel(currentRecommendations);
            return true;
        }
    }

    // "الاقتراحات المفضلة" / "المفضلة" / "اختياراتي" / "اللي عجبني" → يعرض likedPlaces (نفس الزر)
    // لازم يجي قبل فحص "جميع الاقتراحات" عشان الجملتين فيهما "اقتراحات"
    if (/مفضل|اختيارات|عجبني|عجبتني/.test(t)) {
        if (likedPlaces.length === 0) {
            showToast("ما عجبك أي اقتراح بعد — اضغط على القلب لاختياراتك", 3500);
            return true;
        }
        switchToList(likedPlaces);
        return true;
    }

    // "جميع الاقتراحات" / "جميع المقترحات" / "كل التوصيات" / "اقتراحات" / "كلهم" ...
    // نقبل "اقتراح" و "مقترح" (وزنين مختلفين لنفس المعنى) و"توصي" و"اماكن"
    if (/(جميع|كل|كافه).*(اقتراح|مقترح|توصي|اماكن|خيار)/.test(t)
        || /^(الاقتراحات|اقتراحات|المقترحات|مقترحات|التوصيات|توصيات|كلهم|كلها|جميعها|الكل|الباقي|عرض الكل)$/.test(t)) {
        if (currentRecommendations.length) {
            switchToList(currentRecommendations);
            return true;
        }
    }

    // "افتح الخريطة" / "خريطة" / "الموقع" / "وين موقعه" — يفتح خرائط جوجل
    if (/خريط|خرايط|الموقع|موقعه|اين يقع|وين موقع/.test(t)) {
        let targetRec = null;
        // ١. لو ذكرتي اسم مكان معين → نأخذه
        const namedPlace = currentRecommendations.find(r => matchPlaceName(transcript, r.name));
        if (namedPlace) {
            targetRec = namedPlace;
        } else if (inDetails) {
            // ٢. في صفحة التفاصيل → المكان المعروض (نلقاه من العنوان)
            const titleEl = document.querySelector('.details-title');
            if (titleEl) {
                const title = titleEl.textContent.trim();
                targetRec = currentRecommendations.find(r => r.name === title);
            }
        } else if (inCarousel) {
            // ٣. الكاروسيل → الكارد النشط
            const activeCard = document.querySelector('.card.active');
            if (activeCard) {
                const placeId = activeCard.dataset.id;
                targetRec = currentRecommendations.find(r => r.id === placeId);
            }
        }
        if (targetRec) {
            showMapQR(targetRec);
            return true;
        }
    }

    // "تفاصيل" / "افتح" / "اختار" — يفتح تفاصيل الكارد النشط
    if (inCarousel && /^(تفاصيل|تفاصيله|افتح|اختار|اختر|ادخل)/.test(t)) {
        const activeCard = document.querySelector('.card.active');
        if (activeCard) {
            const placeId = activeCard.dataset.id;
            const rec = currentRecommendations.find(r => r.id === placeId);
            if (rec) { switchToDetails(rec, 'carousel'); return true; }
        }
    }

    // اسم مكان: في أي شاشة = اختيار → نفتح التفاصيل ونعمّق فيه
    if ((inCarousel || inList) && currentRecommendations.length) {
        const matched = currentRecommendations.find(r => matchPlaceName(transcript, r.name));
        if (matched) {
            switchToDetails(matched, inList ? 'list' : 'carousel');
            return true;
        }
    }

    return false;
}

function init() {
    console.log("Annaq is starting...");
    requestFullscreen();
    scaleToFit(); // أول استدعاء قبل ما نرسم — عشان #app يطلع بالحجم الصحيح من البداية
    renderLayout();
    renderInitialScreen();
    // Wait for user click (handled by socket connect)

    // إعادة ضبط مؤقت السكوت على أي تفاعل من الزائر — ضغط، سحب، عجلة، لمس، مفتاح
    // (مو فقط عند الكلام) عشان التصفّح بدون كلام يحسب تفاعل ولا يقطع الجلسة
    ['click', 'touchstart', 'wheel', 'keydown', 'pointerdown'].forEach(evt => {
        document.addEventListener(evt, () => {
            if (!sessionEnded) resetIdleTimer();
        }, { passive: true });
    });
}

init();