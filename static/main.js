/**
 * SnapLoad - Ultimate Dynamic JS
 * Z-Generation Style with Micro-interactions
 * Powered by AOS (Animate On Scroll)
 */

// ===================================
// パーティクル背景（マウス追従）
// ===================================
function createParticles() {
    const particleCount = 40;
    const body = document.body;
    const particles = [];

    for (let i = 0; i < particleCount; i++) {
        const p = document.createElement('div');
        p.className = 'particle';
        const size = (2 + Math.random() * 5);
        p.style.width = size + 'px';
        p.style.height = size + 'px';

        const x = Math.random() * window.innerWidth;
        const y = Math.random() * window.innerHeight;

        p.style.left = x + 'px';
        p.style.top = y + 'px';
        p.style.opacity = (0.1 + Math.random() * 0.4);

        body.appendChild(p);
        particles.push({
            el: p,
            x: x,
            y: y,
            vx: (Math.random() - 0.5) * 0.5,
            vy: (Math.random() - 0.5) * 0.5
        });
    }

    // アニメーションループ
    function update() {
        particles.forEach(p => {
            p.x += p.vx;
            p.y += p.vy;

            if (p.x < 0) p.x = window.innerWidth;
            if (p.x > window.innerWidth) p.x = 0;
            if (p.y < 0) p.y = window.innerHeight;
            if (p.y > window.innerHeight) p.y = 0;

            p.el.style.transform = `translate(${p.x}px, ${p.y}px)`;
        });
        requestAnimationFrame(update);
    }
    update();
}

// ===================================
// マグネティック（磁石）ボタン
// ===================================
function setupMagneticButtons() {
    const buttons = document.querySelectorAll('.download-btn, .youtube-btn, .header-link, .btn-mini, .logo-link');

    buttons.forEach(btn => {
        btn.addEventListener('mousemove', e => {
            const rect = btn.getBoundingClientRect();
            const x = e.clientX - rect.left - rect.width / 2;
            const y = e.clientY - rect.top - rect.height / 2;

            btn.style.transform = `translate(${x * 0.3}px, ${y * 0.3}px)`;
        });

        btn.addEventListener('mouseleave', () => {
            btn.style.transform = '';
        });
    });
}

// ===================================
// 入力バリデーション & フィードバック
// ===================================
function setupInputFeedback() {
    const urlInput = document.getElementById('url');
    const clearBtn = document.getElementById('clear-url');
    const pasteBtn = document.getElementById('paste-url');

    if (!urlInput) return;

    // バリデーション検知
    const checkValidation = () => {
        const val = urlInput.value.trim();
        const wrapper = urlInput.closest('.input-wrapper');

        if (val.includes('youtube.com/') || val.includes('youtu.be/')) {
            wrapper.classList.add('valid-glow');
        } else {
            wrapper.classList.remove('valid-glow');
        }
    };

    urlInput.addEventListener('input', checkValidation);

    // 消去ボタン
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            urlInput.value = '';
            urlInput.focus();
            checkValidation();
            showToast('入力をクリアしました', 'info');
        });
    }

    // 貼り付けボタン
    if (pasteBtn) {
        pasteBtn.addEventListener('click', async () => {
            try {
                const text = await navigator.clipboard.readText();
                urlInput.value = text;
                urlInput.focus();
                checkValidation();
                showToast('クリップボードから貼り付けました', 'success');
            } catch (err) {
                showToast('貼り付けに失敗しました。ブラウザの権限を確認してください。', 'error');
            }
        });
    }
}

// ===================================
// 通知 (改良版)
// ===================================
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast-notification toast-${type}`;

    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        info: 'fa-info-circle'
    };

    toast.innerHTML = `<i class="fas ${icons[type]}"></i> <span>${message}</span>`;
    document.body.appendChild(toast);

    setTimeout(() => toast.classList.add('show'), 10);

    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 500);
    }, 4000);
}

// ===================================
// リップル（波紋）エフェクト
// ===================================
function setupRippleEffect() {
    document.addEventListener('click', e => {
        const btn = e.target.closest('button, .btn, .header-link, .logo-link');
        if (!btn) return;

        const ripple = document.createElement('span');
        ripple.className = 'ripple';

        const rect = btn.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const x = e.clientX - rect.left - size / 2;
        const y = e.clientY - rect.top - size / 2;

        ripple.style.width = ripple.style.height = size + 'px';
        ripple.style.left = x + 'px';
        ripple.style.top = y + 'px';

        btn.appendChild(ripple);
        setTimeout(() => ripple.remove(), 600);
    });
}

// ===================================
// iTyped (タイピング演出)
// ===================================
function setupITyped() {
    const subtitle = document.querySelector('#ityped-subtitle');
    if (subtitle && typeof ityped !== 'undefined') {
        ityped.init(subtitle, {
            strings: [
                'SnapLoad - Free YouTube Downloader',
                'Download in 4K Quality',
                'Supports Playlists & MP3',
                'Fast & Secure Download',
                'No Registration Required'
            ],
            typeSpeed: 100,
            backSpeed: 50,
            startDelay: 500,
            backDelay: 1500,
            loop: true,
            showCursor: true,
            placeholder: false,
            disableBackTyping: false
        });
    }
}

// ===================================
// 法的同意の確認 (SweetAlert2)
// ===================================
async function checkLegalAgreements() {
    const hasAgreed = localStorage.getItem('snapload_legal_agreed');

    if (!hasAgreed) {
        const { value: accept } = await Swal.fire({
            title: 'Welcome to SnapLoad',
            html: `
                <div style="text-align: left; font-size: 0.95rem; line-height: 1.6; color: #1e293b;">
                    <p>このサービスを利用するには、以下の内容に同意していただく必要があります：</p>
                    <ul style="margin-top: 10px; margin-left: 20px;">
                        <li><strong>利用規約:</strong> 著作権を尊重し、個人利用の範囲内でのみ使用すること。</li>
                        <li><strong>Cookieの使用:</strong> 快適な操作性と設定保存のためにCookieおよびローカルストレージを使用すること。</li>
                    </ul>
                    <p style="margin-top: 15px; font-size: 0.8rem; color: #64748b;">
                        ※本サービスは教育的・個人的な研究目的で提供されています。
                    </p>
                </div>
            `,
            icon: 'info',
            input: 'checkbox',
            inputValue: 0,
            inputPlaceholder: '利用規約とCookieの使用に同意します',
            confirmButtonText: 'スタート <i class="fas fa-arrow-right"></i>',
            confirmButtonColor: '#764ba2',
            allowOutsideClick: false,
            allowEscapeKey: false,
            inputValidator: (result) => {
                return !result && 'サービスを利用するには同意が必要です！'
            }
        });

        if (accept) {
            localStorage.setItem('snapload_legal_agreed', 'true');
            Swal.fire({
                title: '同意ありがとうございます！',
                text: 'SnapLoadで最高のダウンロード体験を。',
                icon: 'success',
                timer: 2000,
                showConfirmButton: false
            });
        }
    }
}

// ===================================
// 初期化
// ===================================
document.addEventListener('DOMContentLoaded', () => {
    document.body.classList.add('loaded');

    // AOS Initialize
    if (typeof AOS !== 'undefined') {
        AOS.init({
            duration: 800,
            easing: 'cubic-bezier(0.23, 1, 0.32, 1)',
            once: true,
            mirror: false
        });
    }

    checkLegalAgreements();
    setupITyped();
    createParticles();
    setupMagneticButtons();
    setupInputFeedback();
    setupRippleEffect();

    console.log('✨ SnapLoad Ultimate Dynamic JS with AOS & iTyped Initialized');
});

/**
 * テキストをクリップボードにコピー
 * @param {string} text
 */
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('URLをコピーしました！', 'success');
    }).catch(err => {
        console.error('Failed to copy: ', err);
        showToast('コピーに失敗しました', 'error');
    });
}

/**
 * 使い方セクションの表示・非表示を切り替え
 */
function toggleInstructions() {
    const content = document.getElementById('instr-content');
    const icon = document.getElementById('instr-icon');

    if (content.style.display === 'none') {
        content.style.display = 'block';
        icon.style.transform = 'rotate(0deg)';
    } else {
        content.style.display = 'none';
        icon.style.transform = 'rotate(-180deg)';
    }
}
