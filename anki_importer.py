# Copyright (c) 2026 Datan (データン)
# Licensed under a Custom Hybrid License (Free for Individuals, Paid for Commercial).
# See README.md for licensing details.
# -*- coding: utf-8 -*-
"""
=======================================================
  anki_importer.py  (Ankiパッケージ取り込み層)
  .apkg ファイルの解凍・解析・DBへの登録を担当。
  UI・Gemini API には直接依存しません。
  依存: database.py, ai_engine.py (シラバス生成のみ)
=======================================================

【処理の流れ】
  1. .apkg (ZIP) を一時ディレクトリに解凍
  2. media インデックスを読み取り、数字ファイル → 元ファイル名にリネームして
     <科目名>_media/ フォルダへコピー
  3. collection.anki2 (SQLite) からノートを抽出
  4. タグ一覧のみ Gemini に送り、章立て (JSON) を生成
  5. 各ノートをキーワードマッチングで章にマッピング
  6. database.py の config / question テーブルへ登録
"""

import os
import sys
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from typing import Callable, Dict, List, Optional, Tuple

# ── BASE_DIR は database.py と同じ基準で決定 ──────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# =====================================================
#  メディア管理
# =====================================================

def get_media_dir(subject: str) -> str:
    """
    <BASE_DIR>/<subject>_media/ のパスを返す。
    存在しなければ自動生成する。
    """
    path = os.path.join(BASE_DIR, f"{subject}_media")
    os.makedirs(path, exist_ok=True)
    return path


def fix_media_paths(html_text: str, subject: str) -> str:
    """
    HTML 内の <img src="filename"> / <img src='filename'> を
    file:/// 絶対パスへ書き換えて、ローカル画像を表示できるようにする。
    src より前に他の属性がある場合も対応。
    例: <img src="test.jpg">
      → <img src="file:///C:/path/to/subject_media/test.jpg">
    """
    media_dir = get_media_dir(subject)

    def _replace_src(m: re.Match) -> str:
        quote = m.group(1)   # " または '
        src   = m.group(2)
        # すでに絶対パスや http:// / data: の場合はそのまま
        if src.startswith(("http", "file://", "data:")):
            return m.group(0)
        local_path = os.path.join(media_dir, src)
        # Windows パスを file:/// 形式に変換
        uri = local_path.replace("\\", "/")
        if not uri.startswith("/"):
            uri = "/" + uri
        return f'src={quote}file://{uri}{quote}'

    # src="..." または src='...' に対応（img タグ内の任意の位置）
    return re.sub(r'src=(["\'])([^"\']+)\1', _replace_src, html_text)


# =====================================================
#  .apkg 解凍とメディア抽出
# =====================================================

def _extract_apkg(apkg_path: str, work_dir: str) -> None:
    """ZIP (.apkg) を work_dir に解凍する"""
    with zipfile.ZipFile(apkg_path, "r") as z:
        z.extractall(work_dir)


def _collect_media(work_dir: str, subject: str,
                   progress_cb: Optional[Callable[[str], None]] = None,
                   extra_info: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Anki の media インデックス (JSON) を読み取り、
    数字ファイルを元ファイル名にリネームして <subject>_media/ へコピーする。

    Args:
        extra_info: { "元ファイル名": "AI解析時に追加する知識テキスト" }
    Returns:
        { "元ファイル名": "コピー先フルパス" } の辞書
    """
    media_index_path = os.path.join(work_dir, "media")
    if not os.path.exists(media_index_path):
        return {}

    with open(media_index_path, "r", encoding="utf-8") as fp:
        try:
            media_map: Dict[str, str] = json.load(fp)
        except json.JSONDecodeError:
            return {}   # media インデックスが壊れていても問題インポートは続行

    dest_dir = get_media_dir(subject)
    result: Dict[str, str] = {}
    total = len(media_map)
    extra_info = extra_info or {}

    for i, (num_key, orig_name) in enumerate(media_map.items(), 1):
        src = os.path.join(work_dir, num_key)
        if not os.path.exists(src):
            continue
        # パストラバーサル対策: basename でファイル名のみ取り出す
        safe_name = os.path.basename(orig_name)
        if not safe_name:           # 空文字やディレクトリ名だけの場合はスキップ
            continue

        # .svg ファイルのスキップ
        if safe_name.lower().endswith('.svg'):
            continue

        dst = os.path.join(dest_dir, safe_name)
        shutil.copy2(src, dst)
        result[safe_name] = dst

        # 静止画像の場合はAIで内容を解析してDBに保存する
        if safe_name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp')):
            try:
                import ai_engine
                import database
                import time
                if progress_cb:
                    progress_cb(f"🤖 画像をAIで解析中... {safe_name}")
                
                # 目隠し問題などの追加情報があれば取得
                context = extra_info.get(safe_name, "")
                
                summary = ai_engine.analyze_image_for_summary(dst)
                if summary:
                    # 追加情報があれば統合する
                    if context:
                        summary = f"{summary}\n\n[補足知識]\n{context}"
                    database.save_media_summary(subject, safe_name, summary)
                time.sleep(4)  # 無料APIのレート制限（15回/分）対策の待機時間
            except Exception as e:
                print(f"解析スキップ: {e}")

        if progress_cb and (i % 10 == 0 or i == total):
            progress_cb(f"メディア抽出・解析中 ({i}/{total})...")

    return result


# =====================================================
#  collection.anki2 解析
# =====================================================

# Anki が内部で利用するセパレータ (フィールド区切り)
_ANKI_FIELD_SEP = "\x1f"

# Ankiメディアファイルの拡張子セット
_MEDIA_EXTS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ".mp3", ".wav", ".ogg", ".m4a", ".mp4", ".ogv", ".avi", ".swf",
)

# Ankiのメディアファイル名パターン: MD5ハッシュ(32桁16進数)で始まる文字列
_ANKI_MEDIA_HASH_RE = re.compile(r'^[0-9a-fA-F]{32}')


def _is_image_occlusion(model_name: str) -> bool:
    """ノートタイプ名から目隠し問題(Image Occlusion)かどうか判定する"""
    name = model_name.lower()
    return "image occlusion" in name or "画像目隠し" in name


def _extract_image_filename(text: str) -> Optional[str]:
    """HTMLテキストから最初の <img> タグの src ファイル名を取り出す"""
    m = re.search(r'<img [^>]*src=["\']([^"\']+)["\']', text)
    if m:
        return os.path.basename(m.group(1))
    return None


def _looks_like_media_filename(text: str) -> bool:
    """
    テキストがAnkiのメディアファイル名（拡張子あり・なし両方）のように見えるか判定する。
    例: "8ea0c66916f94f508d8e8cbfc5327509-ao-2"
        "8ea0c66916f94f508d8e8cbfc5327509-ao-2.jpg"
    """
    t = text.strip()
    if not t:
        return False
    # 拡張子ありメディアファイル名
    if any(t.lower().endswith(e) for e in _MEDIA_EXTS):
        return True
    # MD5ハッシュ(32桁)で始まる文字列（拡張子なしを含む）
    if _ANKI_MEDIA_HASH_RE.match(t) and len(t) >= 32:
        return True
    return False


def _clean_anki_field(text: str) -> str:
    """
    _strip_html 後のテキストに残るAnki固有の記法をクリーンアップする。
    ・[sound:filename] → 除去
    ・{{c1::テキスト::ヒント}} → テキスト部分を取り出す
    ・メディアハッシュのみ → <img src="..."> に変換（拡張子が分かる場合）または除去
    """
    # [sound:...] を除去
    text = re.sub(r'\[sound:[^\]]*\]', '', text)

    # {{c数字::テキスト}} または {{c数字::テキスト::ヒント}} → テキスト部分を取り出す
    text = re.sub(r'\{\{c\d+::([^:}]+)(?:::[^}]*)?\}\}', r'\1', text)

    # 空白の正規化
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _strip_html(html_text: str) -> str:
    """
    HTML タグを除去しつつ <img> タグだけは src 属性を保持して残す。
    Anki固有の記法（[sound:]、{{cloze}}）も処理する。
    BeautifulSoup が使えない環境のフォールバックも備える。
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text, "html.parser")

        # <img> を "[[IMG:filename]]" プレースホルダーに変換
        for img in soup.find_all("img"):
            src = img.get("src", "")
            img.replace_with(f'[[IMG:{src}]]')

        text = soup.get_text(separator="\n")
        # プレースホルダーを <img> タグに戻す
        text = re.sub(r'\[\[IMG:([^\]]+)\]\]', r'<img src="\1">', text)

    except ImportError:
        # フォールバック: <img> タグはそのまま残し、他のHTMLタグを除去
        text = re.sub(r'<(?!/?img)[^>]+>', "", html_text)
        text = re.sub(r'&nbsp;', " ", text)
        text = re.sub(r'&lt;',   "<", text)
        text = re.sub(r'&gt;',   ">", text)
        text = re.sub(r'&amp;',  "&", text)

    # Anki固有記法のクリーンアップ（両パスで共通）
    text = _clean_anki_field(text)

    # フィールドがメディアファイル名のみの場合は <img> タグに変換
    # 例: "8ea0c66916f94f508d8e8cbfc5327509-ao-2" → <img src="8ea0c66916f94f508d8e8cbfc5327509-ao-2.jpg">
    stripped = text.strip()
    if stripped and _looks_like_media_filename(stripped) and '<img' not in stripped:
        # 拡張子がない場合は .jpg を補完して試みる（最も一般的な画像形式）
        fname = stripped
        if not any(fname.lower().endswith(e) for e in _MEDIA_EXTS):
            fname = fname + ".jpg"
        text = f'<img src="{fname}">'

    return text.strip()


def _parse_notes(anki2_path: str) -> List[Dict]:
    """
    collection.anki2 から全ノートを抽出して返す。

    Returns: List of {
        "flds":  [field0_text, field1_text, ...],   # HTMLタグ除去済み
        "flds_raw": [field0_html, ...],             # 生HTML
        "tags":  ["tag1", "tag2", ...],
        "model": "モデル名 (ノートタイプ名)",
        "is_io": bool                               # Image Occlusion かどうか
    }
    """
    conn = sqlite3.connect(anki2_path)
    conn.row_factory = sqlite3.Row

    # ── ノートタイプ (models) を取得 ──
    models_json: Dict[str, Dict] = {}
    results = []
    try:
        try:
            col_row = conn.execute("SELECT models FROM col").fetchone()
            if col_row and col_row["models"]:
                models_json = json.loads(col_row["models"])
        except Exception:
            pass

        notes_raw = conn.execute(
            "SELECT id, mid, flds, tags FROM notes"
        ).fetchall()

        for row in notes_raw:
            model_id   = str(row["mid"])
            model_def  = models_json.get(model_id, {})
            model_name = model_def.get("name", "")
            is_io      = _is_image_occlusion(model_name)

            flds_raw  = row["flds"].split(_ANKI_FIELD_SEP)
            flds_text = [_strip_html(f) for f in flds_raw]
            tags      = [t for t in row["tags"].strip().split() if t]

            results.append({
                "flds":     flds_text,
                "flds_raw": flds_raw,
                "tags":     tags,
                "model":    model_name,
                "is_io":    is_io,
            })
    finally:
        conn.close()

    return results


# =====================================================
#  シラバス生成 (AI呼び出し)
# =====================================================

_SYLLABUS_SYSTEM_PROMPT = """\
あなたは教育専門家です。
与えられた「タグリスト」を分析し、体系的な学習計画（シラバス）をJSON形式で出力してください。

【出力形式】
[
  {
    "id": "chapter_1",
    "name": "章のタイトル（日本語）",
    "keywords": ["関連タグや重要語句", ...],
    "sub_topics": [
      { "id": "chapter_1_1", "name": "小項目名", "keywords": ["タグ", ...] }
    ]
  },
  ...
]

【ルール】
- 章は 5〜15 個程度を目安に設定してください。
- sub_topics は必要なければ空リスト [] にしてください。
- id は英数字とアンダースコアのみ使用してください。
- keywords にには、各問題をその章に振り分けるための「キーワード」を含めてください。
- JSON のみ出力し、他のテキストは一切含めないでください。
"""


def generate_syllabus_from_tags(
    tags: List[str],
    subject: str,
    note_samples: Optional[List[str]] = None,
) -> List[Dict]:
    """
    タグ一覧（とオプションの問題冒頭サンプル）を Gemini に送り、
    学習計画 JSON を生成して返す。
    """
    import ai_engine

    unique_tags = sorted(set(tags))
    tag_block   = "\n".join(f"- {t}" for t in unique_tags[:500])

    sample_block = ""
    if note_samples:
        samples = note_samples[:30]
        sample_block = "\n\n【問題文サンプル（先頭30件）】\n" + "\n".join(
            f"{i+1}. {s[:80]}" for i, s in enumerate(samples)
        )

    prompt = (
        f"科目名：{subject}\n\n"
        f"【タグ一覧】\n{tag_block}"
        + sample_block
        + "\n\n上記を元に、体系的な学習計画JSONを作成してください。"
    )

    raw = ai_engine.gemini_once_json(
        _SYLLABUS_SYSTEM_PROMPT + "\n\n" + prompt
    )
    plan = json.loads(raw)
    return plan if isinstance(plan, list) else []


# =====================================================
#  キーワードマッチングによる問題の章への振り分け
# =====================================================

def _score_note_for_topic(note: Dict, topic: Dict) -> float:
    """ノートと章の「マッチスコア」を返す"""
    score = 0.0
    keywords  = [kw.lower() for kw in (topic.get("keywords") or [])]
    note_tags = [t.lower()  for t  in (note.get("tags")     or [])]
    note_text = " ".join(note.get("flds") or []).lower()

    for kw in keywords:
        if kw in note_tags:
            score += 3.0
        elif kw in note_text:
            score += 1.0

    return score


def assign_topic_ids(notes: List[Dict], plan: List[Dict]) -> List[Tuple[Dict, str]]:
    """各ノートを学習計画の章 (topic_id) に振り分ける"""
    flat_topics: List[Dict] = []
    for chapter in plan:
        subs = chapter.get("sub_topics", [])
        if subs:
            for sub in subs:
                flat_topics.append(sub)
        else:
            flat_topics.append(chapter)

    if not flat_topics:
        return [(n, "anki_uncategorized") for n in notes]

    assigned = []
    for note in notes:
        best_id    = flat_topics[0]["id"]
        best_score = -1.0

        for topic in flat_topics:
            s = _score_note_for_topic(note, topic)
            if s > best_score:
                best_score = s
                best_id    = topic["id"]

        assigned.append((note, best_id))

    return assigned


# =====================================================
#  database.py へのデータ登録
# =====================================================

def _register_plan(subject: str, plan: List[Dict]) -> None:
    """学習計画を database の config に保存する"""
    import database as _db
    _db.save_cfg(subject, {"plan": plan})


def _has_content(s: str) -> bool:
    """内容の有無を判定"""
    if not s:
        return False
    text_only = re.sub(r'<img[^>]*>', '', s).strip()
    img_count  = len(re.findall(r'<img', s))
    return bool(text_only) or img_count > 0


def _register_questions(
    subject:     str,
    assigned:    List[Tuple[Dict, str]],
    progress_cb: Optional[Callable[[str], None]] = None,
) -> int:
    """問題のDB登録"""
    import database as _db
    import datetime

    conn_path = _db.db_path(subject)
    conn = sqlite3.connect(conn_path)
    _db._ensure_question_table(conn)

    now   = datetime.datetime.now().isoformat(timespec="seconds")
    count = 0
    total = len(assigned)

    try:
        for i, (note, topic_id) in enumerate(assigned, 1):
            flds = note.get("flds", [])
            
            # 目隠し問題(IO)の処理
            if note.get("is_io"):
                # IOカードの場合の暫定的な割り当て
                question = flds[0].strip() if flds else ""
                if "<img" not in question and len(flds) > 1:
                    question = flds[1].strip() + "<br>" + question
                
                answer = flds[5].strip() if len(flds) > 5 else (flds[2].strip() if len(flds) > 2 else "画像を確認してください")
                explanation = flds[6].strip() if len(flds) > 6 else ""
            else:
                if len(flds) < 2:
                    continue
                question    = flds[0].strip()
                answer      = flds[1].strip()
                explanation = flds[2].strip() if len(flds) > 2 else ""

            if not _has_content(question) or not _has_content(answer):
                continue

            question    = fix_media_paths(question, subject)
            answer      = fix_media_paths(answer, subject)
            explanation = fix_media_paths(explanation, subject)

            conn.execute(
                """INSERT INTO question
                   (topic_id, question, answer, explanation, created_at, format)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (topic_id, question, answer, explanation, now, "記述式問題"),
            )
            count += 1

            if progress_cb and (i % 50 == 0 or i == total):
                progress_cb(f"問題登録中 ({i}/{total})...")

        conn.commit()
    finally:
        conn.close()

    return count


# =====================================================
#  メインの公開インターフェース
# =====================================================

class AnkiImporter:
    """
    .apkg ファイルを読み込み、シラバスを逆コンパイルして
    database.py に登録するまでの一連の処理を管理するクラス。
    """

    def __init__(self, apkg_path: str, subject: str):
        self.apkg_path = apkg_path
        self.subject   = subject
        self._work_dir: Optional[str] = None

    def _shard_plan(self, assigned: List[Tuple[Dict, str]], plan: List[Dict], max_per_topic: int = 20) -> Tuple[List[Tuple[Dict, str]], List[Dict]]:
        """1つのトピックに問題が多すぎる場合、(1), (2) のように分割する（オート・シャィディング）。"""
        topic_to_notes = {}
        for note, tid in assigned:
            if tid not in topic_to_notes: topic_to_notes[tid] = []
            topic_to_notes[tid].append(note)

        new_plan = []
        new_assigned = []

        for ch in plan:
            subs = ch.get("sub_topics", [])
            new_subs = []
            
            if subs:
                for sub in subs:
                    tid = sub["id"]
                    notes = topic_to_notes.get(tid, [])
                    if len(notes) > max_per_topic:
                        for i in range(0, len(notes), max_per_topic):
                            idx = (i // max_per_topic) + 1
                            shard_id = f"{tid}_s{idx}"
                            shard_name = f"{sub['name']} ({idx})"
                            new_subs.append({"id": shard_id, "name": shard_name, "keywords": sub.get("keywords", [])})
                            for n in notes[i:i+max_per_topic]:
                                new_assigned.append((n, shard_id))
                    else:
                        new_subs.append(sub)
                        for n in notes: new_assigned.append((n, tid))
                ch["sub_topics"] = new_subs
                new_plan.append(ch)
            else:
                tid = ch["id"]
                notes = topic_to_notes.get(tid, [])
                if len(notes) > max_per_topic:
                    for i in range(0, len(notes), max_per_topic):
                        idx = (i // max_per_topic) + 1
                        shard_id = f"{tid}_s{idx}"
                        shard_name = f"{ch['name']} ({idx})"
                        new_subs.append({"id": shard_id, "name": shard_name, "keywords": ch.get("keywords", [])})
                        for n in notes[i:i+max_per_topic]:
                            new_assigned.append((n, shard_id))
                    ch["sub_topics"] = new_subs
                    new_plan.append(ch)
                else:
                    new_plan.append(ch)
                    for n in notes: new_assigned.append((n, tid))
        
        return new_assigned, new_plan

    def run(
        self,
        progress_cb:        Optional[Callable[[str], None]] = None,
        use_ai_syllabus:    bool = True,
        batch_ai_classify:  bool = False,
    ) -> Dict:
        def _cb(msg: str):
            if progress_cb: progress_cb(msg)

        try:
            # ── Step 1: 解凍 ──────────────────────────────
            _cb("📦 .apkg を解凍中...")
            self._work_dir = tempfile.mkdtemp(prefix="anki_import_")
            _extract_apkg(self.apkg_path, self._work_dir)

            # ── Step 2: ノート解析 ────────────────────────
            _cb("🔍 ノートデータを解析中...")
            anki2_path = self._find_anki2()
            notes      = _parse_notes(anki2_path)
            _cb(f"✅ {len(notes)} 件のノートを検出しました。")

            if not notes:
                return {"success": False, "message": "ノートが見つかりませんでした。", "plan": [], "note_count": 0, "media_count": 0}

            # 目隠し問題(IO)の「答え」を画像の追加知識として収集
            extra_media_info = {}
            for note in notes:
                if note.get("is_io"):
                    bg_img = _extract_image_filename(note["flds_raw"][4]) if len(note["flds_raw"]) > 4 else None
                    if not bg_img:
                        for fraw in note["flds_raw"]:
                            bg_img = _extract_image_filename(fraw)
                            if bg_img: break
                    
                    if bg_img:
                        ans = note["flds"][5] if len(note["flds"]) > 5 else (note["flds"][2] if len(note["flds"]) > 2 else "")
                        if ans:
                            if bg_img not in extra_media_info: extra_media_info[bg_img] = []
                            extra_media_info[bg_img].append(f"目隠し部分の正解: {ans}")

            extra_media_info = {k: " / ".join(v) for k, v in extra_media_info.items()}

            # ── Step 3: メディア抽出 ──────────────────────
            _cb("🖼️  メディアファイルを抽出中...")
            media_result = _collect_media(self._work_dir, self.subject, _cb, extra_info=extra_media_info)
            media_count  = len(media_result)
            _cb(f"✅ メディア {media_count} 件を抽出しました。")

            # ── Step 4: シラバス生成 ──────────────────────
            _cb("🧠 シラバスを生成中...")
            all_tags = [t for note in notes for t in note["tags"]]
            note_samples = [note["flds"][0][:100] for note in notes if note["flds"]]

            if use_ai_syllabus and all_tags:
                try:
                    plan = generate_syllabus_from_tags(all_tags, self.subject, note_samples)
                except Exception as e:
                    _cb(f"⚠️  AI シラバス生成失敗 ({e})。簡易シラバスを作成します。")
                    plan = self._make_simple_plan_from_tags(all_tags)
            else:
                plan = self._make_simple_plan_from_tags(all_tags)

            if not plan:
                plan = [{"id": "anki_uncategorized", "name": "未分類", "keywords": [], "sub_topics": []}]

            # ── Step 5: 問題の振り分け ────────────────────
            _cb("📂 問題を章に振り分け中...")
            assigned = assign_topic_ids(notes, plan)

            # ── Step 6: オート・シャィディング (20枚分割) ──
            _cb("✂️  大きな分野を小分けに分割中...")
            assigned, plan = self._shard_plan(assigned, plan, max_per_topic=20)

            # ── Step 7: DB への登録 ───────────────────────
            _cb("💾 学習計画をデータベースに登録中...")
            _register_plan(self.subject, plan)

            _cb("💾 問題をデータベースに登録中...")
            registered = _register_questions(self.subject, assigned, _cb)

            _cb(f"🎉 インポート完了！ {len(plan)} 章の学習計画と {registered} 問、{media_count} 件のメディアを登録しました。")
            return {
                "success":    True,
                "message":    f"{len(plan)} 章の学習計画と {registered} 問、{media_count} 件のメディアを登録しました。",
                "plan":       plan,
                "note_count": registered,
                "media_count": media_count,
            }

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            return {"success": False, "message": f"エラー: {e}\n{tb}", "plan": [], "note_count": 0, "media_count": 0}
        finally:
            self._cleanup()

    def _find_anki2(self) -> str:
        for name in ("collection.anki21", "collection.anki2"):
            path = os.path.join(self._work_dir, name)
            if os.path.exists(path):
                return path
        raise FileNotFoundError("collection.anki2 が見つかりません。")

    @staticmethod
    def _make_simple_plan_from_tags(all_tags: List[str]) -> List[Dict]:
        from collections import Counter
        tag_counts = Counter(all_tags)
        top_tags   = [tag for tag, _ in tag_counts.most_common(30)]
        if not top_tags:
            return [{"id": "anki_uncategorized", "name": "未分類", "keywords": [], "sub_topics": []}]
        plan = []
        for i, tag in enumerate(top_tags, 1):
            safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", tag)
            plan.append({"id": f"tag_{safe_id}_{i}", "name": tag, "keywords": [tag], "sub_topics": []})
        return plan

    def _cleanup(self):
        if self._work_dir and os.path.exists(self._work_dir):
            shutil.rmtree(self._work_dir, ignore_errors=True)
            self._work_dir = None


def reorganize_syllabus_from_summaries(
    subject:     str,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Dict:
    """
    保存済みの全メディア要約をAIに渡し、最適なシラバスを再構築し、
    全ての問題を新しい章に振り分け直す。
    """
    import database as _db
    import ai_engine
    import time
    import sqlite3

    def _cb(msg: str):
        if progress_cb: progress_cb(msg)

    _cb("📋 全メディア要約を取得中...")
    summaries = _db.get_all_media_summaries(subject)
    if not summaries:
        return {"success": False, "message": "画像要約データが見つかりません。解析が終わるまでお待ちください。"}

    _cb(f"🧠 {len(summaries)} 件の要約を基にシラバスを再構成中...")
    
    # 要約リストをテキスト化
    summary_list_str = "\n".join(f"- {fname}: {text[:150]}" for fname, text in summaries.items())
    
    prompt = f"""あなたは教育専門家です。
以下の画像要約リスト（Ankiデッキから抽出されたもの）を分析し、これらを学習するのに最適な体系的な学習計画（シラバス）を再構築してください。

【画像要約リスト】
{summary_list_str}

【出力形式】
JSONのみ。以下の構造で5〜10章程度にまとめてください。
[
  {{
    "id": "ch_1",
    "name": "章のタイトル",
    "keywords": ["この章に含めるべき画像のファイル名", "キーワード", ...],
    "sub_topics": []
  }},
  ...
]

【ルール】
- 各章の `keywords` には、その章に分類されるべき「画像ファイル名」を可能な限り含めてください。
- すべての画像がいずれかの章に収まるようにしてください。
- 脈略がない場合は、内容が近いもの同士をグループ化してください。
"""

    try:
        raw = ai_engine.gemini_once_json(prompt)
        new_plan = json.loads(raw)
        if not isinstance(new_plan, list): raise ValueError("AIからの回答がリスト形式ではありません。")

        _cb("📂 新しい章に問題を振り分け中...")
        
        # questionテーブルから全問題を取得
        conn = sqlite3.connect(_db.db_path(subject))
        rows = conn.execute("SELECT id, question, answer FROM question").fetchall()
        conn.close()

        notes = []
        for r in rows:
            notes.append({
                "id": r[0],
                "flds": [r[1], r[2]],
                "tags": []
            })

        # 振り分け
        assigned = assign_topic_ids(notes, new_plan)
        
        # オート・シャィディング (20枚分割)
        # AnkiImporterのインスタンスを作って実行
        importer = AnkiImporter(None, subject)
        final_assigned, final_plan = importer._shard_plan(assigned, new_plan, max_per_topic=20)

        # DB更新
        _db.save_cfg(subject, {"plan": final_plan})
        
        conn = sqlite3.connect(_db.db_path(subject))
        try:
            for note, tid in final_assigned:
                conn.execute("UPDATE question SET topic_id=? WHERE id=?", (tid, note["id"]))
            conn.commit()
        finally:
            conn.close()

        _cb("✅ シラバスの再構成と問題の再配置が完了しました。")
        return {"success": True, "message": "シラバスを再構成しました。", "plan": final_plan}

    except Exception as e:
        _cb(f"❌ エラー: {e}")
        return {"success": False, "message": str(e)}


def batch_classify_with_ai(
    subject:     str,
    plan:        List[Dict],
    batch_size:  int = 20,
    delay_sec:   float = 2.0,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> None:
    import time
    import database as _db
    import ai_engine

    def _cb(msg: str):
        if progress_cb: progress_cb(msg)

    conn = sqlite3.connect(_db.db_path(subject))
    try:
        rows = conn.execute("SELECT id, question FROM question ORDER BY id").fetchall()
    finally:
        conn.close()

    total   = len(rows)
    updated = 0
    flat_topics = []
    for ch in plan:
        for sub in ch.get("sub_topics", []) or [ch]:
            flat_topics.append({"id": sub["id"], "name": sub["name"]})

    topic_list_str = "\n".join(f"- id: {t['id']}  名前: {t['name']}" for t in flat_topics)

    for batch_start in range(0, total, batch_size):
        batch = rows[batch_start: batch_start + batch_size]
        qs_str = "\n".join(f"[id={r[0]}] {r[1][:120]}" for r in batch)
        prompt = (f"以下の問題リストを、与えられたトピックリストのいずれかに分類してください。\n\n"
                  f"【トピックリスト】\n{topic_list_str}\n\n"
                  f"【問題リスト】\n{qs_str}\n\n"
                  f"【出力形式】JSONのみ。例: [{{\"id\": 1, \"topic_id\": \"chapter_1_1\"}}, ...]")

        try:
            raw = ai_engine.gemini_once_json(prompt)
            results = json.loads(raw)
            conn = sqlite3.connect(_db.db_path(subject))
            try:
                for item in results:
                    conn.execute("UPDATE question SET topic_id=? WHERE id=?", (item["topic_id"], item["id"]))
                    updated += 1
                conn.commit()
            finally:
                conn.close()
            _cb(f"AI 再分類中... ({min(batch_start + batch_size, total)}/{total})")
        except Exception as e:
            _cb(f"⚠️  バッチ {batch_start}〜{batch_start+batch_size} でエラー: {e}")
        if batch_start + batch_size < total:
            time.sleep(delay_sec)

    _cb(f"✅ AI 再分類完了。{updated} 件を更新しました。")
