/**
 * Video Downloader - Premium Frontend Logic
 */

let currentVideoData = null;
let currentMode = 'video_audio';
let selectedVideoQuality = 'best';
let selectedAudioQuality = 'best';
let selectedAudioFormat = 'mp3';
let currentTaskId = null;

let playlistItems = [];
let downloadQueue = [];
let isBatchDownloading = false;

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    loadHistory();
    setupInputListeners();

    // Uygulama surumu kontrolu arka planda; sonuc gelene kadar bekle.
    // Ayni surum icin tekrar tekrar rahatsiz etme.
    setTimeout(async () => {
        try {
            const s = await (await fetch('/api/update/status')).json();
            if (!s.app_update) return;
            if (localStorage.getItem('vd_update_seen') === s.app_update.version) return;
            localStorage.setItem('vd_update_seen', s.app_update.version);
            // Otomatik guncelleme acikken kullaniciya is dusmuyor; sadece bilgi ver.
            showToast(s.auto_update !== false
                ? 'v' + s.app_update.version + ' indiriliyor — bir dahaki açılışta kurulacak'
                : 'Yeni sürüm var: v' + s.app_update.version +
                  ' — Ayarlar\'dan güncelleyebilirsiniz', 'info');
        } catch (e) { /* cevrimdisi */ }
    }, 6000);

    // Load theme
    const theme = localStorage.getItem('vd_theme') || 'dark';
    document.body.setAttribute('data-theme', theme);
    document.getElementById('themeSelect').value = theme;
    
    // Send tray setting to backend
    setTimeout(() => {
        if (window.pywebview && window.pywebview.api) {
            const isTray = localStorage.getItem('vd_tray') === 'true';
            document.getElementById('trayToggle').checked = isTray;
            window.pywebview.api.set_minimize_to_tray(isTray);
        }
    }, 1000);
});

// Setup Input behaviors
function setupInputListeners() {
    const input = document.getElementById('urlInput');
    const clearBtn = document.getElementById('clearBtn');
    
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') fetchVideoInfo();
    });

    input.addEventListener('input', () => {
        clearBtn.style.display = input.value.trim() ? 'flex' : 'none';
        
        // Auto-fetch if pasted a valid looking url
        const val = input.value.trim();
        if (val.match(/^https?:\/\/.+/)) {
            // Optional: trigger auto-fetch after a slight delay
            // clearTimeout(window.autoFetchTimeout);
            // window.autoFetchTimeout = setTimeout(fetchVideoInfo, 1000);
        }
    });
}

function clearInput() {
    const input = document.getElementById('urlInput');
    input.value = '';
    document.getElementById('clearBtn').style.display = 'none';
    input.focus();
}

async function pasteFromClipboard() {
    try {
        const text = await navigator.clipboard.readText();
        if (text) {
            const input = document.getElementById('urlInput');
            input.value = text;
            document.getElementById('clearBtn').style.display = 'flex';
            if (text.match(/^https?:\/\/.+/)) {
                fetchVideoInfo();
            } else {
                showToast('Panodaki metin bir URL değil.', 'info');
            }
        }
    } catch (err) {
        showToast('Panodan yapıştırma izni reddedildi veya desteklenmiyor.', 'error');
    }
}

// ===== SETTINGS =====
function openSettings() {
    document.getElementById('settingsModal').style.display = 'flex';
    document.getElementById('themeSelect').value = localStorage.getItem('vd_theme') || 'dark';
    document.getElementById('trayToggle').checked = localStorage.getItem('vd_tray') === 'true';
    refreshUpdateStatus();
}

// ===== GUNCELLEME =====

let appUpdateInfo = null;

async function refreshUpdateStatus() {
    try {
        const r = await fetch('/api/update/status');
        const s = await r.json();

        document.getElementById('appVersionLabel').textContent = 'v' + s.app_version;
        const ytLabel = document.getElementById('ytdlpVersionLabel');
        ytLabel.textContent = s.ytdlp_version || 'bilinmiyor';
        // Paket ici kopya guncellenemez; kullaniciya bunu belli et
        ytLabel.title = s.ytdlp_source || '';

        document.getElementById('autoUpdateToggle').checked = s.auto_update !== false;
        document.getElementById('impersonationWarn').style.display =
            s.impersonation === false ? '' : 'none';

        appUpdateInfo = s.app_update;
        const btn = document.getElementById('appUpdateBtn');
        const hint = document.getElementById('updateHint');
        if (s.staged_version) {
            // Otomatik guncelleme indirmeyi bitirmis: kurulum bir sonraki
            // acilista kendiliginden yapilacak.
            btn.style.display = '';
            btn.classList.add('is-highlight');
            btn.textContent = 'Şimdi kur';
            hint.textContent = 'v' + s.staged_version + ' indirildi. Uygulamayı ' +
                'bir dahaki açışınızda kendiliğinden kurulacak.';
        } else if (appUpdateInfo) {
            btn.style.display = '';
            btn.classList.add('is-highlight');
            btn.textContent = 'v' + appUpdateInfo.version + ' yükle';
            hint.textContent = s.auto_update === false
                ? 'Yeni sürüm hazır: v' + appUpdateInfo.version +
                  '. İndirilip kurulum başlatılacak, uygulama kapanacak.'
                : 'Yeni sürüm indiriliyor: v' + appUpdateInfo.version +
                  '. İndirme bitince bir dahaki açılışta kurulacak.';
        } else {
            btn.style.display = 'none';
        }
    } catch (e) {
        // Cevrimdisi olabilir; ayarlar penceresi yine de acilmali
    }
}

async function updateYtdlp() {
    const btn = document.getElementById('ytdlpUpdateBtn');
    const hint = document.getElementById('updateHint');
    btn.disabled = true;
    btn.textContent = 'Denetleniyor...';
    try {
        const r = await fetch('/api/update/ytdlp', { method: 'POST' });
        const res = await r.json();
        hint.textContent = res.message;
        if (res.restart_required) {
            document.getElementById('ytdlpVersionLabel').classList.add('is-new');
            showToast('yt-dlp güncellendi — yeniden başlatınca devreye girecek', 'success');
        } else {
            showToast(res.message, 'info');
        }
    } catch (e) {
        showToast('Güncelleme kontrolü başarısız', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Denetle';
    }
}

async function installAppUpdate() {
    if (!appUpdateInfo) return;
    const btn = document.getElementById('appUpdateBtn');
    btn.disabled = true;
    btn.textContent = 'İndiriliyor...';
    showToast('Güncelleme indiriliyor, bu biraz sürebilir...', 'info');
    try {
        const r = await fetch('/api/update/app', { method: 'POST' });
        const res = await r.json();
        if (res.error) {
            showToast(res.error, 'error');
            btn.disabled = false;
            btn.textContent = 'Yeniden dene';
        } else {
            btn.textContent = 'Kurulum açılıyor...';
        }
    } catch (e) {
        showToast('Güncelleme indirilemedi', 'error');
        btn.disabled = false;
        btn.textContent = 'Yeniden dene';
    }
}
function closeSettings() {
    document.getElementById('settingsModal').style.display = 'none';
}
function changeTheme() {
    const theme = document.getElementById('themeSelect').value;
    localStorage.setItem('vd_theme', theme);
    document.body.setAttribute('data-theme', theme);
}
async function toggleAutoUpdate() {
    const enabled = document.getElementById('autoUpdateToggle').checked;
    try {
        await fetch('/api/update/auto', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        });
        showToast(enabled
            ? 'Güncellemeler otomatik kurulacak'
            : 'Otomatik güncelleme kapatıldı', 'info');
    } catch (e) {
        showToast('Ayar kaydedilemedi', 'error');
    }
}

function toggleTray() {
    const isTray = document.getElementById('trayToggle').checked;
    localStorage.setItem('vd_tray', isTray);
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.set_minimize_to_tray(isTray);
    }
}

// ===== TOAST SYSTEM =====
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    let icon = '';
    if (type === 'error') icon = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
    else if (type === 'success') icon = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
    else icon = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';

    toast.innerHTML = `${icon} <span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('hiding');
        toast.addEventListener('animationend', () => toast.remove());
    }, 4000);
}

// ===== LOGIN PROMPT (giriş gerektiren içerik) =====
// Giriş sayfası linkin platformuna göre açılır; TikTok linkinde Instagram
// giriş sayfası açmak işe yaramıyordu.
function showLoginPrompt(data) {
    const platform = (data && data.login_platform) || 'Platform';
    const loginUrl = (data && data.login_url) || '';
    const hint = (data && data.login_hint) || '';
    const container = document.getElementById('toastContainer');
    const t = document.createElement('div');
    t.className = 'toast toast-info';
    t.style.flexWrap = 'wrap';

    const span = document.createElement('span');
    span.textContent = `Bu içerik ${platform} girişi gerektiriyor.` +
        (hint ? ' ' + hint : '');

    const btnStyle = 'margin-left:8px;padding:6px 14px;border-radius:8px;border:none;cursor:pointer;font-weight:600;font-size:13px;';
    const loginBtn = document.createElement('button');
    loginBtn.textContent = `${platform} Giriş Yap`;
    loginBtn.style.cssText = btnStyle + 'background:linear-gradient(135deg,#8b5cf6,#6366f1);color:#fff;';
    loginBtn.onclick = () => openLoginWindow(t, loginUrl, platform);

    // Tarayicisinda zaten girisi olanlar icin kacis yolu: uygulama
    // cerezleri kurulu tarayicilardan da okuyabiliyor.
    const retryBtn = document.createElement('button');
    retryBtn.textContent = 'Tarayıcımdan girdim, tekrar dene';
    retryBtn.style.cssText = btnStyle + 'background:rgba(255,255,255,0.12);color:inherit;';
    retryBtn.onclick = () => { t.remove(); fetchVideoInfo(); };

    t.appendChild(span);
    t.appendChild(loginBtn);
    t.appendChild(retryBtn);
    container.appendChild(t);
    setTimeout(() => t.remove(), 120000);
}

async function openLoginWindow(toast, loginUrl, platform) {
    if (toast && toast.remove) toast.remove();
    showToast('Giriş penceresi açıldı. Giriş yaptıktan sonra pencereyi kapatın.', 'info');
    try {
        const saved = await window.pywebview.api.open_login(loginUrl || '');
        if (saved === 0) {
            // Pencere kapandi ama hic cerez yakalanmadi: giris tamamlanmamis.
            // Kullaniciyi bosta birakma, calisan yolu goster.
            showToast('Giriş algılanmadı. QR kodla deneyin ya da tarayıcınızda ' +
                      (platform || 'siteye') + ' girip tekrar deneyin — ' +
                      'uygulama çerezleri tarayıcınızdan da okur.', 'error');
            return;
        }
        showToast('Giriş kaydedildi, video bilgisi tekrar alınıyor...', 'success');
        fetchVideoInfo();
    } catch (e) {
        showToast('Giriş penceresi açılamadı.', 'error');
    }
}

// ===== FETCH VIDEO INFO =====
async function fetchVideoInfo() {
    const url = document.getElementById('urlInput').value.trim();
    if (!url) { showToast('Lütfen bir video bağlantısı yapıştırın', 'error'); return; }

    hideSection('videoInfo');
    hideSection('downloadProgress');
    hideSection('successMessage');
    setLoading(true);

    try {
        const res = await fetch('/api/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        const data = await res.json();
        if (!res.ok) {
            if (data.needs_login && window.pywebview && window.pywebview.api) {
                showLoginPrompt(data);
            } else {
                showToast(data.error || 'Video bilgisi alınamadı.', 'error');
            }
            setLoading(false);
            return;
        }

        currentVideoData = data;
        renderVideoInfo(data);
        showSection('videoInfo');
        
        // Scroll to video info smoothly
        setTimeout(() => {
            document.getElementById('videoInfo').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 100);

    } catch (err) {
        showToast('Sunucuya bağlanılamadı. Uygulamanın çalıştığından emin olun.', 'error');
    }
    setLoading(false);
}

// ===== RENDER VIDEO INFO =====
function renderVideoInfo(data) {
    document.getElementById('videoThumbnail').src = data.thumbnail || '';
    document.getElementById('videoTitle').textContent = data.title;
    document.getElementById('platformTag').textContent = data.platform;
    document.getElementById('videoUploader').querySelector('span').textContent = data.uploader || 'Bilinmeyen';

    const viewsEl = document.getElementById('videoViews');
    if (data.view_count) {
        viewsEl.querySelector('span').textContent = formatNumber(data.view_count);
        viewsEl.style.display = 'flex';
    } else {
        viewsEl.style.display = 'none';
    }

    if (data.duration) {
        document.getElementById('videoDuration').textContent = formatDuration(data.duration);
        document.getElementById('videoDuration').style.display = 'block';
    } else {
        document.getElementById('videoDuration').style.display = 'none';
    }

    // Playlist rendering
    if (data.is_playlist && data.playlist_items && data.playlist_items.length > 0) {
        playlistItems = data.playlist_items;
        document.getElementById('playlistSection').style.display = 'block';
        document.getElementById('trimmerGroup').style.display = 'none'; // Trimming disabled for batch
        
        const pc = document.getElementById('playlistContainer');
        pc.innerHTML = '';
        playlistItems.forEach((item, idx) => {
            const div = document.createElement('div');
            div.className = 'setting-item';
            div.style.padding = '8px'; div.style.marginBottom = '4px'; div.style.border = 'none'; 
            div.style.background = 'rgba(0,0,0,0.2)'; div.style.borderRadius = '8px';
            div.innerHTML = `
                <div style="display:flex; align-items:center; gap:10px; overflow:hidden;">
                    <input type="checkbox" class="playlist-cb" value="${idx}" checked>
                    <span style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:14px;">${item.title}</span>
                </div>
                <span style="font-size:12px; color:var(--text-muted);">${formatDuration(item.duration)}</span>
            `;
            pc.appendChild(div);
        });
    } else {
        playlistItems = [];
        document.getElementById('playlistSection').style.display = 'none';
        document.getElementById('trimmerGroup').style.display = 'block';
    }

    // Reset mode to video_audio
    selectMode('video_audio');
}

function selectAllPlaylist(check) {
    document.querySelectorAll('.playlist-cb').forEach(cb => cb.checked = check);
}

// ===== MODE SELECTION =====
function selectMode(mode) {
    currentMode = mode;

    document.querySelectorAll('.mode-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.mode === mode);
    });

    const videoQG = document.getElementById('videoQualityGroup');
    const audioQG = document.getElementById('audioQualityGroup');
    const audioFG = document.getElementById('audioFormatGroup');

    if (mode === 'audio_only') {
        videoQG.style.display = 'none';
        audioQG.style.display = 'block';
        audioFG.style.display = 'block';
        renderAudioQualities();
        renderAudioFormats();
    } else {
        videoQG.style.display = 'block';
        audioQG.style.display = 'none';
        audioFG.style.display = 'none';
        renderVideoQualities();
    }
}

// ===== RENDER QUALITIES =====
function renderVideoQualities() {
    const grid = document.getElementById('videoQualityGrid');
    grid.innerHTML = '';

    if (!currentVideoData || !currentVideoData.video_qualities || currentVideoData.video_qualities.length === 0) {
        const btn = createQualityBtn('Otomatik (En İyi)', 'best', true);
        grid.appendChild(btn);
        selectedVideoQuality = 'best';
        return;
    }

    const bestBtn = createQualityBtn('Otomatik (En İyi)', 'best', true);
    grid.appendChild(bestBtn);
    selectedVideoQuality = 'best';

    currentVideoData.video_qualities.forEach(q => {
        let label = q.quality_label;
        let hdBadge = '';
        if (q.height >= 2160) hdBadge = '4K';
        else if (q.height >= 1440) hdBadge = '2K';
        else if (q.height >= 1080) hdBadge = 'FHD';
        else if (q.height >= 720) hdBadge = 'HD';

        const btn = createQualityBtn(label, q.height, false, hdBadge);
        grid.appendChild(btn);
    });
}

function renderAudioQualities() {
    const grid = document.getElementById('audioQualityGrid');
    grid.innerHTML = '';

    const bestBtn = createQualityBtn('Otomatik (En İyi)', 'best', true, '', 'audio');
    grid.appendChild(bestBtn);
    selectedAudioQuality = 'best';

    if (currentVideoData && currentVideoData.audio_formats) {
        currentVideoData.audio_formats.forEach(a => {
            const btn = createQualityBtn(a.quality_label, a.abr, false, '', 'audio');
            grid.appendChild(btn);
        });
    }
}

function renderAudioFormats() {
    const grid = document.getElementById('audioFormatGrid');
    grid.innerHTML = '';

    const formats = [
        { label: 'MP3', value: 'mp3' },
        { label: 'M4A (AAC)', value: 'm4a' },
        { label: 'WAV', value: 'wav' },
        { label: 'OPUS', value: 'opus' },
        { label: 'FLAC', value: 'flac' }
    ];

    formats.forEach((f, i) => {
        const btn = createQualityBtn(f.label, f.value, i === 0, '', 'format');
        grid.appendChild(btn);
    });
    selectedAudioFormat = 'mp3';
}

function createQualityBtn(label, value, active = false, hdBadge = '', type = 'video') {
    const btn = document.createElement('button');
    btn.className = 'quality-btn' + (active ? ' active' : '');
    btn.innerHTML = label + (hdBadge ? `<span class="badge-hd">${hdBadge}</span>` : '');
    btn.onclick = () => {
        const parent = btn.parentElement;
        parent.querySelectorAll('.quality-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        if (type === 'audio') selectedAudioQuality = value;
        else if (type === 'format') selectedAudioFormat = value;
        else selectedVideoQuality = value;
    };
    return btn;
}

// ===== DOWNLOAD =====
async function startDownload() {
    if (!currentVideoData) return;

    if (playlistItems.length > 0) {
        const checkedBoxes = document.querySelectorAll('.playlist-cb:checked');
        if (checkedBoxes.length === 0) { showToast('Lütfen listeden en az bir video seçin.', 'warning'); return; }
        
        downloadQueue = Array.from(checkedBoxes).map(cb => playlistItems[cb.value]);
        isBatchDownloading = true;
        
        document.getElementById('downloadBtn').disabled = true;
        hideSection('successMessage');
        showSection('downloadProgress');
        document.getElementById('downloadProgress').scrollIntoView({ behavior: 'smooth', block: 'end' });
        
        processDownloadQueue();
        return;
    }

    // Single download
    await triggerSingleDownload(document.getElementById('urlInput').value.trim());
}

async function triggerSingleDownload(url) {
    const downloadBtn = document.getElementById('downloadBtn');
    if(!isBatchDownloading) {
        downloadBtn.disabled = true;
        hideSection('successMessage');
    }

    const payload = {
        url: url,
        mode: currentMode,
        quality: currentMode !== 'audio_only' ? String(selectedVideoQuality) : 'best',
        audio_quality: currentMode === 'audio_only' ? String(selectedAudioQuality) : 'best',
        audio_format: selectedAudioFormat,
        start_time: isBatchDownloading ? '' : document.getElementById('trimStart').value.trim(),
        end_time: isBatchDownloading ? '' : document.getElementById('trimEnd').value.trim()
    };

    try {
        const res = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) { 
            showToast(data.error || 'İndirme başlatılamadı', 'error'); 
            if(!isBatchDownloading) downloadBtn.disabled = false;
            else processDownloadQueue();
            return; 
        }

        currentTaskId = data.task_id;
        if(!isBatchDownloading) {
            showSection('downloadProgress');
            document.getElementById('downloadProgress').scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
        trackProgress(data.task_id);
    } catch (err) {
        showToast('İndirme başlatılamadı: ' + err.message, 'error');
        if(!isBatchDownloading) downloadBtn.disabled = false;
        else processDownloadQueue();
    }
}

function processDownloadQueue() {
    if (downloadQueue.length === 0) {
        isBatchDownloading = false;
        document.getElementById('downloadBtn').disabled = false;
        showToast('Toplu indirme tamamlandı!', 'success');
        document.getElementById('successFilename').textContent = "Seçilen tüm dosyalar indirildi.";
        showSection('successMessage');
        // Hide individual save button for batch downloads to avoid confusion
        document.getElementById('saveFileBtn').style.display = 'none'; 
        return;
    }
    
    document.getElementById('saveFileBtn').style.display = 'inline-flex';
    const nextItem = downloadQueue.shift();
    document.getElementById('progressPercent').textContent = '0%';
    document.getElementById('progressBar').style.width = '0%';
    document.getElementById('progressSpeed').textContent = `Sıradaki: ${nextItem.title}`;
    document.getElementById('progressEta').textContent = '';
    
    triggerSingleDownload(nextItem.url);
}

// ===== PROGRESS TRACKING =====
function trackProgress(taskId) {
    const evtSource = new EventSource(`/api/progress/${taskId}`);

    evtSource.onmessage = (event) => {
        const progress = JSON.parse(event.data);
        updateProgressUI(progress);

        if (progress.status === 'completed') {
            evtSource.close();
            
            // Add to history
            addToHistory({
                title: progress.title || progress.filename || 'İndirilen Dosya',
                platform: currentVideoData ? currentVideoData.platform : 'Bilinmeyen',
                thumbnail: currentVideoData ? currentVideoData.thumbnail : '',
                date: new Date().toISOString()
            });

            if (isBatchDownloading) {
                processDownloadQueue();
            } else {
                hideSection('downloadProgress');
                showSuccess(progress);
                document.getElementById('downloadBtn').disabled = false;
            }
        } else if (progress.status === 'error') {
            evtSource.close();
            showToast(progress.error || 'İndirme sırasında hata oluştu', 'error');
            
            if (isBatchDownloading) {
                processDownloadQueue();
            } else {
                hideSection('downloadProgress');
                document.getElementById('downloadBtn').disabled = false;
            }
        }
    };

    evtSource.onerror = () => {
        evtSource.close();
        pollProgress(taskId);
    };
}

async function pollProgress(taskId) {
    try {
        const res = await fetch(`/api/progress/${taskId}`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const progress = JSON.parse(line.slice(6));
                    updateProgressUI(progress);

                    if (progress.status === 'completed') {
                        addToHistory({
                            title: progress.title || progress.filename || 'İndirilen Dosya',
                            platform: currentVideoData ? currentVideoData.platform : 'Bilinmeyen',
                            thumbnail: currentVideoData ? currentVideoData.thumbnail : '',
                            date: new Date().toISOString()
                        });

                        if (isBatchDownloading) {
                            processDownloadQueue();
                        } else {
                            hideSection('downloadProgress');
                            showSuccess(progress);
                            document.getElementById('downloadBtn').disabled = false;
                        }
                        return;
                    } else if (progress.status === 'error') {
                        showToast(progress.error || 'İndirme sırasında hata oluştu', 'error');
                        if (isBatchDownloading) processDownloadQueue();
                        else {
                            hideSection('downloadProgress');
                            document.getElementById('downloadBtn').disabled = false;
                        }
                        return;
                    }
                }
            }
        }
    } catch (err) {
        showToast('İlerleme takibi başarısız', 'error');
        if (isBatchDownloading) processDownloadQueue();
        else document.getElementById('downloadBtn').disabled = false;
    }
}

function updateProgressUI(progress) {
    const pct = progress.percent || 0;
    document.getElementById('progressPercent').textContent = pct + '%';
    document.getElementById('progressBar').style.width = pct + '%';

    if (progress.speed) {
        document.getElementById('progressSpeed').textContent = formatBytes(progress.speed) + '/sn';
    }
    if (progress.eta) {
        document.getElementById('progressEta').textContent = 'Kalan: ' + formatDuration(progress.eta);
    }
    if (progress.message) {
        document.getElementById('progressSpeed').textContent = progress.message;
        document.getElementById('progressEta').textContent = '';
    }
}

// ===== SUCCESS, FILE SAVE & HISTORY =====
function showSuccess(progress) {
    document.getElementById('successFilename').textContent = progress.title || progress.filename || 'İndirilen Dosya';
    showSection('successMessage');
    showToast('İndirme tamamlandı!', 'success');
}

async function saveFile() {
    if (!currentTaskId) return;
    
    if (window.pywebview && window.pywebview.api) {
        try {
            const success = await window.pywebview.api.save_file_dialog(currentTaskId);
            if (!success) {
                console.log("Kullanıcı kaydetmeyi iptal etti veya bir hata oluştu.");
            } else {
                showToast('Dosya başarıyla kaydedildi.', 'success');
            }
            return;
        } catch (e) {
            console.error("Native save failed:", e);
        }
    }
    
    const link = document.createElement('a');
    link.href = `/api/file/${currentTaskId}`;
    link.download = '';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ===== HISTORY MANAGEMENT =====
function loadHistory() {
    const historySection = document.getElementById('historySection');
    const historyList = document.getElementById('historyList');
    
    let history = [];
    try { history = JSON.parse(localStorage.getItem('vd_history')) || []; } 
    catch(e) { history = []; }
    
    if (history.length === 0) {
        historySection.style.display = 'none';
        return;
    }
    
    historySection.style.display = 'block';
    historyList.innerHTML = '';
    
    history.forEach(item => {
        const date = new Date(item.date).toLocaleDateString('tr-TR', { day: 'numeric', month: 'short', hour: '2-digit', minute:'2-digit' });
        const div = document.createElement('div');
        div.className = 'history-item';
        div.innerHTML = `
            ${item.thumbnail ? `<img src="${item.thumbnail}" class="history-thumb" alt="thumb">` : '<div class="history-thumb" style="background:#222"></div>'}
            <div class="history-details">
                <div class="history-title" title="${item.title}">${item.title}</div>
                <div class="history-meta">${item.platform} • ${date}</div>
            </div>
        `;
        historyList.appendChild(div);
    });
}

function addToHistory(item) {
    let history = [];
    try { history = JSON.parse(localStorage.getItem('vd_history')) || []; } 
    catch(e) { history = []; }
    
    history.unshift(item);
    if (history.length > 5) history = history.slice(0, 5); // Keep last 5
    
    localStorage.setItem('vd_history', JSON.stringify(history));
    loadHistory();
}

function clearHistory() {
    localStorage.removeItem('vd_history');
    loadHistory();
    showToast('Geçmiş temizlendi', 'info');
}

// ===== HELPERS =====
function showSection(id) {
    document.getElementById(id).style.display = 'block';
}

function hideSection(id) {
    document.getElementById(id).style.display = 'none';
}

function setLoading(loading) {
    const btn = document.getElementById('fetchBtn');
    const text = btn.querySelector('.btn-text');
    const loader = btn.querySelector('.btn-loader');
    const arrow = btn.querySelector('.btn-arrow');
    btn.disabled = loading;
    text.style.display = loading ? 'none' : 'inline';
    if(arrow) arrow.style.display = loading ? 'none' : 'inline';
    loader.style.display = loading ? 'inline-flex' : 'none';
}

function formatDuration(seconds) {
    if (!seconds) return '';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    return `${m}:${String(s).padStart(2,'0')}`;
}

function formatNumber(num) {
    if (!num) return '0';
    if (num >= 1e9) return (num / 1e9).toFixed(1) + 'B';
    if (num >= 1e6) return (num / 1e6).toFixed(1) + 'M';
    if (num >= 1e3) return (num / 1e3).toFixed(1) + 'K';
    return String(num);
}

function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + sizes[i];
}
