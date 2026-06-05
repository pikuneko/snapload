from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    send_from_directory,
    abort,
    session,
)
from def_FILE import (
    setup_logging,
    load_download_history,
    start_background_download,
    active_tasks,
    get_status_info,
    load_settings,
    save_settings_to_file,
    DEFAULT_SETTINGS,
    generate_task_id,
    _get_task_status,
    run_yt_dlp
)
from werkzeug.security import generate_password_hash, check_password_hash
import sys
import os
import logging
import json
import shutil
import tempfile
from datetime import datetime
from urllib.parse import quote

# BASE_DIRをアプリケーションのルートディレクトリとして定義
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
# セッションのセキュリティ設定
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32).hex()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Strict',
    SESSION_COOKIE_SECURE=True,  # HTTPS時のセキュアクッキー
    PERMANENT_SESSION_LIFETIME=3600,  # 1時間に短縮
    SESSION_REFRESH_EACH_REQUEST=True,
)
APP_VERSION = "v1.4.0"

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    # Content-Security-Policy の基本設定
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://unpkg.com https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com https://unpkg.com; font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; img-src 'self' data:"
    return response

from datetime import datetime, timedelta
from collections import defaultdict

def validate_url(url):
    """URLの妥当性をチェック"""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    # YouTubeとプレイリストのみを許可
    if 'youtube.com' in url or 'youtu.be' in url:
        return True
    return False

# レート制限用の辞書（IP アドレス -> [時刻,...] のリスト）
request_history = defaultdict(list)
RATE_LIMIT_REQUESTS = 20  # 1 時間あたりのリクエスト上限
RATE_LIMIT_WINDOW = 3600  # 1 時間（秒）

def check_rate_limit(ip_address):
    """IP アドレス単位のレート制限をチェック"""
    now = datetime.now()
    cutoff = now - timedelta(seconds=RATE_LIMIT_WINDOW)

    # 古いリクエストを削除
    request_history[ip_address] = [
        req_time for req_time in request_history[ip_address]
        if req_time > cutoff
    ]

    # リクエスト数をチェック
    if len(request_history[ip_address]) >= RATE_LIMIT_REQUESTS:
        return False

    # 現在のリクエストを記録
    request_history[ip_address].append(now)
    return True

@app.context_processor
def inject_version():
    return dict(app_version=APP_VERSION)

# 設定
settings = load_settings()
app.config["HISTORY_FILE"] = os.path.join(BASE_DIR, settings.get("history_file", "JSON/history.json"))
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, settings.get("upload_folder", "downloads"))

if not os.path.exists(app.config["UPLOAD_FOLDER"]):
    os.makedirs(app.config["UPLOAD_FOLDER"])

setup_logging()

# --- 認証チェック ---
@app.before_request
def check_auth():
    # 静的ファイルはスルー
    if request.path.startswith('/static'):
        return

    # 保護対象のルートを定義 (状態を変更するアクションや管理画面)
    protected_endpoints = ['settings_page', 'api_settings', 'admin_dashboard', 'delete_history', 'reset_settings']

    if request.endpoint in protected_endpoints:
        current_settings = load_settings()
        passcode = current_settings.get("passcode")

        # パスコードが設定されている場合のみ認証が必要
        if passcode and len(str(passcode).strip()) > 0:
            if not session.get('authenticated'):
                # AJAXリクエスト (fetch等) の場合はJSONを返す
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({
                        "success": False,
                        "error": "認証が必要です",
                        "redirect": url_for('login', next=url_for('index'))
                    }), 401
                return redirect(url_for('login', next=request.url))

# ログイン試行レート制限（IP アドレス -> [時刻,...] のリスト）
login_attempts = defaultdict(list)
LOGIN_ATTEMPT_LIMIT = 5  # 5 回
LOGIN_ATTEMPT_WINDOW = 900  # 15 分

@app.route('/login', methods=['GET', 'POST'])
def login():
    next_url = request.args.get('next', url_for('index'))
    ip_address = request.remote_addr

    if request.method == 'POST':
        # ログイン試行のレート制限
        now = datetime.now()
        cutoff = now - timedelta(seconds=LOGIN_ATTEMPT_WINDOW)
        login_attempts[ip_address] = [
            attempt_time for attempt_time in login_attempts[ip_address]
            if attempt_time > cutoff
        ]

        if len(login_attempts[ip_address]) >= LOGIN_ATTEMPT_LIMIT:
            logging.warning(f"Login attempt limit exceeded for IP: {ip_address}")
            return render_template('login.html',
                                 error="ログイン試行回数が多すぎます。15 分後に再度お試しください。",
                                 next=next_url), 429

        entered = request.form.get('passcode', '').strip()
        current_settings = load_settings()
        correct_hash = current_settings.get('passcode')

        # ログイン試行を記録
        login_attempts[ip_address].append(now)

        if correct_hash:
            if check_password_hash(correct_hash, entered):
                session['authenticated'] = True
                session.permanent = True
                app.permanent_session_lifetime = timedelta(hours=1)
                return redirect(request.form.get('next') or url_for('index'))

        return render_template('login.html', error="パスコードが正しくありません", next=next_url)
    return render_template('login.html', next=next_url)

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))

# --- 履歴取得 ---
def get_safe_history():
    try:
        history_data = load_download_history()
        items = history_data.get("downloads", []) if isinstance(history_data, dict) else (history_data if isinstance(history_data, list) else [])
        try:
            items.sort(key=lambda x: x.get('download_date', ''), reverse=True)
        except (TypeError, AttributeError) as e:
            logging.warning(f"Failed to sort history: {e}")
        return items
    except Exception as e:
        logging.error(f"Failed to load history: {e}")
        return []

@app.route("/")
def index():
    # 設定を都度読み込む
    current_settings = load_settings()

    if not current_settings.get("show_history", True):
        downloads_list = []
    else:
        downloads_list = get_safe_history()
        # 表示件数の制限
        count = current_settings.get("history_count", 10)
        try:
            count = int(count)
        except (ValueError, TypeError):
            count = 10
        downloads_list = downloads_list[:count]

    return render_template("index.html", history=downloads_list)

@app.route("/", methods=["POST"])
def download_post():
    # レート制限チェック
    ip_address = request.remote_addr
    if not check_rate_limit(ip_address):
        logging.warning(f"Rate limit exceeded for IP: {ip_address}")
        return jsonify({"success": False, "error": "一時的にリクエストが集中しています。少し待ってから再度お試しください。"}), 429

    data = request.get_json() if request.is_json else request.form
    url = data.get("url", "").strip()
    audio_only = data.get("audio_only") in ["on", True, "true"]

    if not url:
        return jsonify({"success": False, "error": "URLを入力してください"}), 400

    # URLバリデーション
    if not validate_url(url):
        logging.warning(f"Invalid URL attempted from {ip_address}: {url[:50]}...")
        return jsonify({"success": False, "error": "YouTubeのURLを入力してください"}), 400

    # URL長チェック
    if len(url) > 2048:
        return jsonify({"success": False, "error": "URLが長すぎます"}), 400

    result = start_background_download(url, audio_only, app.config["UPLOAD_FOLDER"])
    task_id = result.task.task_id
    return jsonify({"success": True, "task_id": task_id, "status_url": url_for("task_status", task_id=task_id)})

@app.route("/task/<task_id>")
def task_status(task_id):
    return render_template("status.html", task_id=task_id)

@app.route("/api/status/<task_id>")
def get_task_status_api(task_id):
    return jsonify(_get_task_status(task_id))


# --- ダウンロード機能（エラー解消版） ---

def load_updates_history():
    readme_path = os.path.join(BASE_DIR, "README.md")

    if os.path.exists(readme_path):
        updates = []
        current = None
        with open(readme_path, 'r', encoding='utf-8') as f:
            for raw_line in f:
                line = raw_line.strip()
                if line.startswith('### '):
                    if current:
                        updates.append(current)
                    header = line[4:].strip()
                    parts = header.split(' - ', 1)
                    version = parts[0].strip()
                    date = parts[1].strip() if len(parts) > 1 else ''
                    current = {
                        'version': version,
                        'date': date,
                        'title': '',
                        'changes': []
                    }
                elif line.startswith('#### ') and current is not None:
                    current['title'] = line[5:].strip()
                elif line.startswith('- ') and current is not None:
                    current['changes'].append(line[2:].strip())
        if current:
            updates.append(current)
        return updates

    updates_path = os.path.join(BASE_DIR, "JSON/updates.json")
    if os.path.exists(updates_path):
        with open(updates_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

@app.route('/history')
def history():
    return render_template("history.html", history=get_safe_history())

@app.route('/api/history/delete', methods=['POST'])
def delete_history():
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        if not file_path:
            return jsonify({"success": False, "error": "file_path is required"}), 400

        settings = load_settings()
        h_file = os.path.join(BASE_DIR, settings.get("history_file", "JSON/history.json"))
        upload_folder = app.config["UPLOAD_FOLDER"]

        if not os.path.exists(h_file):
            return jsonify({"success": False, "error": "History file not found"}), 404

        with open(h_file, 'r', encoding='utf-8') as f:
            history_data = json.load(f)

        items = history_data if isinstance(history_data, list) else history_data.get("downloads", [])

        # 1. 物理ファイルを削除 (パス移動対策を強化)
        upload_folder = os.path.abspath(app.config["UPLOAD_FOLDER"])
        full_path = os.path.abspath(os.path.join(upload_folder, file_path))

        if not full_path.startswith(upload_folder):
            logging.warning(f"Malicious delete attempt blocked: {file_path}")
            return jsonify({"success": False, "error": "Invalid file path"}), 403

        if os.path.exists(full_path):
            try:
                if os.path.isdir(full_path):
                    shutil.rmtree(full_path)
                else:
                    os.remove(full_path)
                logging.info(f"Physical file deleted: {full_path}")
            except Exception as e:
                logging.error(f"Failed to delete physical file {full_path}: {e}")
                # 警告としてログに残すが、DB(JSON)からの削除は継続する

        # 2. 履歴データ(JSON)から削除
        new_items = [item for item in items if (item.get("file_path") or item.get("result")) != file_path]

        if isinstance(history_data, list):
            history_data = new_items
        else:
            history_data["downloads"] = new_items

        with open(h_file, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, indent=4, ensure_ascii=False)

        return jsonify({"success": True})
    except Exception as e:
        logging.error(f"Error deleting history: {e}")
        return jsonify({"success": False, "error": "削除に失敗しました"}), 500

@app.route('/updates')
def updates():
    return render_template("updates.html", updates=load_updates_history())

@app.route('/admin')
def admin_dashboard():
    return render_template("admin_dashboard.html", status_info=get_status_info(), active_tasks=active_tasks, recent_downloads=get_safe_history()[:5])

@app.route('/settings')
def settings_page():
    return render_template("settings.html", settings=load_settings())

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    settings_file = os.path.join(BASE_DIR, "JSON/settings.json")

    if request.method == 'GET':
        s = load_settings()
        # パスコードそのものは返さず、設定済みかどうかだけを返す
        if s.get("passcode"):
            s["passcode"] = "__SET__"
        return jsonify(s)

    # POST: 設定を保存
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"success": False, "error": "Invalid request"}), 400

        os.makedirs(os.path.dirname(settings_file), exist_ok=True)

        # 既存の設定を読み込み
        current = load_settings()

        # パスコードのハッシュ化処理
        new_passcode = data.get("passcode")
        if new_passcode == "__SET__":
            # 変更なし、既存のハッシュを維持
            data["passcode"] = current.get("passcode")
        elif new_passcode:
            # パスコード長チェック
            if len(str(new_passcode)) < 4:
                return jsonify({"success": False, "error": "パスコードは4文字以上でお願いします"}), 400
            # 新しいパスコードをハッシュ化
            data["passcode"] = generate_password_hash(new_passcode)
        else:
            # 空欄の場合はパスコード無効化
            data["passcode"] = ""

        # 新しい設定で更新
        current.update(data)
        save_settings_to_file(current)

        return jsonify({"success": True, "message": "設定を保存しました"})
    except ValueError:
        return jsonify({"success": False, "error": "Invalid request format"}), 400
    except Exception as e:
        logging.error(f"Failed to save user settings: {e}")
        return jsonify({"success": False, "error": "設定の保存に失敗しました"}), 500

@app.route('/api/settings/reset', methods=['POST'])
def reset_settings():
    try:
        save_settings_to_file(DEFAULT_SETTINGS.copy())
        return jsonify({"success": True, "message": "初期設定にリセットしました"})
    except Exception as e:
        logging.error(f"Failed to reset settings: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route("/terms_of_service")
def terms_of_service():
    terms_path = os.path.join(BASE_DIR, "terms_of_service.txt")
    try:
        with open(terms_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = "利用規約が準備できていません。"
    except OSError as e:
        logging.error(f"利用規約の読み込みエラー: {e}")
        content = "利用規約の読み込みに失敗しました。"
    return render_template("terms_of_service.html", terms_content=content)

@app.route("/task_progress/<task_id>")
def task_progress(task_id):
    return jsonify(_get_task_status(task_id))


@app.route("/download_file")
def download_file():
    dirname = request.args.get("dirname", "").strip()
    filename = request.args.get("filename", "").strip()

    if not dirname or not filename:
        abort(400)

    # パス長チェック
    if len(dirname) > 255 or len(filename) > 255:
        abort(400)

    base_dir = os.path.abspath(app.config["UPLOAD_FOLDER"])
    target_dir = os.path.abspath(os.path.join(base_dir, dirname))
    full_path = os.path.abspath(os.path.join(target_dir, filename))

    # セキュリティチェック：パストラバーサル対策
    if not full_path.startswith(base_dir):
        logging.warning(f"Path traversal attempt blocked: {dirname}/{filename}")
        abort(403)

    if not os.path.exists(full_path):
        abort(404)

    response = send_from_directory(
        target_dir,
        filename,
        as_attachment=True
    )
    response.headers["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(filename)}"
    )
    return response


@app.route("/download")
def download():
    name = request.args.get("name")
    if not name:
        abort(400)

    base_dir = os.path.abspath(app.config["UPLOAD_FOLDER"])
    full_path = os.path.abspath(os.path.join(base_dir, name))

    if not full_path.startswith(base_dir):
        abort(403)

    if not os.path.exists(full_path):
        abort(404)

    # フォルダの場合はZIP圧縮して送る
    if os.path.isdir(full_path):
        temp_dir = tempfile.gettempdir()
        zip_base_name = os.path.join(temp_dir, f"dl_{name}")
        zip_path = f"{zip_base_name}.zip"

        # 再作成の要否判定（Windowsの WinError 32 対策）
        need_rebuild = True
        if os.path.exists(zip_path):
            try:
                # 誰かが開いているかチェック
                os.remove(zip_path)
            except PermissionError:
                # 使用中の場合、中身があればそれを再利用（作成中かもしれないため）
                if os.path.exists(zip_path) and os.path.getsize(zip_path) > 1024:
                    need_rebuild = False
                    logging.info(f"Serving existing locked zip: {zip_path}")
                else:
                    # 壊れているか0バイトなら待ってもらう
                    abort(503, description="ZIPファイルを作成中です。数分後に再度お試しください。")

        if need_rebuild:
            try:
                # root_dir にプレイリストフォルダの「親」を指定し、base_dir に「フォルダ名」を指定することで
                # ZIPの中にそのフォルダが含まれる構造にする（より一般的で確実な方法）
                parent_dir = os.path.dirname(full_path)
                folder_name = os.path.basename(full_path)
                shutil.make_archive(zip_base_name, 'zip', root_dir=parent_dir, base_dir=folder_name)

                # 作成後のチェック
                if not os.path.exists(zip_path) or os.path.getsize(zip_path) < 100:
                    raise RuntimeError("Created ZIP is empty or too small.")

            except Exception as e:
                logging.error(f"Failed to create zip for {name}: {e}")
                if not (os.path.exists(zip_path) and os.path.getsize(zip_path) > 1024):
                    abort(500, description="ZIPファイルの作成に失敗しました。時間をおいて再度お試しください。")

        return send_from_directory(
            temp_dir,
            os.path.basename(zip_path),
            as_attachment=True
        )

    # 単一ファイルの場合
    response = send_from_directory(
        base_dir,
        name,
        as_attachment=True
    )
    response.headers["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(name)}"
    )
    return response

@app.route("/results/<path:filename>")
def results(filename):
    base_dir = os.path.abspath(app.config["UPLOAD_FOLDER"])
    full_path = os.path.abspath(os.path.join(base_dir, filename))

    if not full_path.startswith(base_dir):
        abort(403)
    if not os.path.exists(full_path):
        abort(404)

    # クエリパラメータからプレイリスト判定を取得（最優先）
    is_playlist = request.args.get('is_playlist', 'false').lower() == 'true'

    # フォールバック：ディレクトリかつ複数ファイルがある場合はプレイリストと判定
    if not is_playlist and os.path.isdir(full_path):
        files = [f for f in os.listdir(full_path) if os.path.isfile(os.path.join(full_path, f))]
        is_playlist = len(files) > 1
    elif os.path.isdir(full_path):
        files = [f for f in os.listdir(full_path) if os.path.isfile(os.path.join(full_path, f))]
    else:
        files = []

    return render_template(
        "results.html",
        name=filename,
        is_playlist=is_playlist,
        files=files,
        error=None
    )

@app.errorhandler(400)
def bad_request(error):
    logging.warning(f"Bad request: {error}")
    return jsonify({"error": "Invalid request"}), 400

@app.errorhandler(403)
def forbidden(error):
    logging.warning(f"Forbidden access attempt")
    return jsonify({"error": "Access denied"}), 403

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logging.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)