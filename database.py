# Copyright (c) 2026 Datan (データン)
# Licensed under a Custom Hybrid License (Free for Individuals, Paid for Commercial).
# See README.md for licensing details.
# -*- coding: utf-8 -*-
"""
=======================================================
  database.py (データ永続化層)
  SQLiteデータベースの作成・読み書きのみを 担当
  UIや外部API(Gemini)には依存しません。
=======================================================
"""

import os
import sys
import json
import sqlite3
import datetime
import math
from typing import List, Dict, Any, Optional

# DBファイルを保存するディレクトリ
# PyInstaller --onefile でEXE化された場合、__file__ は一時フォルダ(_MEIPASS)を指すため
# データが起動のたびに消滅する。sys.executable（EXE本体のパス）を使うことで回避する。
if getattr(sys, 'frozen', False):
    # EXE化されている場合は、EXE本体があるディレクトリを使用する
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 通常のスクリプト実行時はスクリプトのディレクトリを使用する
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# =====================================================
#  各種設定・定数
# =====================================================
QUESTION_POOL_MAX = 50
NEW_Q_NORMAL      = 4
NEW_Q_FULL        = 1

# 忘却曲線に基づく復習間隔（正解連続回数 -> 次回出題までの日数）
REVIEW_INTERVALS = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}
REVIEW_INTERVAL_MAX = 60

# =====================================================
#  DBスキーマ バージョン管理
# =====================================================
DB_SCHEMA_VERSION = 4  # 現在のDBスキーマ最新バージョン

def _migrate_db(conn: sqlite3.Connection) -> None:
    """
    DBファイルの PRAGMA user_version を確認し、古ければ順番にマイグレーションを実行する。
    将来バージョンを追加する際は「if current_version < N:」ブロックをここに追記する。
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA user_version")
    current_version = cursor.fetchone()[0]

    if current_version < 1:
        # v0 → v1: 初期テーブル群は CREATE TABLE IF NOT EXISTS で保証するため、ここでは何もしない
        pass

    if current_version < 2:
        # v1 → v2: 忘却曲線・出題形式カラムを追加（既存カラムは例外を無視してスキップ）
        for col, default in [
            ("last_asked_at",       "NULL"),
            ("consecutive_correct", "0"),
            ("next_review_date",    "NULL"),
            ("format",              "'記述式問題'"),
        ]:
            try:
                conn.execute(
                    f"ALTER TABLE question ADD COLUMN {col} TEXT DEFAULT {default}"
                )
            except Exception:
                pass  # 既にカラムが存在する場合は無視

    if current_version < 3:
            # v2 → v3: study_log テーブルに correct カラムを追加
            try:
                conn.execute("ALTER TABLE study_log ADD COLUMN correct INTEGER DEFAULT 0")
            except Exception:
                pass # 既に存在する場合はスキップ

    if current_version < 4:
        # v3 → v4: 既存の問題のフォーマットを模範解答の内容から自動判定して一括更新
        try:
            rows = conn.execute("SELECT id, answer, format FROM question").fetchall()
            for qid, ans, current_fmt in rows:
                ans_str = str(ans).strip()
                new_fmt = current_fmt
                if ans_str in ["○", "×", "正", "誤", "正しい", "誤り", "〇"]:
                    new_fmt = "正誤問題"
                elif ans_str in ["1", "2", "3", "4", "5", "①", "②", "③", "④", "⑤"]:
                    new_fmt = "5肢択一問題"
                
                if new_fmt != current_fmt:
                    conn.execute("UPDATE question SET format=? WHERE id=?", (new_fmt, qid))
        except Exception:
            pass

    # 将来 v4 が必要になったら以下のブロックを追記する
    # if current_version < 4:
    #     conn.execute("ALTER TABLE question ADD COLUMN new_col TEXT DEFAULT NULL")

    # 最新バージョン番号をDBファイル自体に記録
    conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
    conn.commit()

# =====================================================
#  共通 I/O
# =====================================================
def db_path(subject: str) -> str:
    """指定された科目のDBファイルパスを返す"""
    return os.path.join(BASE_DIR, f"{subject}.db")

def get_media_dir(subject: str) -> str:
    """
    Ankiインポート時の画像格納フォルダ <BASE_DIR>/<subject>_media/ のパスを返す。
    存在しなければ自動的に作成する。
    """
    path = os.path.join(BASE_DIR, f"{subject}_media")
    os.makedirs(path, exist_ok=True)
    return path

def _get_conn(subject: str) -> sqlite3.Connection:
    """DBコネクションを取得し、configテーブルを保証する"""
    conn = sqlite3.connect(db_path(subject))
    # configテーブル：学習計画や進捗（JSON）をKeyValueで保存
    conn.execute(
        "CREATE TABLE IF NOT EXISTS config "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.commit()
    # 接続のたびにバージョンチェック → 古ければ自動マイグレーション
    _migrate_db(conn)
    return conn

def load_cfg(subject: str) -> Dict[str, Any]:
    """configテーブルから設定や進捗状況(JSON)を読み込む"""
    if not os.path.exists(db_path(subject)):
        return {}
    try:
        conn = _get_conn(subject)
        rows = conn.execute("SELECT key, value FROM config").fetchall()
        conn.close()
        data = {}
        for key, val in rows:
            try:
                data[key] = json.loads(val)
            except Exception:
                data[key] = val
        return data
    except Exception:
        return {}

def save_cfg(subject: str, data: Dict[str, Any]) -> None:
    """configテーブルへ設定や進捗状況(JSON)を保存する"""
    conn = _get_conn(subject)
    for key, val in data.items():
        conn.execute(
            "INSERT INTO config(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(val, ensure_ascii=False))
        )
    conn.commit()
    conn.close()

def list_subjects() -> List[str]:
    """スクリプトと同階層に存在するDBファイルから科目リストを取得する"""
    subjects = []
    for fname in os.listdir(BASE_DIR):
        if fname.endswith(".db"):
            subjects.append(fname[:-3])
    return subjects

# =====================================================
#  explane テーブル I/O (説明文の保存)
# =====================================================
def _ensure_explane_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS explane (
            topic_id   TEXT PRIMARY KEY,
            content    TEXT NOT NULL,
            weakness   TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()

def load_explane(subject: str, topic_id: str) -> Optional[str]:
    """指定したトピックの説明文（キャッシュ）を取得する"""
    if not os.path.exists(db_path(subject)):
        return None
    try:
        conn = _get_conn(subject)
        _ensure_explane_table(conn)
        row = conn.execute("SELECT content FROM explane WHERE topic_id=?", (topic_id,)).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None

def save_explane(subject: str, topic_id: str, content: str, weakness: str = "") -> None:
    """AIが生成した説明文をDBに保存（キャッシュ）する"""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    conn = _get_conn(subject)
    _ensure_explane_table(conn)
    
    existing = conn.execute("SELECT created_at FROM explane WHERE topic_id=?", (topic_id,)).fetchone()
    created_at = existing[0] if existing else now
    
    conn.execute("""
        INSERT INTO explane(topic_id, content, weakness, created_at, updated_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(topic_id) DO UPDATE SET
            content    = excluded.content,
            weakness   = excluded.weakness,
            updated_at = excluded.updated_at
    """, (topic_id, content, weakness, created_at, now))
    conn.commit()
    conn.close()

# =====================================================
#  Question テーブル I/O (テスト問題と成績)
# =====================================================
def _ensure_question_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS question (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id            TEXT    NOT NULL,
            question            TEXT    NOT NULL,
            answer              TEXT    NOT NULL,
            explanation         TEXT    DEFAULT '',
            asked_count         INTEGER DEFAULT 0,
            correct_count       INTEGER DEFAULT 0,
            correct_rate        REAL    DEFAULT 0.0,
            consecutive_correct INTEGER DEFAULT 0,
            next_review_date    TEXT    DEFAULT NULL,
            last_asked_at       TEXT    DEFAULT NULL,
            created_at          TEXT,
            format              TEXT    DEFAULT '記述式問題'
        )
    """)
    conn.commit()

def _ensure_study_log_table(conn: sqlite3.Connection) -> None:
    """学習記録（ヒートマップ用）のテーブルを保証し、初期データがあれば移行する"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_log (
            date  TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0,
            correct INTEGER DEFAULT 0
        )
    """)
    # もし学習記録がまだ1件もなければ、過去の question テーブルから実績をサルベージする
    row = conn.execute("SELECT COUNT(*) FROM study_log").fetchone()
    if row and row[0] == 0:
        try:
            conn.execute("""
                INSERT INTO study_log (date, count)
                SELECT substr(last_asked_at,1,10) as d, COUNT(*) as cnt
                FROM question 
                WHERE last_asked_at IS NOT NULL 
                GROUP BY d
            """)
        except Exception:
            pass # questionテーブルがまだ無い初期状態などのエラーは無視
    conn.commit()

def count_all_questions(subject: str) -> int:
    """科目全体に蓄積された問題の総数を取得する"""
    if not os.path.exists(db_path(subject)):
        return 0
    conn = _get_conn(subject)
    _ensure_question_table(conn)
    row = conn.execute("SELECT COUNT(*) FROM question").fetchone()
    conn.close()
    return row[0] if row else 0

def get_review_questions(subject: str) -> List[Dict[str, Any]]:
    """本日の復習対象となる問題を忘却曲線スコアでソートして返す"""
    if not os.path.exists(db_path(subject)):
        return []
    conn = _get_conn(subject)
    _ensure_question_table(conn)
    today_str = datetime.date.today().isoformat()
    
    # 次回レビュー日が今日以前、または未設定（新規）のものを取得
    rows = conn.execute("""
        SELECT id, topic_id, question, answer, explanation,
               asked_count, correct_rate, consecutive_correct,
               next_review_date, last_asked_at, format
        FROM question
        WHERE next_review_date IS NULL OR next_review_date <= ?
        ORDER BY next_review_date ASC, correct_rate ASC
    """, (today_str,)).fetchall()
    conn.close()

    today = datetime.date.today()
    scored = []
    for r in rows:
        (qid, tid, q, a, expl, asked, rate, streak, next_rev, last_at, fmt) = r
        asked  = int(asked  or 0)
        rate   = float(rate   or 0.0)
        streak = int(streak or 0)

        # スコアリングロジック（スコアが高いほど優先的に出題）
        if asked == 0 or next_rev is None:
            score = 999.0  # 未出題は最優先
        else:
            try:
                last_date = datetime.date.fromisoformat(last_at[:10]) if last_at else today
                days = max(1, (today - last_date).days)
            except Exception:
                days = 1
            # 経過日数の対数を取り、正解率が低く、連続正解が少ないものほど高スコア
            score = (1.0 - rate) * math.log(days + 1) / (1.0 + streak)

        scored.append({
            "id": qid, "topic_id": tid, "question": q, "answer": a,
            "explanation": expl, "asked_count": asked,
            "correct_rate": rate, "consecutive_correct": streak,
            "next_review_date": next_rev, "last_asked_at": last_at,
            "review_score": score,
            "format": fmt
        })
    
    # スコアの降順（優先度が高い順）にソート
    scored.sort(key=lambda x: x["review_score"], reverse=True)
    return scored

def get_question_pool(subject: str, topic_id: str,
                      question_format: str = None) -> List[Dict[str, Any]]:
    """特定のトピックに属する全問題を取得（テスト生成時のレビュー問題抽出用）。
    question_format を指定すると同形式の問題のみを返す（形式混在防止）。
    """
    if not os.path.exists(db_path(subject)):
        return []
    conn = _get_conn(subject)
    _ensure_question_table(conn)
    if question_format:
        rows = conn.execute("""
            SELECT id, question, answer, explanation, asked_count, correct_count, correct_rate, format
            FROM question
            WHERE topic_id = ? AND format = ?
            ORDER BY correct_rate ASC, asked_count ASC
        """, (topic_id, question_format)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, question, answer, explanation, asked_count, correct_count, correct_rate, format
            FROM question WHERE topic_id = ? ORDER BY correct_rate ASC, asked_count ASC
        """, (topic_id,)).fetchall()
    conn.close()
    return [{"id": r[0], "question": r[1], "answer": r[2], "explanation": r[3],
             "asked_count": r[4], "correct_count": r[5], "correct_rate": r[6], "format": r[7]} for r in rows]

def add_questions_to_pool(subject: str, topic_id: str, new_qs: List[Dict[str, str]],
                          question_format: str = "記述式問題") -> None:
    """AIが生成した新しい問題のリストをDBに追加する"""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    conn = _get_conn(subject)
    _ensure_question_table(conn)
    for q in new_qs:
        conn.execute(
            "INSERT INTO question(topic_id, question, answer, created_at, format) VALUES(?,?,?,?,?)",
            (topic_id, q["question"], q["answer"], now, question_format)
        )
    conn.commit()
    conn.close()

def get_recent_questions(subject: str, topic_id: str, limit: int) -> List[Dict[str, Any]]:
    """直近に追加された問題を limit 件取得する（新規テスト生成直後用）"""
    conn = _get_conn(subject)
    _ensure_question_table(conn)
    # idの降順で取得してから反転させることで、追加された順序を保つ
    rows = conn.execute("SELECT id, question, answer, format FROM question WHERE topic_id=? ORDER BY id DESC LIMIT ?", (topic_id, limit)).fetchall()
    conn.close()
    return [{"id": r[0], "question": r[1], "answer": r[2], "format": r[3]} for r in reversed(rows)]

def update_question_result(subject: str, qid: int, correct: bool, explanation: str = "") -> None:
    """採点結果をDBに反映し、日ごとの学習ログ（回答数・正解数）を更新する"""
    conn = _get_conn(subject)
    _ensure_question_table(conn)
    row = conn.execute("SELECT asked_count, correct_count, consecutive_correct FROM question WHERE id=?",(qid,)).fetchone()
    if row:
        asked        = int(row[0] or 0) + 1
        correct_cnt  = int(row[1] or 0) + (1 if correct else 0)
        rate         = correct_cnt / asked
        today        = datetime.date.today()
        today_str    = today.isoformat()

        if correct:
            new_streak   = int(row[2] or 0) + 1
            days_to_add  = REVIEW_INTERVALS.get(new_streak, REVIEW_INTERVAL_MAX)
            next_rev     = (today + datetime.timedelta(days=days_to_add)).isoformat()
        else:
            new_streak   = 0
            next_rev     = (today + datetime.timedelta(days=1)).isoformat()

        conn.execute("""
            UPDATE question
            SET asked_count=?, correct_count=?, correct_rate=?, consecutive_correct=?, next_review_date=?, last_asked_at=?,
                explanation=CASE WHEN ? != '' THEN ? ELSE explanation END
            WHERE id=?
        """, (asked, correct_cnt, rate, new_streak, next_rev, today_str, explanation, explanation, qid))
        
        # 学習ログの更新：count(回答数)に加え、correct(正解数)も記録
        _ensure_study_log_table(conn)
        conn.execute("""
            INSERT INTO study_log (date, count, correct)
            VALUES (?, 1, ?)
            ON CONFLICT(date) DO UPDATE SET 
                count = count + 1,
                correct = correct + excluded.correct
        """, (today_str, 1 if correct else 0))
        
    conn.commit()
    conn.close()

# =====================================================
#  統計用データ取得 (レーダーチャート、ヒートマップ等)
# =====================================================
def get_radar_data(subject: str, plan: list,
                   topic_settings: dict = None) -> List[Dict[str, Any]]:
    """分野ごとの正解率平均を計算して返す（レーダーチャート用）。
    topic_settings を渡すと現在の出題形式のみで集計し、形式名も返す。
    """
    if not os.path.exists(db_path(subject)):
        return []
    conn = _get_conn(subject)
    _ensure_question_table(conn)
    result = []
    ts = topic_settings or {}

    for top in plan:
        subs = top.get("sub_topics", [])
        if subs:
            rates = []
            fmt_set = set()
            for st in subs:
                fmt = ts.get(st["id"])
                if fmt:
                    row = conn.execute(
                        "SELECT AVG(correct_rate) FROM question WHERE topic_id=? AND format=?",
                        (st["id"], fmt)
                    ).fetchone()
                    fmt_set.add(fmt)
                else:
                    row = conn.execute(
                        "SELECT AVG(correct_rate) FROM question WHERE topic_id=?",
                        (st["id"],)
                    ).fetchone()
                if row and row[0] is not None:
                    rates.append(float(row[0]))
            avg = sum(rates) / len(rates) if rates else 0.0
            # 形式名：全サブ分野が同じ形式なら統一表示、混在なら「複数形式」
            fmt_label = list(fmt_set)[0] if len(fmt_set) == 1 else ("複数形式" if fmt_set else None)
            result.append({"label": top["name"], "rate": avg, "format": fmt_label})
        else:
            fmt = ts.get(top["id"])
            if fmt:
                row = conn.execute(
                    "SELECT AVG(correct_rate) FROM question WHERE topic_id=? AND format=?",
                    (top["id"], fmt)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT AVG(correct_rate) FROM question WHERE topic_id=?",
                    (top["id"],)
                ).fetchone()
            avg = float(row[0]) if row and row[0] is not None else 0.0
            result.append({"label": top["name"], "rate": avg, "format": fmt})
    conn.close()
    return result

def get_review_forecast(subject: str) -> List[Dict[str, Any]]:
    """今日から7日後までの、各日にレビューが必要な問題数を返す（棒グラフ用）"""
    if not os.path.exists(db_path(subject)):
        return []
    today = datetime.date.today()
    conn  = _get_conn(subject)
    _ensure_question_table(conn)
    forecast = []
    for i in range(7):
        d = (today + datetime.timedelta(days=i)).isoformat()
        
        if i == 0:
            # 今日の分には、今日以前（復習遅延分）と未設定（新規）をすべて含める
            rows = conn.execute(
                "SELECT topic_id, COUNT(*) FROM question WHERE next_review_date <= ? OR next_review_date IS NULL GROUP BY topic_id", 
                (d,)
            ).fetchall()
        else:
            # 明日以降は、その日の分だけを集計
            rows = conn.execute(
                "SELECT topic_id, COUNT(*) FROM question WHERE next_review_date = ? GROUP BY topic_id", 
                (d,)
            ).fetchall()
            
        topic_counts = {r[0]: r[1] for r in rows}
        total_count = sum(topic_counts.values())
        forecast.append({"date": d, "count": total_count, "topics": topic_counts})
    conn.close()
    return forecast

def get_heatmap_data(subject: str) -> Dict[str, Dict[str, int]]:
    """日付ごとに解いた問題数と正解数を辞書形式で返す"""
    if not os.path.exists(db_path(subject)):
        return {}
    conn = _get_conn(subject)
    _ensure_study_log_table(conn)
    
    rows = conn.execute("SELECT date, count, correct FROM study_log").fetchall()
    conn.close()
    
    # 戻り値を辞書のネスト構造に変更
    return {r[0]: {"count": r[1], "correct": r[2]} for r in rows if r[0]}

# =====================================================
#  Anki エクスポート等 汎用取得関数
# =====================================================
def get_questions_for_export(subject: str, filter_type: str = "ALL") -> List[Dict[str, str]]:
    """
    指定された条件に従ってエクスポート用の問題リストを取得する。
    filter_type: "ALL" | "WEAK" | "RECENT_WRONG"
    """
    if not os.path.exists(db_path(subject)):
        return []
        
    conn = _get_conn(subject)
    _ensure_question_table(conn)

    # 除外条件：問題・回答・解説のいずれかに ```python が含まれていたら弾く
    exclude_cond = (
        "question NOT LIKE '%```python%' "
        "AND answer NOT LIKE '%```python%' "
        "AND (explanation IS NULL OR explanation NOT LIKE '%```python%')"
    )

    if filter_type == "WEAK":
        # 1回以上出題されていて、正解率が80%未満の問題
        query = f"SELECT question, answer, explanation FROM question WHERE asked_count > 0 AND correct_rate < 0.8 AND {exclude_cond}"
    elif filter_type == "RECENT_WRONG":
        # 直近で間違えた（連続正解が0の）問題
        query = f"SELECT question, answer, explanation FROM question WHERE asked_count > 0 AND consecutive_correct = 0 AND {exclude_cond}"
    else:  # "ALL"
        # すべての問題
        query = f"SELECT question, answer, explanation FROM question WHERE {exclude_cond}"


    rows = conn.execute(query).fetchall()
    conn.close()
    return [{"question": r[0], "answer": r[1], "explanation": r[2]} for r in rows]

# =====================================================
#  メディアメタデータ（画像要約）の保存・取得
# =====================================================
def _ensure_media_meta_table(conn: sqlite3.Connection) -> None:
    # 既存のテーブルにカラムがあるかチェックして自動マイグレーション
    cur = conn.execute("PRAGMA table_info(media_meta)")
    columns = [row[1] for row in cur.fetchall()]
    
    if not columns:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS media_meta (
                filename TEXT PRIMARY KEY,
                summary  TEXT NOT NULL,
                embedding BLOB
            )
        """)
    elif "embedding" not in columns:
        conn.execute("ALTER TABLE media_meta ADD COLUMN embedding BLOB")
    
    conn.commit()

def save_media_summary(subject: str, filename: str, summary: str, embedding: list = None) -> None:
    """画像の要約とベクトルデータをDBに保存する"""
    import json
    conn = _get_conn(subject)
    _ensure_media_meta_table(conn)
    
    emb_data = json.dumps(embedding) if embedding else None
    
    conn.execute(
        "INSERT OR REPLACE INTO media_meta (filename, summary, embedding) VALUES (?, ?, ?)",
        (filename, summary, emb_data)
    )
    conn.commit()
    conn.close()

def get_all_media_summaries(subject: str) -> dict:
    """科目に紐づく全画像の要約を辞書形式で取得する"""
    if not os.path.exists(db_path(subject)):
        return {}
    conn = _get_conn(subject)
    _ensure_media_meta_table(conn)
    rows = conn.execute("SELECT filename, summary FROM media_meta").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def get_all_media_with_embeddings(subject: str) -> list:
    """その科目に紐づく全ての画像データ（要約とベクトル）を取得する"""
    import json
    if not os.path.exists(db_path(subject)):
        return []
    conn = _get_conn(subject)
    _ensure_media_meta_table(conn)
    rows = conn.execute("SELECT filename, summary, embedding FROM media_meta").fetchall()
    conn.close()
    
    result = []
    for r in rows:
        emb = None
        if r[2]:
            try:
                emb = json.loads(r[2])
            except:
                pass
        result.append({"filename": r[0], "summary": r[1], "embedding": emb})
    return result

# =====================================================
#  問題の削除
# =====================================================
def delete_question(subject: str, qid: int) -> None:
    """指定されたIDの問題をDBから削除する"""
    conn = _get_conn(subject)
    _ensure_question_table(conn)
    conn.execute("DELETE FROM question WHERE id=?", (qid,))
    conn.commit()
    conn.close()

# =====================================================
#  トピックの習熟度の取得
# =====================================================
def get_topic_mastery_stats(subject: str, topic_id: str,
                            question_format: str = None) -> dict:
    """トピック内の (直近正解数, 全小問数) を返す。
    question_format を指定すると同形式の問題のみで集計する。
    """
    if not os.path.exists(db_path(subject)):
        return {"correct": 0, "total": 0}
    conn = _get_conn(subject)
    _ensure_question_table(conn)

    if question_format:
        total = conn.execute(
            "SELECT COUNT(*) FROM question WHERE topic_id=? AND format=?",
            (topic_id, question_format)
        ).fetchone()[0]
        correct = conn.execute(
            "SELECT COUNT(*) FROM question WHERE topic_id=? AND format=? AND consecutive_correct > 0",
            (topic_id, question_format)
        ).fetchone()[0]
    else:
        total = conn.execute(
            "SELECT COUNT(*) FROM question WHERE topic_id=?", (topic_id,)
        ).fetchone()[0]
        correct = conn.execute(
            "SELECT COUNT(*) FROM question WHERE topic_id=? AND consecutive_correct > 0",
            (topic_id,)
        ).fetchone()[0]

    conn.close()
    return {"correct": correct, "total": total}

# =====================================================
#  科目学習データの全リセット
# =====================================================
def reset_subject_learning_data(subject: str) -> None:
    """
    学習計画を作り直す際に呼び出す。
    question・explane・study_log テーブルのデータを全削除する。
    config テーブル（学習計画・設定）には触れない。
    """
    if not os.path.exists(db_path(subject)):
        return
    conn = _get_conn(subject)
    
    # ▼▼▼ 修正：削除を実行する前に、テーブルの存在を保証する ▼▼▼
    _ensure_question_table(conn)
    _ensure_explane_table(conn)
    _ensure_study_log_table(conn)
    # ▲▲▲ ここまで追加 ▲▲▲

    conn.execute("DELETE FROM question")
    conn.execute("DELETE FROM explane")
    conn.execute("DELETE FROM study_log")
    conn.commit()
    conn.close()