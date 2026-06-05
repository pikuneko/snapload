import json
import os
import shutil
import sys
from typing import List, Dict, Any

def find_duplicates_by_url_and_path(downloads_data: List[Dict[str, Any]]):
    """
    URLとfile_pathで重複を検出して削除対象を返す
    """
    seen_urls = set()
    seen_paths = set()
    unique_items = []
    removed_duplicates = []

    for item in downloads_data:
        url = item.get('url')
        path = item.get('file_path')

        if url in seen_urls or path in seen_paths:
            removed_duplicates.append(item)
        else:
            if url:
                seen_urls.add(url)
            if path:
                seen_paths.add(path)
            unique_items.append(item)

    return unique_items, removed_duplicates

def delete_files(items: List[Dict[str, Any]]):
    """削除対象のファイルを削除"""
    deleted = []
    errors = []

    for item in items:
        path = item.get('file_path')
        if path and os.path.exists(path):
            try:
                os.remove(path)
                deleted.append(path)
            except Exception as e:
                errors.append(f"{path}: {e}")

    return deleted, errors

def process_file(file_path: str):
    """JSONの重複削除＋ファイル削除"""
    if not os.path.exists(file_path):
        print(f"エラー: ファイルが存在しません: {file_path}")
        return

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, list):
            downloads_data = data
            is_list = True
        elif 'downloads' in data:
            downloads_data = data['downloads']
            is_list = False
        else:
            print("エラー: JSON形式が不正です。'downloads'キーが見つかりません")
            return

        original_count = len(downloads_data)

        unique_items, removed_duplicates = find_duplicates_by_url_and_path(downloads_data)
        cleaned_count = len(unique_items)

        deleted_files, delete_errors = delete_files(removed_duplicates)

        # バックアップ作成
        backup_file = file_path + ".backup"
        shutil.copy2(file_path, backup_file)

        # 上書き保存
        result = unique_items if is_list else {'downloads': unique_items}
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # 結果表示
        print(f"処理完了: {original_count}件 → {cleaned_count}件")
        print(f"削除された重複: {original_count - cleaned_count}件")
        print(f"削除されたファイル: {len(deleted_files)}件")
        if delete_errors:
            print(f"削除失敗ファイル: {len(delete_errors)}件")
            for err in delete_errors[:5]:
                print(f"  {err}")
        print(f"バックアップ: {backup_file}")

    except Exception as e:
        print(f"エラー: {e}")

if __name__ == "__main__":
    process_file("E:\YoutubeDownload\JSON\download_history.json")


