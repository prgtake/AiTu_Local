# Copyright (c) 2026 Datan (データン)
# Licensed under a Custom Hybrid License (Free for Individuals, Paid for Commercial).
# See README.md for licensing details.
# -*- coding: utf-8 -*-
"""
=======================================================
  anki_exporter.py
  Ankiパッケージ (.apkg) および CSVファイル のエクスポート処理
=======================================================
"""
import os
import re
import csv
import traceback
import urllib.parse
import random

def export_deck(filepath: str, subj: str, deck_suffix: str, rows: list, media_dir: str) -> tuple[bool, str]:
    """
    指定された問題リスト(rows)を .apkg または .csv として出力する。
    戻り値: (成功かどうかのbool, メッセージ文字列)
    """
    def _clean_and_extract_img(text):
        if not text:
            return "", []
        found_media = []
        def _repl(m):
            quote = m.group(1)
            src_val = m.group(2)
            fname = src_val.split("/")[-1]
            fname = urllib.parse.unquote(fname)
            found_media.append(fname)
            return f'src={quote}{fname}{quote}'
        cleaned_text = re.sub(r'src=(["\'])([^"\']+)\1', _repl, text, flags=re.IGNORECASE)
        return cleaned_text, found_media

    try:
        media_files_to_pack = set()

        if filepath.endswith(".apkg"):
            try:
                import genanki
            except ImportError:
                return False, "apkg出力には 'genanki' が必要です。\nコマンドプロンプト等で pip install genanki を実行してください。"

            deck_id  = random.randrange(1 << 30, 1 << 31)
            model_id = random.randrange(1 << 30, 1 << 31)
            my_model = genanki.Model(
                model_id,
                'AiTu 基本モデル',
                fields=[{'name': 'Question'}, {'name': 'Answer'}],
                templates=[{
                    'name': 'Card 1',
                    'qfmt': '{{Question}}',
                    'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}',
                }]
            )
            my_deck = genanki.Deck(deck_id, f'AiTu_{subj}_{deck_suffix}')

            for r in rows:
                q_clean,    q_m    = _clean_and_extract_img(r.get("question", ""))
                a_clean,    a_m    = _clean_and_extract_img(r.get("answer", ""))
                expl_clean, expl_m = _clean_and_extract_img(r.get("explanation", ""))
                
                back_side = a_clean or ""
                if expl_clean:
                    back_side += f"<br><br>【解説】<br>{expl_clean}"
                    
                my_deck.add_note(genanki.Note(model=my_model, fields=[q_clean, back_side]))
                
                for fname in (q_m + a_m + expl_m):
                    full_path = os.path.join(media_dir, fname)
                    if os.path.exists(full_path):
                        media_files_to_pack.add(full_path)

            my_package = genanki.Package(my_deck)
            my_package.media_files = list(media_files_to_pack)
            my_package.write_to_file(filepath)
            
            return True, f"{len(rows)}問の問題を画像付きAnkiDeck(.apkg)として出力しました！\nこのままAnkiアプリで読み込めます。"

        else:
            with open(filepath, 'w', encoding='utf-8-sig', newline='') as csvfile:
                writer = csv.writer(csvfile)
                for r in rows:
                    q_clean,    _ = _clean_and_extract_img(r.get("question", ""))
                    a_clean,    _ = _clean_and_extract_img(r.get("answer", ""))
                    expl_clean, _ = _clean_and_extract_img(r.get("explanation", ""))
                    
                    back_side = a_clean or ""
                    if expl_clean:
                        back_side += f"<br><br>【解説】<br>{expl_clean}"
                    writer.writerow([q_clean, back_side])
                    
            return True, f"{len(rows)}問の問題をAnkiDeck(CSV)として出力しました。\nAnkiアプリからインポートしてください。"

    except Exception:
        return False, f"ファイルの保存中にエラーが発生しました:\n{traceback.format_exc()}"