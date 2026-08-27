// ===== RENDER ROOT LAYOUT =====
export function renderLayout() {
    const app = document.getElementById("app");
    app.innerHTML = `
        <div class="screen">
            <div class="kiosk-logo">
                <img src="assets/Images/logo.png" alt="Annaq" onerror="this.style.display='none'" />
            </div>
            <div class="top-bar">
                <button class="btn-outline" id="homeBtn">الرئيسية</button>
            </div>
            <div id="content"></div>
            <div class="mic-indicator" id="micIndicator">
                <i class="fas fa-microphone"></i>
            </div>
        </div>
    `;
    const homeBtn = document.getElementById('homeBtn');
    if (homeBtn) {
        // Use the globally exposed function from app.js
        homeBtn.onclick = () => {
            if (window.resetToInitial) window.resetToInitial();
        };
    }
}

// ===== INITIAL SCREEN =====
// خريطة المشاعر → عرض ودود (إيموجي + شارة + لمسة شخصية في الترحيب)
const EMOTION_PRESENTATION = {
    happy:     { emoji: '😊', label: 'يبان عليك مزاج حلو', subtitle: 'تبي نسوي شي يستاهل اليوم؟' },
    sad:       { emoji: '🤗', label: 'حياك الله', subtitle: 'خلني أساعدك تكتشف شي يطيّب خاطرك' },
    angry:     { emoji: '🌿', label: 'أهلاً فيك', subtitle: 'تبي مكان تروّق فيه شوي؟' },
    surprised: { emoji: '✨', label: 'يبان متحمّس', subtitle: 'عندي أماكن حماسية تستاهل' },
    neutral:   { emoji: '🙂', label: 'هلا والله', subtitle: 'وش رايك نكتشف شي حلو سوا؟' },
    bored:     { emoji: '☕', label: 'هلا فيك', subtitle: 'عندي أفكار تكسر الروتين' }
};

export function renderInitialScreen() {
    const content = document.getElementById("content");
    content.innerHTML = `
        <div class="initial-screen">
            <div class="welcome-card">
                <h1 class="welcome-title">أهلاً وسهلاً</h1>
                <p class="welcome-subtitle" id="welcomeSubtitle">قول لي وش تبي تكتشف اليوم</p>
                <div class="mood-badge" id="moodBadge" style="display: none;">
                    <span class="gender-icon" id="genderIcon" aria-label="الجنس"></span>
                    <span class="mood-emoji" id="moodEmoji">🙂</span>
                    <span class="mood-label" id="moodLabel">مستعد لتجربة جديدة</span>
                </div>
            </div>
        </div>
    `;
}

// تحديث لوحة الترحيب الشخصية حسب المشاعر + الجنس المكتشفة من الكاميرا
// تُستدعى من app.js لما يجي حدث face_analysis
export function updateMoodPanel(emotion, gender) {
    const badge = document.getElementById('moodBadge');
    const emojiEl = document.getElementById('moodEmoji');
    const labelEl = document.getElementById('moodLabel');
    const subtitleEl = document.getElementById('welcomeSubtitle');
    const genderEl = document.getElementById('genderIcon');
    // الواجهة ممكن تكون انتقلت لشاشة ثانية — نتجاهل بصمت
    if (!badge || !emojiEl || !labelEl || !subtitleEl) return;
    const p = EMOTION_PRESENTATION[emotion] || EMOTION_PRESENTATION.neutral;
    emojiEl.textContent = p.emoji;
    labelEl.textContent = p.label;
    subtitleEl.textContent = p.subtitle;
    // مؤشّر الجنس — دائرة ملوّنة بدون رموز (وردي للأنثى / أزرق للذكر)
    if (genderEl) {
        if (gender === 'female') {
            genderEl.className = 'gender-icon female';
            genderEl.style.display = 'inline-block';
        } else if (gender === 'male') {
            genderEl.className = 'gender-icon male';
            genderEl.style.display = 'inline-block';
        } else {
            genderEl.style.display = 'none';
        }
    }
    badge.style.display = 'inline-flex';
}

// ===== CAROUSEL VIEW =====
// خريطة لتحويل اسم التصنيف الإنجليزي لنص عربي يظهر تحت العنوان
const CATEGORY_AR = {
    entertainment: 'ترفيه',
    heritage: 'تراث',
    cultural: 'ثقافة',
    art: 'حدث فني',
    event: 'فعالية',
    nature: 'طبيعة',
    park: 'حديقة',
    food: 'مطعم',
    cafe: 'مقهى',
    shopping: 'تسوق',
    religious: 'ديني',
    adventure: 'مغامرة',
    historic_site: 'موقع تاريخي',
    theme_park: 'مدينة ألعاب',
};

function categoryLabel(rec) {
    // نحاول نبني وسم: "category | sub_category" بالعربي
    const parts = [];
    if (rec.category && CATEGORY_AR[rec.category]) parts.push(CATEGORY_AR[rec.category]);
    else if (rec.category) parts.push(rec.category);
    if (rec.sub_category && CATEGORY_AR[rec.sub_category]) parts.push(CATEGORY_AR[rec.sub_category]);
    if (parts.length === 0 && rec.type) parts.push(CATEGORY_AR[rec.type] || rec.type);
    return parts.join(' | ');
}

// SVG أيقونة قلب — متمركز جيداً داخل الزر (Material Design heart)
const HEART_SVG = `<svg viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>`;

// ألوان وأيقونات placeholder حسب نوع المكان (primary_type)
const CATEGORY_THEME = {
    restaurant:  { c1: '#ff7849', c2: '#a83809', icon: '🍽' },
    cafe:        { c1: '#b08968', c2: '#5e3d23', icon: '☕' },
    mall:        { c1: '#3b82f6', c2: '#1e3a8a', icon: '🛍' },
    park:        { c1: '#10b981', c2: '#064e3b', icon: '🌳' },
    attraction:  { c1: '#f59e0b', c2: '#78350f', icon: '🏛' },
    religious:   { c1: '#6366f1', c2: '#312e81', icon: '🕌' },
};

const DEFAULT_THEME = { c1: '#475569', c2: '#1e293b', icon: '📍' };

// ينشئ placeholder SVG (data URI) ملوّن حسب نوع المكان مع اسم المكان
function buildPlaceholder(rec) {
    const theme = CATEGORY_THEME[rec.type] || DEFAULT_THEME;
    const name = (rec.name || 'مكان').slice(0, 30); // قص الأسماء الطويلة
    // نستخدم encodeURIComponent عشان النص العربي يشتغل في data URI
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
        <defs>
            <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="${theme.c1}"/>
                <stop offset="100%" stop-color="${theme.c2}"/>
            </linearGradient>
        </defs>
        <rect width="600" height="400" fill="url(#g)"/>
        <text x="300" y="180" font-size="120" text-anchor="middle" dominant-baseline="middle">${theme.icon}</text>
        <text x="300" y="290" font-size="28" fill="#ffffff" text-anchor="middle" font-family="Arial, sans-serif" font-weight="bold" opacity="0.95">${name}</text>
    </svg>`;
    return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
}

export function renderCarousel(recommendations) {
    const content = document.getElementById("content");
    // الكارد الأوسط يكون active كبداية
    const activeIdx = recommendations.length > 1 ? 1 : 0;
    content.innerHTML = `
        <div class="carousel-view">
            <div class="carousel" id="carousel">
                ${recommendations.map((rec, i) => {
                    const name = rec.name || 'مكان';
                    const desc = rec.description || '';
                    const cat = categoryLabel(rec);
                    const img = rec.image || buildPlaceholder(rec);
                    return `
                    <div class="card ${i === activeIdx ? "active" : ""}" data-id="${rec.id}" data-index="${i}">
                        <div class="card-image-wrap">
                            <img src="${img}" alt="${name}" />
                        </div>
                        <div class="card-content">
                            <h2>${name}</h2>
                            ${cat ? `<div class="card-category">${cat}</div>` : ''}
                            <p class="card-desc">${desc}</p>
                        </div>
                        <button class="card-heart" data-id="${rec.id}" aria-label="إعجاب">
                            ${HEART_SVG}
                        </button>
                    </div>
                    `;
                }).join("")}
            </div>
            <button class="btn-outline center-btn" id="showAllBtn">الاقتراحات المفضلة</button>
        </div>
    `;
}

// helper لبناء HTML الجاليري حول صورة محددة (currentIdx)
// لو ٣ صور أو أكثر: تعرض السابقة + الحالية (main) + التالية مع wrap-around
// لو ٢: تعرض الاثنتين، الحالية main
// لو ١: تعرض وحدة فقط
export function buildGalleryHTML(images, currentIdx) {
    if (!images.length) return '';
    if (images.length === 1) {
        return `<img src="${images[0]}" class="main" data-idx="0" />`;
    }
    if (images.length === 2) {
        return images.map((img, i) =>
            `<img src="${img}" class="${i === currentIdx ? 'main' : ''}" data-idx="${i}" />`
        ).join('');
    }
    // ٣+ صور — نعرض السابقة، الحالية main، التالية
    const total = images.length;
    const left = (currentIdx - 1 + total) % total;
    const right = (currentIdx + 1) % total;
    return [
        `<img src="${images[left]}" data-idx="${left}" />`,
        `<img src="${images[currentIdx]}" class="main" data-idx="${currentIdx}" />`,
        `<img src="${images[right]}" data-idx="${right}" />`,
    ].join('');
}

// ===== DETAILS VIEW =====
export function renderDetails(rec) {
    const content = document.getElementById("content");
    const name = rec.name || rec.title || 'المكان';
    const desc = rec.description || '';
    const cat = categoryLabel(rec);
    const mapsUrl = rec.maps_url || `https://www.google.com/maps/search/${encodeURIComponent(name)}`;

    // الجاليري: نأخذ images array، أو نرجع للصورة الواحدة، وإلا placeholder حسب التصنيف
    let images = (rec.images && rec.images.length) ? rec.images : (rec.image ? [rec.image] : []);
    if (!images.length) images = [buildPlaceholder(rec)];
    // نخزّن كل الصور على عنصر الجاليري عشان app.js يقدر يقرأها للتنقل
    const allImagesAttr = encodeURIComponent(JSON.stringify(images));
    // نبدأ بالصورة الوسطى (لو فردي) أو الأولى
    const initialIdx = images.length >= 3 ? Math.floor(images.length / 2) : 0;

    content.innerHTML = `
        <div class="details-view">
            <div class="details-card">
                <h1 class="details-title">${name}</h1>
                <div class="details-gallery" data-images="${allImagesAttr}" data-current="${initialIdx}">
                    ${buildGalleryHTML(images, initialIdx)}
                </div>
                <p class="details-desc">${desc}</p>
                ${cat ? `<div class="details-category">${cat}</div>` : ''}
                <div class="details-actions">
                    <a href="${mapsUrl}" target="_blank" rel="noopener" class="btn-outline">فتح في الخريطة</a>
                </div>
            </div>
            <button class="btn-outline center-btn" id="backBtn">رجوع</button>
        </div>
    `;
}

// ===== LIST VIEW =====
export function renderList(recommendations) {
    const content = document.getElementById("content");

    content.innerHTML = `
        <div class="list-view">
            <h1 class="title">جميع الاقتراحات</h1>
            <div class="list-scroll">
                ${recommendations.map(rec => {
                    const name = rec.name || 'مكان';
                    const cat = categoryLabel(rec);
                    const img = rec.image || buildPlaceholder(rec);
                    // QR يحمل رابط الخرائط (أو بحث Google عن الاسم لو ما فيه رابط)
                    const qrPayload = rec.maps_url || `https://www.google.com/maps/search/${encodeURIComponent(name)}`;
                    const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=160x160&margin=0&data=${encodeURIComponent(qrPayload)}`;
                    return `
                    <div class="list-card" data-id="${rec.id}">
                        <img class="place-img" src="${img}" alt="${name}" />
                        <div class="text">
                            <h2>${name}</h2>
                            ${cat ? `<div class="cat">${cat}</div>` : ''}
                        </div>
                        <div class="qr"><img src="${qrUrl}" alt="QR" /></div>
                    </div>
                    `;
                }).join("")}
            </div>
            <button class="btn-outline center-btn" id="backBtn">رجوع</button>
        </div>
    `;
}