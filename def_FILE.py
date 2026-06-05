import os
import json
import threading
import time
import logging
import secrets
import subprocess
import re
import shutil
from datetime import datetime
try:
    from concurrent_log_handler import ConcurrentRotatingFileHandler
except ImportError:
    from logging.handlers import RotatingFileHandler as ConcurrentRotatingFileHandler, TimedRotatingFileHandler

# モジュールレベルでプロジェクトルートの絶対パスを定義
APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(APP_DIR)

# グローバル管理用
active_tasks = {}
PROGRESS_RE = re.compile(r'(\d+(?:\.\d+)?)%')
SPEED_RE = re.compile(r'at\s+([\d.]+\w+/s)')
ETA_RE = re.compile(r'ETA\s+([\d:]+)')
DOWNLOAD_TIMEOUT = 3600  # 1時間
TASK_ID_PATTERN = re.compile(r'^[a-z0-9_]+$')  # タスク ID の例計パターン

# デフォルト設定値
DEFAULT_SETTINGS = {
    "upload_folder": "downloads",
    "history_file": "JSON/history.json",
    "default_quality": "1080",
    "concurrent_fragments": "8",
    "audio_format": "mp3",
    "enable_notifications": True,
    "enable_sound": True,
    "history_count": 10,
    "show_logs": True,
    "show_history": True,
    "passcode": ""
}


def setup_logging():
    log_dir = os.path.join(APP_DIR, "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    log_file = os.path.join(log_dir, "app.log")

    handler = ConcurrentRotatingFileHandler(log_file, "a", 10 * 1024 * 1024, 5)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[handler, logging.StreamHandler()]
    )

def load_settings():
    settings_path = os.path.join(APP_DIR, "JSON", "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
        except Exception as e:
            logging.error(f"Failed to load settings: {e}")
    return DEFAULT_SETTINGS

def save_settings_to_file(settings):
    settings_dir = os.path.join(APP_DIR, "JSON")
    if not os.path.exists(settings_dir):
        os.makedirs(settings_dir)
    settings_path = os.path.join(settings_dir, "settings.json")
    try:
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to save settings: {e}")

def load_download_history():
    settings = load_settings()
    history_path = os.path.join(APP_DIR, settings["history_file"])
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 空のオブジェクト {} は空リストに変換
                if isinstance(data, dict) and not data:
                    return []
                # リストなら返す、それ以外は空リスト
                return data if isinstance(data, list) else []
        except Exception as e:
            logging.error(f"Failed to load history: {e}")
    return []

def save_download_history(history):
    """ダウンロード履歴をJSONファイルに保存"""
    settings = load_settings()
    history_dir = os.path.dirname(os.path.join(APP_DIR, settings["history_file"]))
    history_path = os.path.join(APP_DIR, settings["history_file"])

    if not os.path.exists(history_dir):
        os.makedirs(history_dir)

    try:
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
        logging.info(f"History saved: {history_path}")
    except Exception as e:
        logging.error(f"Failed to save history: {e}")

def generate_task_id():
    """UUID を使用した安全なタスク ID を生成"""
    import uuid
    return f"task_{uuid.uuid4().hex[:12]}"

def detect_downloaded_files(task, save_dir):
    """ダウンロード後に作成されたファイル/フォルダを検出"""
    try:
        if not os.path.exists(save_dir):
            return
        # まずタスクの開始時刻があれば、その時刻以降に作成/更新されたファイルを検出
        found = []
        cutoff = None
        if getattr(task, 'start_time', None):
            cutoff = task.start_time - 5

        for root, _dirs, filenames in os.walk(save_dir):
            for fname in filenames:
                full = os.path.join(root, fname)
                try:
                    mtime = os.path.getmtime(full)
                except Exception:
                    continue
                if cutoff is None or mtime >= cutoff:
                    # 相対パスで記録
                    rel = os.path.relpath(full, save_dir)
                    found.append(rel)

        if found:
            # 新しいファイルが見つかったら記録
            task.found_files = sorted(found)

            # 共通ディレクトリを求める
            full_paths = [os.path.normpath(os.path.join(save_dir, p)) for p in task.found_files]
            try:
                common = os.path.commonpath(full_paths)
                rel_common = os.path.relpath(common, save_dir)
            except Exception:
                rel_common = None

            # 相対共通パスが '.' の場合はルートにある
            if rel_common and rel_common != '.':
                task.download_path = rel_common
            else:
                task.download_path = None

            # プレイリスト判定は実際のファイル数に基づく
            task.is_playlist = len(task.found_files) > 1

            # タイトル未設定なら最初のファイル名を使用
            if (not task.title or task.title == "Unknown") and task.found_files:
                first = task.found_files[0]
                task.title = os.path.splitext(os.path.basename(first))[0]

            logging.info(f"[{task.task_id}] Detected files: {len(task.found_files)} items, download_path={task.download_path}")
            return

        # フォールバック: 既存の簡易ロジック（変更前の動作）
        items = os.listdir(save_dir)
        files = [f for f in items if os.path.isfile(os.path.join(save_dir, f))]
        dirs = [d for d in items if os.path.isdir(os.path.join(save_dir, d))]

        def newest_name(names, base):
            if not names:
                return None
            try:
                return max(names, key=lambda n: os.path.getmtime(os.path.join(base, n)))
            except Exception:
                return names[0]

        if task.is_playlist and dirs:
            chosen = newest_name(dirs, save_dir)
            task.download_path = chosen
            if not task.title or task.title == "Unknown":
                task.title = chosen
        elif files:
            chosen = newest_name(files, save_dir)
            task.download_path = chosen
            if not task.title or task.title == "Unknown":
                filename_without_ext = os.path.splitext(chosen)[0]
                task.title = filename_without_ext
        elif dirs:
            chosen = newest_name(dirs, save_dir)
            task.download_path = chosen
            if not task.title or task.title == "Unknown":
                task.title = chosen

        logging.info(f"[{task.task_id}] Downloaded (fallback): {task.download_path}")
    except Exception as e:
        logging.error(f"[{task.task_id}] Failed to detect downloaded files: {e}")

def save_download_to_history(task):
    """ダウンロードタスク情報を履歴に記録"""
    try:
        history = load_download_history()
        if not isinstance(history, list):
            history = []
        # まず、run-time に検出された新規ファイル群があればそれを使う
        if getattr(task, 'found_files', None):
            if len(task.found_files) > 0:
                # found_files は相対パスのリスト
                for rel in sorted(task.found_files, reverse=True):
                    entry_id = generate_task_id()
                    title = os.path.splitext(os.path.basename(rel))[0]
                    download_info = {
                        "id": entry_id,
                        "url": task.url,
                        "title": title or "Unknown",
                        "download_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "save_dir": task.save_dir,
                        "file_path": rel.replace('\\', '/'),
                        "is_playlist": len(task.found_files) > 1,
                        "status": task.status,
                        "file_type": "video"
                    }
                    history.insert(0, download_info)
        # プレイリストの場合はフォルダ内の各ファイルを個別に履歴登録
        elif task.is_playlist and task.download_path:
            playlist_dir = os.path.join(task.save_dir, task.download_path)
            if os.path.isdir(playlist_dir):
                files = [f for f in os.listdir(playlist_dir) if os.path.isfile(os.path.join(playlist_dir, f))]
                # 新しい順（最終更新日時順）に並べ替え
                try:
                    files.sort(key=lambda x: os.path.getmtime(os.path.join(playlist_dir, x)), reverse=True)
                except Exception:
                    files = sorted(files)

                for fname in files:
                    entry_id = generate_task_id()
                    title = os.path.splitext(fname)[0]
                    download_info = {
                        "id": entry_id,
                        "url": task.url,
                        "title": title or "Unknown",
                        "download_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "save_dir": task.save_dir,
                        "file_path": os.path.join(task.download_path, fname).replace('\\', '/'),
                        "is_playlist": True,
                        "status": task.status,
                        "file_type": "video"
                    }
                    history.insert(0, download_info)
        else:
            # 単一ファイルまたはフォルダのエントリ
            download_info = {
                "id": task.task_id,
                "url": task.url,
                "title": task.title or "Unknown",
                "download_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "save_dir": task.save_dir,
                "file_path": task.download_path if task.download_path else None,
                "is_playlist": task.is_playlist,
                "status": task.status,
                "file_type": "playlist" if task.is_playlist else "video"
            }
            history.insert(0, download_info)

        # 最大保存数（デフォルト100件）を超える場合は削除
        max_history = 100
        if len(history) > max_history:
            history = history[:max_history]

        save_download_history(history)
        logging.info(f"Download saved to history: {task.title}")
    except Exception as e:
        logging.error(f"Failed to save download to history: {e}")

def is_url_playlist(url):
    """URLからプレイリストかどうか判定"""
    url_lower = url.lower()
    # プレイリストを含むURLパターン
    if 'playlist?list=' in url_lower or '&list=' in url_lower:
        return True
    if '/playlist' in url_lower:
        return True
    return False

class DownloadTask:
    def __init__(self, task_id, url, save_dir):
        self.task_id = task_id
        self.url = url
        self.save_dir = save_dir
        self.status = "starting"
        self.percentage = 0
        self.speed = ""
        self.eta = ""
        self.title = ""
        self.error = None
        self.is_playlist = False  # プレイリストフラグを追加
        self.download_path = None  # 実際のダウンロードファイル/フォルダパスを保存
        self.logs = []  # ダウンロードログを保存
        self.start_time = None  # タスク開始時刻 (秒)
        self.found_files = []   # 検出されたファイルのリスト (相対パス)

    def add_log(self, message):
        """ログメッセージを追加"""
        self.logs.append(message)

def run_yt_dlp(task_id, url, save_dir, quality="1080", audio_only=False):
    task = active_tasks.get(task_id)
    if not task:
        return

    # クッキーファイルのパス（app.pyと同じ階層を想定）
    cookie_path = os.path.join(APP_DIR, "cookies.txt")

    speed_opts = ["--newline", "--progress"]

    # User-Agentとヘッダーの設定
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"

    # 出力テンプレート: プレイリストならフォルダに分ける
    out_template = "%(playlist_title)s/%(title)s.%(ext)s" if task.is_playlist else "%(title)s.%(ext)s"

    # 基本コマンド
    if audio_only:
        cmd = [
            "yt-dlp",
            "--user-agent", user_agent,
            "-f", "bestaudio/best",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "192",
            "--socket-timeout", "30",
            "--retries", "10",
            "--fragment-retries", "3",
            "--no-check-formats",
            "--extractor-args", "youtube:player_client=web",
            "--extractor-args", "youtube:lang=ja",
            "--extractor-args", "youtube:skip=dash",
            "--no-check-certificates",
            *speed_opts,
            "-o", out_template
        ]
    else:
        cmd = [
            "yt-dlp",
            "--user-agent", user_agent,
            "-f", "18/best[ext=mp4]/best",
            "--fragment-retries", "3",
            "--no-check-formats",
            "--socket-timeout", "30",
            "--retries", "10",
            "--extractor-args", "youtube:player_client=web",
            "--extractor-args", "youtube:lang=ja",
            "--extractor-args", "youtube:skip=dash",
            "--no-check-certificates",
            *speed_opts,
            "-o", out_template
        ]

    # クッキーファイルが存在する場合のみ追加
    if os.path.exists(cookie_path):
        cmd.extend(["--cookies", cookie_path])
        logging.info(f"[{task_id}] Using cookies.txt for download.")
    else:
        logging.warning(f"[{task_id}] cookies.txt not found. Attempting without cookies.")

    # HTTPヘッダーを追加してYouTubeのセキュリティを回避
    cmd.extend([
        "--extractor-args", "youtube:player_version=null",
        "--extractor-args", "youtube:signature_timestamp=null"
    ])

    cmd.append(url)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # Node.jsを強制的に使用
    env["NODE_PATH"] = os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "nodejs")
    env["PATH"] = f"{env['NODE_PATH']};{env.get('PATH', '')}"

def sanitize_log(message):
    """ログから機密情報（URL、ファイルパスなど）を削除"""
    if not message:
        return message

    # ユーザーエージェント情報を隠す
    message = re.sub(r'User-Agent:.*', 'User-Agent: [REDACTED]', message)

    # ファイルパスのフルパスを相対パスに
    message = re.sub(r'[A-Z]:\\[^\\]+\\', '[PATH]/', message)

    # Cookie 情報を隠す
    message = re.sub(r'cookies\.txt.*', '[cookies: REDACTED]', message)

    return message

def run_yt_dlp(task_id, url, save_dir, quality="1080", audio_only=False):
    task = active_tasks.get(task_id)
    if not task:
        return

    # クッキーファイルのパス（app.pyと同じ階層を想定）
    cookie_path = os.path.join(APP_DIR, "cookies.txt")

    speed_opts = ["--newline", "--progress"]

    # User-Agentとヘッダーの設定
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"

    # 基本コマンド
    if audio_only:
        cmd = [
            "yt-dlp",
            "--user-agent", user_agent,
            "-f", "bestaudio/best",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "192",
            "--socket-timeout", "30",
            "--retries", "10",
            "--fragment-retries", "3",
            "--no-check-formats",
            "--extractor-args", "youtube:player_client=web",
            "--extractor-args", "youtube:lang=ja",
            "--extractor-args", "youtube:skip=dash",
            "--no-check-certificates",
            *speed_opts,
            "-o", "%(title)s.%(ext)s"
        ]
    else:
        cmd = [
            "yt-dlp",
            "--user-agent", user_agent,
            "-f", "18/best[ext=mp4]/best",
            "--fragment-retries", "3",
            "--no-check-formats",
            "--socket-timeout", "30",
            "--retries", "10",
            "--extractor-args", "youtube:player_client=web",
            "--extractor-args", "youtube:lang=ja",
            "--extractor-args", "youtube:skip=dash",
            "--no-check-certificates",
            *speed_opts,
            "-o", "%(title)s.%(ext)s"
        ]

    # クッキーファイルが存在する場合のみ追加
    if os.path.exists(cookie_path):
        cmd.extend(["--cookies", cookie_path])
        logging.info(f"[{task_id}] Using cookies.txt for download.")
    else:
        logging.warning(f"[{task_id}] cookies.txt not found. Attempting without cookies.")

    # HTTPヘッダーを追加してYouTubeのセキュリティを回避
    cmd.extend([
        "--extractor-args", "youtube:player_version=null",
        "--extractor-args", "youtube:signature_timestamp=null"
    ])

    cmd.append(url)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # Node.jsを強制的に使用
    env["NODE_PATH"] = os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "nodejs")
    env["PATH"] = f"{env['NODE_PATH']};{env.get('PATH', '')}"

    try:
        process = subprocess.Popen(
            cmd,
            cwd=save_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        for line in process.stdout:
            line = line.strip()
            if line:
                # 機密情報を削除してログに記録
                safe_log = sanitize_log(line)
                logging.info(f"[{task_id}] {safe_log}")
                task.add_log(safe_log)  # ログをリアルタイムで保存

                m = PROGRESS_RE.search(line)
                if m:
                    task.percentage = int(float(m.group(1)))
                    speed_match = SPEED_RE.search(line)
                    eta_match = ETA_RE.search(line)
                    task.speed = speed_match.group(1) if speed_match else task.speed
                    task.eta = eta_match.group(1) if eta_match else task.eta
                    task.status = "downloading"

                # ダウンロード完了の検出
                if "100%" in line or "has already been downloaded" in line:
                    task.percentage = 100
                    task.status = "completed"

        process.wait()
        if process.returncode == 0:
            task.status = "completed"
            task.percentage = 100

            # 実際のダウンロード対象を検出
            detect_downloaded_files(task, save_dir)

            # ダウンロード完了時に履歴を記録
            save_download_to_history(task)
        else:
            task.status = "failed"
            task.error = "yt-dlp failed"

        logging.info(f"[{task_id}] Task completed with status: {task.status}")

    except Exception as e:
        logging.error(f"[{task_id}] Error: {e}")
        task.status = "failed"
        task.error = str(e)

def start_background_download(url, audio_only, save_dir=None):
    settings = load_settings()
    if save_dir is None:
        save_dir = os.path.join(APP_DIR, settings["upload_folder"])
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    quality = settings.get("default_quality", "1080")
    task_id = generate_task_id()
    task = DownloadTask(task_id, url, save_dir)
    task.start_time = time.time()
    # URLからプレイリスト判定を設定
    task.is_playlist = is_url_playlist(url)
    active_tasks[task_id] = task

    thread = threading.Thread(target=run_yt_dlp, args=(task_id, url, save_dir, quality, audio_only))
    thread.start()

    class TaskWrapper:
        pass
    wrapper = TaskWrapper()
    wrapper.task = task
    return wrapper

def _get_task_status(task_id):
    task = active_tasks.get(task_id)
    if task:
        result = {
            "status": task.status,
            "percentage": task.percentage,
            "speed": task.speed,
            "eta": task.eta,
            "title": task.title,
            "error": task.error,
            "is_playlist": task.is_playlist,
            "logs": task.logs,  # ログをレスポンスに含める
            "message": f"{task.status}中..." if task.status == "downloading" else task.status
        }
        # 完了時は実際のダウンロードファイル/フォルダパスを追加
        if task.status == "completed":
            result["complete"] = True
            result["status"] = "complete"
            # ダウンロード対象が検出されていればそれを使用、なければベースディレクトリ
            result["result_path"] = task.download_path if task.download_path else task.save_dir
        return result
    return None

def validate_task_id(task_id):
    """task_idの例計性を検証"""
    if not task_id or not isinstance(task_id, str):
        return False
    return bool(TASK_ID_PATTERN.match(task_id)) and len(task_id) < 100

def get_status_info(task_id):
    if not validate_task_id(task_id):
        return None
    return _get_task_status(task_id)

def save_settings_to_file(settings):
    settings_dir = os.path.join(APP_DIR, "JSON")
    if not os.path.exists(settings_dir):
        os.makedirs(settings_dir)
    settings_path = os.path.join(settings_dir, "settings.json")
    try:
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to save settings: {e}")