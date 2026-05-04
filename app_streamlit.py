# Copyright (c) 2026 Datan (データン)
# Licensed under a Custom Hybrid License (Free for Individuals, Paid for Commercial).
# See README.md for licensing details.
# -*- coding: utf-8 -*-
"""
=======================================================
  app_streamlit.py (UI層)
  StreamlitによるGUI表示とユーザーイベントのハンドリング
  ai_engine.py と database.py、anki_exporter.py、
  anki_importer.pyに依存します。
  ※google.genai は直接インポートしません（完全分離）
  ※スマホのカメラ機能を動かすには、Chromeの「サイトの設定」から
  「カメラ」を「許可」にするとともに、スマホのChromeの
    chrome://flags/#unsafely-treat-insecure-origin-as-secure
    に、サーバーのhttpオリジンを追加してください。
=======================================================
"""

import streamlit as st
import datetime
import time
import json
import os
import sys
import tkinter as tk
import tkinter.simpledialog as sd
import shutil
import re
import base64
import tempfile
import pandas as pd
import plotly.graph_objects as go
import io

# 既存のビジネスロジックをインポート
import ai_engine
import database
import anki_exporter


def apply_custom_styles():
    """画面タイトル(h1)を少し小さくし、濃い青色に統一、およびスマホ用文字色調整"""
    st.markdown(
        """
        <style>
        .stApp h1 {
            font-size: 1.6rem;
            color: #1e90ff; /* 濃い青色 */
        }
        /* 追加：Plotlyのドロップダウンメニューの文字色と背景を強制指定 */
        .js-plotly-plot .updatemenu-button {
            fill: #333333 !important;
        }
        .js-plotly-plot .updatemenu-item rect {
            fill: #ffffff !important;
            stroke: #d0e0f0 !important;
        }
        .js-plotly-plot .updatemenu-item text {
            fill: #333333 !important;
        }
        /* 追加：スマホでグラフを横スクロールさせるための容器 */
        .scroll-container {
            overflow-x: auto;
            white-space: nowrap;
            -webkit-overflow-scrolling: touch;
            margin-bottom: 20px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# --- 0. 共通プロンプト・ヘルパー ---
def get_full_media_block(subject: str, query: str = None) -> str:
    """
    画像要約とベクトルデータを利用し、クエリに関連する上位10件の画像情報をプロンプト用に構築する。
    """
    all_media = database.get_all_media_with_embeddings(subject)
    if not all_media:
        return "\n【画像出力の禁止】現在利用可能な画像データはありません。架空の画像ファイル名を作成して `<img src=\"...\">` のようなタグを出力することは絶対にやめてください。\n"
    
    # クエリがある場合はベクトル検索で上位10件を抽出、なければ全件から先頭10件
    if (query and query.strip()):
        relevant_media = ai_engine.find_top_relevant_images(query, all_media, top_n=10)
    else:
        relevant_media = all_media[:10]
    
    block = "\n\n【利用可能な画像データ（最優先ルール：関連上位10件のみ）】\n"
    block += "【重要】画像を表示する場合は、必ず以下のリストにある正確なファイル名を用いて `<img src=\"ファイル名\">` の形式で出力してください。リストにない架空のファイル名は絶対に生成・使用しないでください。\n"
    for m in relevant_media:
        block += f"- {m['filename']}: {m['summary']}\n"
    
    block += "\n【図表出力の優先ルール】\n"
    block += "説明、問題、回答、または解説に図解が必要な場合、まずは提供された画像データの中に適切なものがあれば `<img src=\"ファイル名\">` を優先して使用してください。\n"
    block += "該当する画像がない場合に限り、Plotlyを用いたPythonコードを作成して図表を自作してください（matplotlib不可）。\n"
    return block

def safe_json_parse(raw_text):
    """AIの出力を安全にパースし、エラー時はデフォルト構造を返す"""
    try:
        data = json.loads(ai_engine._extract_json(raw_text))
        return data
    except:
        return {"total_score": 0, "results": [], "overall_comment": "解析エラーが発生しました。", "weakness": "", "recommendation": "stay"}

def show_friendly_error(e):
    """Gemini APIのエラー内容に応じて分かりやすいメッセージを表示する"""
    err_str = str(e).lower()
    if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
        st.error("🤖 Geminiのサーバーが現在大変混み合っています。数分待ってから、もう一度お試しください。(503 Unavailable)")
    elif "429" in err_str or "quota" in err_str or "exhausted" in err_str:
        st.error("⚠️ APIの利用制限（リクエスト上限）に達しました。しばらく時間を置くか、設定を確認してください。(429 Too Many Requests)")
    elif "500" in err_str or "internal" in err_str:
        st.error("🌀 Geminiのサーバー側で一時的なエラーが発生しました。時間をおいて再度お試しください。(500 Internal Server Error)")
    else:
        st.error(f"❌ 予期せぬエラーが発生しました: {e}")

def render_ai_response(text: str):
    """
    AIの返答テキストを解析し、Plotlyコード、および <img> タグを処理して表示する。
    """
    subj = st.session_state.current_subject
    media_dir = database.get_media_dir(subj) if subj else ""

    # 1. まず Plotly コードブロックで分割
    pattern = r'```python\s*\n([\s\S]*?)```'
    parts = re.split(pattern, text)

    for i, part in enumerate(parts):
        if i % 2 == 0:
            # --- テキスト部分（<img> タグが含まれる可能性がある） ---
            if not part.strip():
                continue

            # <img> タグを探して分割する
            # 例: <img src="filename.jpg">
            img_pattern = r'(<img\s+src=["\']([^"\']+)["\']\s*/?>)'
            sub_parts = re.split(img_pattern, part, flags=re.IGNORECASE)
            
            # sub_parts は [テキスト, 全タグ, ファイル名, テキスト...] という構造になる
            # インデックスが 0, 3, 6... が純粋なテキスト
            # インデックスが 2, 5, 8... がファイル名
            idx = 0
            while idx < len(sub_parts):
                # テキストの表示
                if sub_parts[idx].strip():
                    st.markdown(sub_parts[idx], unsafe_allow_html=True)
                
                # 画像の表示
                if idx + 2 < len(sub_parts):
                    img_filename = sub_parts[idx + 2]
                    img_path = os.path.join(media_dir, img_filename)
                    
                    if os.path.exists(img_path):
                        # Streamlit標準の st.image を使用
                        st.image(img_path, caption=img_filename)
                    else:
                        st.warning(f"画像が見つかりません: {img_filename}")
                    idx += 3
                else:
                    idx += 1
        else:
            # 奇数インデックス → Pythonコード部分
            # Plotlyのグラフ描画を試みる
            try:
                import plotly.graph_objects as go
                import pandas as pd
                
                # 追加の便利ライブラリは、環境に無い場合も想定して安全にインポート（デグレ防止）
                try:
                    import plotly.express as px
                except ImportError:
                    px = None
                try:
                    import numpy as np
                except ImportError:
                    np = None
                    
                local_ns = {}
                code_to_run = part.replace("fig.show()", "")
                
                # AIが使う可能性が高いライブラリを渡す
                exec_env = {
                    "go": go,
                    "pd": pd,
                    "__builtins__": __builtins__
                }
                if px: exec_env["px"] = px
                if np: exec_env["np"] = np
                
                exec(code_to_run, exec_env, local_ns)
                
                # 変数名が 'fig' 以外の場合（AIの命名ブレ）もPlotlyオブジェクトを探索して表示
                fig = local_ns.get("fig")
                if fig is None:
                    for val in local_ns.values():
                        if isinstance(val, go.Figure):
                            fig = val
                            break
                            
                if fig is not None:
                    st.plotly_chart(fig, width="stretch")
                else:
                    # グラフが見つからなければ元のコードブロックを表示（欠落防止）
                    st.code(part, language="python")
            except Exception:
                # どんな実行エラーが起きてもアプリを止めず、コードとして表示させる（欠落防止）
                st.code(part, language="python")

# --- 1. セッション状態の初期化 ---
if "page" not in st.session_state: st.session_state.page = "start"
if "current_subject" not in st.session_state: st.session_state.current_subject = None
if "current_topic" not in st.session_state: st.session_state.current_topic = None
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "result_chat_history" not in st.session_state: st.session_state.result_chat_history = []
if "test_qs" not in st.session_state: st.session_state.test_qs = None
if "user_ans" not in st.session_state: st.session_state.user_ans = None
if "test_res" not in st.session_state: st.session_state.test_res = None
if "cfg_data" not in st.session_state: st.session_state.cfg_data = None
if "pending_plan" not in st.session_state: st.session_state.pending_plan = None


# APIキー設定（環境変数、設定ファイル、またはダイアログから）
def get_api_key_blocking():
    """
    APIキーを確認し、不足していればOSダイアログを表示して入力を促す。
    設定された場合は app_config.json に保存し、os.environ にもセットする。
    """
    # 1. 環境変数を確認
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key and api_key != "YOUR_API_KEY_HERE":
        return api_key

    # 2. app_config.json を確認 (Tkinter版と同じ場所を探す)
    base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    CONFIG_FILE = os.path.join(base_dir, "app_config.json")
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved_key = json.load(f).get("GEMINI_API_KEY")
                if saved_key and saved_key != "YOUR_API_KEY_HERE":
                    os.environ["GEMINI_API_KEY"] = saved_key # キャッシュとして環境変数にセット
                    return saved_key
        except Exception: pass

    # 3. ダイアログを表示 (PCローカル実行時のみ機能)
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.eval('tk::PlaceWindow . center')
        
        key = sd.askstring("API キー", "Gemini API キーを入力してください：\n（次回から入力不要になります）", parent=root)
        root.destroy()
        
        if key:
            os.environ["GEMINI_API_KEY"] = key # キャッシュとしてセット
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump({"GEMINI_API_KEY": key}, f)
            except Exception as e:
                print(f"キーの保存に失敗しました: {e}")
            return key
        else:
            # 入力されなかった場合はサーバーアプリを終了
            print("APIキーが入力されませんでした。終了します。")
            os._exit(0) 
            
    except Exception as e:
        # Tkinterが動作しない環境（ヘッドレスサーバーなど）の場合
        st.error(f"APIキーが設定されていません。環境変数 GEMINI_API_KEY を設定してください。 エラー: {e}")
        st.stop()
    return None

api_key = get_api_key_blocking()
if api_key: ai_engine.set_api_key(api_key)

def navigate_to(page_name):
    # --- 状態のリセット（他画面への影響を遮断） ---
    st.session_state.show_regen = False
    st.session_state.generate_audio = False

    st.session_state.page = page_name
    st.rerun()

# --- 2. 各画面の定義 ---

def show_start_screen():
    """1. 学習開始画面 [手順1]"""
    st.title("📚 AiTu - 学習開始")
    col1, col2, col3 = st.columns(3)
    if col1.button("📝 新規分野を選定", width="stretch"): navigate_to("new_subject")
    if col2.button("📂 既存分野を選択", width="stretch"): navigate_to("select_subject")
    if col3.button("🃏 Ankiから作成", width="stretch"): navigate_to("anki_import")

def show_new_subject_screen():
    """2. 新規分野の設定画面 [手順2]"""
    st.title("📝 新規分野の設定")
    with st.form("new_subject_form"):
        subj = st.text_input("分野名（例：統計学）")
        level = st.text_input("目標到達レベル")
        hours = st.text_input("目標到達までの時間（任意）")
        explain_level = st.text_input("説明のレベル", value="中学生にも分かるレベル")
        model = st.text_input("Geminiモデル", value=ai_engine.get_model())
        embedding_model = st.text_input("Embeddingモデル", value=ai_engine.get_embedding_model())
        notes = st.text_area("留意事項（任意）")
        
        stores = ai_engine.get_file_search_stores()
        store_opts = {"使用しない": None}
        for s in stores: store_opts[s["display"]] = s["name"]
        rag_disp = st.selectbox("RAG指定", list(store_opts.keys()))
        rag_type = st.radio("RAG資料の性質", ["教科書・参考書モード", "問題集・プリントモード"])
        use_web = st.checkbox("🌐 WEB検索を使用する")
        
        if st.form_submit_button("学習計画を作成 →"):
            if subj and level:
                ai_engine.set_model(model)
                ai_engine.set_embedding_model(embedding_model)
                with st.spinner("Gemini가学習計画を作成中..."):
                    rag_instr = "資料の目次を完全に再現して。" if rag_type == "教科書・参考書モード" else "論理的に構築して。"
                    prompt = f"""分野:{subj}, レベル:{level}, 時間:{hours}. {rag_instr}
                    以下の構造のJSONでのみ出力してください: 
                    {{ "subject": "{subj}", "goal_level": "{level}", "total_hours": "{hours}", "plan": [ {{ "id": "1", "name": "章名", "sub_topics": [ {{"id": "1-1", "name": "節名", "estimated_minutes": 60}} ] }} ] }}"""

                    try:
                        raw = ai_engine.gemini_once_json(prompt, rag_store_name=store_opts[rag_disp], use_web_search=use_web)
                        plan = json.loads(raw)
                        plan.update({
                            "notes": notes, "rag_store_name": store_opts[rag_disp], 
                            "rag_type": rag_type, "explain_level": explain_level, 
                            "use_web_search": use_web, "gemini_model": model,
                            "embedding_model": embedding_model
                        })
                        st.session_state.pending_plan = plan
                        navigate_to("confirm_plan")
                    except Exception as e:
                        show_friendly_error(e)

    if st.button("← 戻る"): navigate_to("start")

def show_confirm_plan_screen():
    """3. 学習計画の確認画面 [手順3]"""
    plan = st.session_state.pending_plan
    if not plan: navigate_to("new_subject")
    
    st.title(f"📋 学習計画の確認: {plan.get('subject')}")
    st.write(f"目標レベル: {plan.get('goal_level')} | 時間: {plan.get('total_hours')}")
    
    display_data = []
    # TypeError対策: 各要素が辞書であることを確認しながらループ
    raw_plan = plan.get("plan", [])
    if isinstance(raw_plan, list):
        for top in raw_plan:
            if isinstance(top, dict):
                display_data.append({"ID": top.get("id", "-"), "分野名": top.get("name", "名称不明")})
                for sub in top.get("sub_topics", []):
                    if isinstance(sub, dict):
                        display_data.append({"ID": sub.get("id", "-"), "分野名": f"  {sub.get('name', '名称不明')}"})
    
    st.table(display_data)
    
    if st.button("✅ 確定して保存"):
        database.save_cfg(plan['subject'], plan)
        st.session_state.current_subject = plan['subject']
        navigate_to("menu")
    if st.button("← 戻る"): navigate_to("new_subject")

def show_anki_reclassify_screen():
    """🔄 AIで問題を再分類画面"""
    subj = st.session_state.current_subject
    cfg = st.session_state.cfg_data
    plan = cfg.get("plan", [])
    
    st.title(f"🔄 AIで問題を再分類 : {subj}")
    st.info("キーワードマッチングより精度の高いAI分類で全問題を再振り分けします。")
    
    batch_size = st.number_input("1回あたりの処理件数", min_value=1, max_value=100, value=20)
    st.caption("※ 多いほど速いですが API の負荷が上がります。")

    log_area = st.empty()
    log_text = []
    
    def progress_cb(msg):
        log_text.append(msg)
        log_area.code("\n".join(log_text[-10:]), language="text")

    st.subheader("🤖 学習計画の再構成")
    st.write("全ての画像要約データを基に、学習計画（章立て）をゼロから再構築します。")
    confirm_reorg = st.checkbox("既存の分類が破棄されることを理解し、再構成を実行する")
    
    if st.button("🚀 AIで章立てから再構成する", width="stretch", disabled=not confirm_reorg):
        with st.spinner("シラバスを再構成中..."):
            try:
                from anki_importer import reorganize_syllabus_from_summaries
                res = reorganize_syllabus_from_summaries(subj, progress_cb=progress_cb)
                if res["success"]:
                    st.success("完了しました！メニューに戻ります。")
                    time.sleep(2)
                    navigate_to("menu")
                else:
                    st.error(res["message"])
            except Exception as e:
                show_friendly_error(e)

    st.divider()
    st.subheader("🔄 既存の章への再分類")
    st.write("現在の章立てを維持したまま、未分類の問題をAIで適切な章に振り分けます。")
    if st.button("🔄 AI再分類を実行", width="stretch"):
        with st.spinner("再分類を実行中..."):
            try:
                from anki_importer import batch_classify_with_ai
                batch_classify_with_ai(subject=subj, plan=plan, batch_size=batch_size, delay_sec=2.0, progress_cb=progress_cb)
                st.success("AIによる再分類が完了しました。")
            except Exception as e:
                show_friendly_error(e)

    st.divider()
    if st.button("← 学習メニューへ戻る", width="stretch"):
        navigate_to("menu")


def show_menu_screen():
    """4. 学習メニュー画面 [手順4] - 機能維持+色分け+オートフォーカス+KeyError修正版"""
    subj = st.session_state.current_subject
    cfg = database.load_cfg(subj)
    st.session_state.cfg_data = cfg
    st.title(f"📚 {subj} - 学習メニュー")

    # --- ヘッダー・設定情報 ---
    st.caption(f"目標レベル: {cfg.get('goal_level','')} ／ 目標時間: {cfg.get('total_hours','')} ／ 説明レベル: {cfg.get('explain_level','')}")
    
    info_col, btn_col = st.columns([3, 1])
    with info_col:
        web_status = "🟢 ON" if cfg.get("use_web_search") else "⚪ OFF"
        st.caption(f"🤖 Gemini: **{cfg.get('gemini_model', ai_engine.get_model())}** ｜ 🧠 Embedding: **{cfg.get('embedding_model', ai_engine.get_embedding_model())}** ｜ 🌐 WEB検索: **{web_status}**")
    with btn_col:
        if st.button("⚙️ 設定変更", width="stretch"):
            navigate_to("edit_settings")
            
    st.divider()
    st.subheader("📊 学習計画・進捗状況")
    
    # --- データ準備 ---
    FMT_ABBR = {
        "正誤問題": "正誤", "5肢択一問題": "択一", "穴埋め問題": "穴埋",
        "記述式問題": "記述", "論証問題": "論証",
        "理系用計算問題（途中式あり）": "計算", "理系用証明・導出問題": "証明",
    }
    prog = cfg.get("progress", {})
    topic_settings = cfg.get("topic_settings", {})
    topic_options = []       
    progress_table_data = [] 

    # 階層構造の解析
    for top in cfg.get("plan", []):
        if not isinstance(top, dict): continue
        subs = top.get("sub_topics", [])
        
        if subs:
            # 親カテゴリ（見出し）
            progress_table_data.append({"ID": str(top.get("id", "")), "分野名": f"【{top.get('name', '')}】", "進捗": "", "理解度": "", "tid_raw": ""})
            for st_obj in subs:
                tid = str(st_obj["id"])
                tname = st_obj["name"] # 変数に保持
                p = prog.get(tid, {})
                done_str = "✅ 完了" if p.get("done") else "・ 未学習"
                fmt = topic_settings.get(tid)
                stats = database.get_topic_mastery_stats(subj, tid, question_format=fmt)
                abbr = FMT_ABBR.get(fmt, "")
                score_str = f"{stats['correct']} / {stats['total']} [{abbr}]" if stats["total"] > 0 and abbr else f"{stats['correct']} / {stats['total']}" if stats["total"] > 0 else f"- / - [{abbr}]" if abbr else "- / -"
                
                progress_table_data.append({"ID": f"  {tid}", "分野名": f"  {tname} ({st_obj.get('estimated_minutes', 60)}分)", "進捗": done_str, "理解度": score_str, "tid_raw": tid})
                # 【修正箇所】name キーを追加
                topic_options.append({"id": tid, "name": tname, "display": f"{tid}: {tname}"})
        else:
            # 単一カテゴリ
            tid = str(top["id"])
            tname = top["name"] # 変数に保持
            p = prog.get(tid, {})
            done_str = "✅ 完了" if p.get("done") else "・ 未学習"
            fmt = topic_settings.get(tid)
            stats = database.get_topic_mastery_stats(subj, tid, question_format=fmt)
            abbr = FMT_ABBR.get(fmt, "")
            score_str = f"{stats['correct']} / {stats['total']} [{abbr}]" if stats["total"] > 0 and abbr else f"{stats['correct']} / {stats['total']}" if stats["total"] > 0 else f"- / - [{abbr}]" if abbr else "- / -"
            
            progress_table_data.append({"ID": tid, "分野名": f"{tname} ({top.get('estimated_minutes', 60)}分)", "進捗": done_str, "理解度": score_str, "tid_raw": tid})
            # 【修正箇所】name キーを追加
            topic_options.append({"id": tid, "name": tname, "display": f"{tid}: {tname}"})

    # --- ① 理解度の色分け ---
    df = pd.DataFrame(progress_table_data)
    def highlight_score(row):
        styles = [''] * len(row)
        tid = row['tid_raw']
        if tid and prog.get(tid, {}).get("done"):
            m = re.search(r"(\d+)\s*/\s*(\d+)", str(row['理解度']))
            if m:
                correct, total = int(m.group(1)), int(m.group(2))
                if total > 0:
                    rate = correct / total
                    if rate < 0.2: color = '#ffcccc'
                    elif rate < 0.4: color = '#ffe0cc'
                    elif rate < 0.6: color = '#ffffcc'
                    elif rate < 0.8: color = '#e0ffcc'
                    elif rate < 1.0: color = '#ccffcc'
                    else: color = '#cce5ff'
                    styles[3] = f'background-color: {color}; color: black;'
        return styles

    st.dataframe(
        df.style.apply(highlight_score, axis=1),
        height=350, width="stretch", hide_index=True,
        column_order=("ID", "分野名", "進捗", "理解度"),
        column_config={"分野名": st.column_config.TextColumn("分野名", width="large")}
    )

    # --- ② オートフォーカス ---
    default_idx = 0
    for i, opt in enumerate(topic_options):
        if not prog.get(opt["id"], {}).get("done", False):
            default_idx = i
            break

    sel_disp = st.selectbox("学習する分野", [o["display"] for o in topic_options], index=default_idx)
    
    # 出題形式の同期保存
    format_options = ["記述式問題", "正誤問題", "5肢択一問題", "穴埋め問題", "論証問題", "理系用計算問題（途中式あり）", "理系用証明・導出問題"]
    selected_tid = next((o["id"] for o in topic_options if o["display"] == sel_disp), None)
    current_fmt = topic_settings.get(selected_tid, "記述式問題")
    fmt_idx = format_options.index(current_fmt) if current_fmt in format_options else 0
    sel_fmt = st.selectbox("出題形式選択", format_options, index=fmt_idx)
    
    if current_fmt != sel_fmt and selected_tid:
        if "topic_settings" not in cfg: cfg["topic_settings"] = {}
        cfg["topic_settings"][selected_tid] = sel_fmt
        database.save_cfg(subj, cfg)
        st.rerun()

    # --- ボタン群 ---
    col1, col2, col3, col4, col5, col6, col7, col8 = st.columns(8)
    if col1.button("▶ 学習開始", width="stretch"):
        # セレクトボックスで選ばれている分野オブジェクトを取得
        st.session_state.current_topic = next(o for o in topic_options if o["display"] == sel_disp)
        st.session_state.chat_history = []
        navigate_to("lesson")
    if col2.button("📊 状況＋論評"): 
        st.session_state.stats_with_ai = True
        navigate_to("stats")
    if col3.button("📈 状況（高速）"): 
        st.session_state.stats_with_ai = False
        navigate_to("stats")
    if col4.button("💬 自由質問"):
        st.session_state.chat_history = []
        navigate_to("free_chat")
    if col5.button("🃏 AnkiDec出力"):
        navigate_to("anki_export")
    
    if cfg.get("anki_imported"):
        if col6.button("🔄 AIで再分類"):
            navigate_to("anki_reclassify")
    else:
        col6.empty()
        
    if col7.button("🖼️ 図解一括取込"):
        navigate_to("image_batch_import")
    if col8.button("🏠 ホームへ"): 
        navigate_to("start")

def show_image_batch_import_screen():
    """🖼️ 図解の一括取込画面 (ファイル選択 & カメラ撮影対応版)"""
    subj = st.session_state.current_subject
    if not subj:
        navigate_to("start")
        return

    st.title(f"🖼️ 図解を一括取込 : {subj}")
    st.info("PC内の画像を選択、またはスマホのカメラで資料を直接撮影して、図解データベースに登録します。")

    uploaded_files = st.file_uploader(
        "📁 画像ファイルを選択 (複数可)",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="batch_img_uploader"
    )

    all_to_import = uploaded_files if uploaded_files else []
    col1, col2 = st.columns(2)
    is_ready = len(all_to_import) > 0
    
    if col1.button("🚀 取込と解析を開始", width="stretch", disabled=not is_ready):
        media_dir = database.get_media_dir(subj)
        success_count = 0
        skipped_count = 0
        error_count = 0
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 既存の解析済みリストを取得
        existing_summaries = database.get_all_media_summaries(subj)

        for i, file_data in enumerate(all_to_import):
            try:
                original_name = getattr(file_data, "name", "camera_input.png")
                if original_name == "camera_input.png":
                    timestamp = datetime.datetime.now().strftime("%H%M%S_%f")
                    fname = f"camera_{timestamp}.png"
                else:
                    fname = original_name
                
                dest_path = os.path.join(media_dir, fname)
                
                # 既に解析済みのファイルはスキップ（中断からの再開対応）
                # ※ summary が空文字の場合は未完了とみなして再解析する
                if fname in existing_summaries and existing_summaries[fname].strip():
                    if not os.path.exists(dest_path):
                        with open(dest_path, "wb") as f:
                            f.write(file_data.getbuffer())
                    skipped_count += 1
                    continue
                
                status_text.text(f"⏳ 処理中 ({i+1}/{len(all_to_import)}): {fname}")
                
                # バイナリデータとして保存
                with open(dest_path, "wb") as f:
                    f.write(file_data.getbuffer())
                
                # AIによる画像解析（ai_engine側の内部リトライを利用）
                summary = ai_engine.analyze_image_for_summary(dest_path)

                if summary:
                    # RAG検索用のベクトルを生成して保存
                    emb = ai_engine.get_embedding(summary)
                    database.save_media_summary(subj, fname, summary, embedding=emb)
                    existing_summaries[fname] = summary
                    success_count += 1
                    # APIへの連続負荷を避けるため短い待機
                    time.sleep(1)
                else:
                    st.warning(f"「{fname}」の処理中にAPI制限に達したため、安全に中断しました。\n時間を置いて再度実行すると続きから再開できます。")
                    break # ループを抜けて中断

            except Exception as e:
                st.error(f"❌ エラー ({original_name}): {e}")
                error_count += 1
            
            progress_bar.progress((i + 1) / len(all_to_import))

        status_text.empty()
        
        # 結果の通知
        if success_count > 0 or skipped_count > 0:
            msg = ""
            if success_count > 0: msg += f"✅ {success_count} 枚の画像を取り込みました。"
            if skipped_count > 0: msg += f"（既存の {skipped_count} 枚はスキップ）"
            st.success(msg)
            if success_count > 0:
                st.toast(f"{success_count}枚の画像を取り込みました", icon="🖼️")
            time.sleep(1.5)
            st.rerun()
            
        if error_count > 0:
            st.warning(f"⚠️ {error_count} 枚の処理に失敗しました。詳細は上記エラーを確認してください。")

    if col2.button("← 学習メニューへ戻る", width="stretch"):
        navigate_to("menu")




def show_edit_settings_screen():
    """設定変更画面"""
    subj = st.session_state.current_subject
    cfg = st.session_state.cfg_data
    
    st.title(f"⚙️ 設定の変更：{subj}")

    # === 追加：エンベディングモデル変更時の確認画面 ===
    if st.session_state.get("show_emb_confirm"):
        st.warning("⚠️ エンベディングモデルの変更を検出しました。")
        st.error("モデルを変更すると、既存の画像ベクトル（検索用データ）との互換性がなくなり、RAG検索が正しく機能しなくなります。")
        st.info("検索を復旧させるには、全ての画像を削除して取り込み直す（再解析する）必要があります。")

        c1, c2 = st.columns(2)
        if c1.button("✅ 了解して強制保存", width="stretch"):
            pending = st.session_state.get("pending_cfg")
            if pending:
                ai_engine.set_model(pending["gemini_model"])
                ai_engine.set_embedding_model(pending["embedding_model"])
                database.save_cfg(subj, pending)
                st.session_state.cfg_data = pending
                st.session_state.show_emb_confirm = False
                st.session_state.pending_cfg = None
                st.toast("設定を強制保存しました。")
                navigate_to("menu")
        
        if c2.button("キャンセル", width="stretch"):
            st.session_state.show_emb_confirm = False
            st.session_state.pending_cfg = None
            st.rerun()
        return
    
    with st.form("edit_settings_form"):
        goal_level = st.text_input("目標到達レベル", value=cfg.get("goal_level", ""))
        # 目標時間はTkinter版と同様に読み取り専用(disabled=True)にする
        total_hours = st.text_input("目標到達までの時間", value=cfg.get("total_hours", ""), disabled=True)
        explain_level = st.text_input("説明のレベル", value=cfg.get("explain_level", ""))
        gemini_model = st.text_input("Geminiモデルコード", value=cfg.get("gemini_model", ai_engine.get_model()))
        # エンベディングモデルの設定を追加
        embedding_model = st.text_input("Embeddingモデルコード", value=cfg.get("embedding_model", ai_engine.get_embedding_model()))
        notes = st.text_area("留意事項", value=cfg.get("notes", ""))
        
        stores = ai_engine.get_file_search_stores()
        store_opts = {"使用しない": None}
        for s in stores: store_opts[s["display"]] = s["name"]
        
        # 現在のRAGストア名から表示名を取得して初期値にする
        current_store_name = cfg.get("rag_store_name")
        current_disp = "使用しない"
        for disp, name in store_opts.items():
            if name == current_store_name:
                current_disp = disp
                break
                
        disp_opts = list(store_opts.keys())
        rag_disp_idx = disp_opts.index(current_disp) if current_disp in disp_opts else 0
        rag_disp = st.selectbox("参考資料 (RAG / コーパス)", disp_opts, index=rag_disp_idx)
        
        rag_types = ["教科書・参考書モード", "問題集・プリントモード"]
        current_rag_type = "教科書・参考書モード" if cfg.get("rag_type", "systematic") == "systematic" else "問題集・プリントモード"
        rag_type_idx = rag_types.index(current_rag_type)
        rag_type = st.radio("RAG資料の性質", rag_types, index=rag_type_idx)
        
        use_web_search = st.checkbox("🌐 最新WEB情報を検索反映", value=cfg.get("use_web_search", False))
        
        if st.form_submit_button("✅ 保存", width="stretch"):
            # モデル変更のチェック
            old_emb = cfg.get("embedding_model", "models/gemini-embedding-001")
            
            # 既存のcfg辞書を複製して更新
            new_cfg = dict(cfg)
            new_cfg.update({
                "goal_level": goal_level,
                "explain_level": explain_level,
                "gemini_model": gemini_model,
                "embedding_model": embedding_model,
                "notes": notes,
                "rag_store_name": store_opts[rag_disp],
                "rag_type": "systematic" if rag_type == "教科書・参考書モード" else "fragmented",
                "use_web_search": use_web_search
            })

            if embedding_model != old_emb:
                st.session_state.show_emb_confirm = True
                st.session_state.pending_cfg = new_cfg
                st.rerun()
            else:
                ai_engine.set_model(gemini_model)
                ai_engine.set_embedding_model(embedding_model)
                database.save_cfg(subj, new_cfg)
                st.session_state.cfg_data = new_cfg
                st.toast("設定を保存しました。")
                navigate_to("menu")

    if st.button("キャンセル", width="stretch"):
        navigate_to("menu")


def show_lesson_screen():
    """5. 説明画面 [手順5]"""
    import subprocess
    subj = st.session_state.current_subject
    topic = st.session_state.current_topic
    cfg = st.session_state.cfg_data

    # --- 1. 画面最上部へのアンカー設置 ---
    st.markdown('<div id="top" style="margin-top:-100px;"></div>', unsafe_allow_html=True)
    st.markdown("[▼ ページラストへ](#bottom)")
    
    st.title(f"📖 {topic['name']}")
    
    sys_prompt = f"""あなたは親切で分かりやすいプロ家庭教師の「AiTu」です。
科目「{subj}」の「{topic['name']}」について、レベル「{cfg.get('explain_level')}」で説明してください。
【指示】
1. 冒頭で必ず「AiTuです。」と名乗ること。
2. 【画像出力の絶対ルール（厳守）】
(1)あなたは、この科目のために用意された画像リスト（下記）を持っています。説明の各セクションを作成する前に、必ず画像リストの内容を確認してください。
(2)説明内容と合致する画像がある場合は、必ず `<img src="ファイル名">` を単独の行（前後に改行を入れる）で挿入してください。
(3)**[※資料...] や (画像:...) のようなテキスト形式での引用はシステムが読み取れないため「絶対に禁止」です。** 
   これを無視するとユーザーには画像が表示されません。
(4)画像があるのにテキストだけで説明することは「不親切」とみなされます。積極的に画像を提示してください。
(5)リストにない架空のファイル名は絶対に使用しないでください。
(6)適切な画像が存在しない場合に限り、Plotlyライブラリを用いたPythonコード（```python 〜 ```）を出力してください（matplotlib不可）。
3. 提供資料(RAG)があれば「[※資料より]」と明記して引用すること。
{get_full_media_block(subj, query=topic['name'])}
【留意事項】{cfg.get('notes', '')}"""

    if not st.session_state.chat_history:
        cached = database.load_explane(subj, topic["id"])
        if cached:
            st.session_state.chat_history = [{"role": "assistant", "content": cached}]
        else:
            with st.spinner("AiTuが説明を生成中..."):
                try:
                    reply = ai_engine.gemini_chat(sys_prompt, [], f"「{topic['name']}」の内容を説明してください。", rag_store_name=cfg.get("rag_store_name"), use_web_search=cfg.get("use_web_search"))
                    database.save_explane(subj, topic["id"], reply)
                    st.session_state.chat_history = [{"role": "assistant", "content": reply}]
                except Exception as e:
                    show_friendly_error(e)

    # --- ▼ 2. チャット履歴の表示（説明本体・質問回答） ---
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                render_ai_response(msg["content"])
            else:
                st.markdown(msg["content"])

    # --- ▼ 4. 質問入力セクション ---
    with st.container(border=True):
        uploaded_files = st.file_uploader("📁 ファイルを添付（スマホはカメラOK）", accept_multiple_files=True, key="lesson_files")
        
        if "lesson_p_to_process" not in st.session_state:
            st.session_state.lesson_p_to_process = None

        def handle_lesson_submit():
            if st.session_state.lesson_input_widget.strip() or (st.session_state.lesson_files and len(st.session_state.lesson_files) > 0):
                st.session_state.lesson_p_to_process = st.session_state.lesson_input_widget
                st.session_state.lesson_input_widget = ""

        p_input = st.text_area("質問を入力してください", placeholder=f"「{topic['name']}」について何でも聞いてください", key="lesson_input_widget", height=100)
        st.button("🚀 質問を送信", width="stretch", type="primary", on_click=handle_lesson_submit)

    # 送信処理
    if st.session_state.lesson_p_to_process is not None:
        p = st.session_state.lesson_p_to_process
        st.session_state.lesson_p_to_process = None
        
        combined_files = uploaded_files if uploaded_files else []
        user_content = p if not combined_files else f"【添付画像あり】\n{p}"
        st.session_state.chat_history.append({"role": "user", "content": user_content})

        with st.chat_message("user"): st.markdown(p)
        with st.chat_message("assistant"):
            with st.spinner("考え中..."):
                try:
                    file_paths = []
                    for f in combined_files:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{f.name}") as tmp:
                            tmp.write(f.getvalue())
                            file_paths.append(tmp.name)

                    history = [{"role": "user" if m["role"]=="user" else "model", "parts": [m["content"]]} for m in st.session_state.chat_history[:-1]]

                    if file_paths:
                        reply = ai_engine.gemini_chat_multimodal(sys_prompt, history, p, file_paths)
                    else:
                        reply = ai_engine.gemini_chat(sys_prompt, history, p, rag_store_name=cfg.get("rag_store_name"), use_web_search=cfg.get("use_web_search"))

                    render_ai_response(reply)
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    
                    for fp in file_paths:
                        try: os.remove(fp)
                        except: pass
                except Exception as e:
                    show_friendly_error(e)
        st.rerun()

    # --- 1. 画面最下部へのアンカー設置 ---
    st.markdown('<div id="bottom"></div>', unsafe_allow_html=True)
    st.markdown("[▲ ページトップへ](#top)")

    # --- ▼ 5. フッターナビゲーション（ボタン拡張） ---
    st.divider()
    col1, col2, col3, col4 = st.columns(4)
    if col1.button("← メニューへ", width="stretch"):
        navigate_to("menu")

    # 表示順序管理用
    if "lesson_ui_stack" not in st.session_state:
        st.session_state.lesson_ui_stack = []

    def update_ui_stack(key):
        if key in st.session_state.lesson_ui_stack:
            st.session_state.lesson_ui_stack.remove(key)
        st.session_state.lesson_ui_stack.insert(0, key)

    if col2.button("🔄 説明再作成", width="stretch"):
        st.session_state.show_regen = True
        update_ui_stack("regen")
        st.rerun()
    if col3.button("🎙️ 音声解説", width="stretch"):
        st.session_state.generate_audio = True
        update_ui_stack("audio")
        st.rerun()
    if col4.button("📝 テスト開始 →", width="stretch"):
        navigate_to("test")

    # --- ▼ 6. 動的UIエリア（フッターの下に表示） ---
    for ui_key in st.session_state.lesson_ui_stack:
        # --- 説明再作成 UI ---
        if ui_key == "regen" and st.session_state.get("show_regen", False):
            st.divider()
            st.warning("⚠️ 新しい説明で上書き保存されます。どのように修正して再作成してほしいか、要望を入力してください。")
            regen_req = st.text_area("追加の要望・修正指示（空欄のまま再作成も可）", key="regen_req_input")
            r_col1, r_col2 = st.columns(2)
            
            if r_col1.button("✅ 再作成を実行", width="stretch"):
                with st.spinner("AiTuが説明を再作成中..."):
                    try:
                        prev_text = next((h["content"] for h in reversed(st.session_state.chat_history) if h["role"] == "assistant"), "")
                        user_msg = f"「{topic['name']}」の内容を説明してください。"
                        if prev_text: user_msg += f"\n\n【前回の説明文（参考）】\n{prev_text}"
                        if regen_req: user_msg += f"\n\n【追加の要望・修正指示】\n上記の「前回の説明文」をベースにして、以下の指示に従って再作成してください：\n{regen_req}"

                        reply = ai_engine.gemini_chat(sys_prompt, [], user_msg, rag_store_name=cfg.get("rag_store_name"), use_web_search=cfg.get("use_web_search"))
                        
                        # 古い音声ファイル群のクリーンアップ
                        media_dir = database.get_media_dir(subj)
                        for fname in os.listdir(media_dir):
                            if fname.startswith(f"podcast_{topic['id']}"):
                                try: os.remove(os.path.join(media_dir, fname))
                                except: pass
                                
                        database.save_explane(subj, topic["id"], reply)
                        st.session_state.chat_history = [{"role": "assistant", "content": reply}]
                        st.session_state.show_regen = False
                        st.session_state.lesson_ui_stack.remove("regen")
                        st.rerun()
                    except Exception as e:
                        show_friendly_error(e)
                        
            if r_col2.button("キャンセル", width="stretch", key="btn_cancel_regen"):
                st.session_state.show_regen = False
                st.session_state.lesson_ui_stack.remove("regen")
                st.rerun()

        # --- 音声解説 UI ---
        elif ui_key == "audio" and st.session_state.get("generate_audio", False):
            st.divider()
            st.subheader("🎙️ 音声解説 (対話形式)")
            media_dir = database.get_media_dir(subj)
            topic_id = topic['id']
            json_path = os.path.join(media_dir, f"podcast_script_{topic_id}.json")
            
            script_data = None
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        script_data = json.load(f)
                except: pass
                
            if not script_data:
                texts = [h["content"] for h in st.session_state.chat_history if h["role"] == "assistant"]
                if not texts:
                    st.warning("先に説明を生成してください。")
                else:
                    with st.spinner("🎙️ AI台本を作成中..."):
                        try:
                            prompt = f"""あなたはプロの構成作家です。
                    以下の学習内容を元に、2人のキャラクター（専門家の「先生」と、好奇心旺盛な「生徒」）による、楽しくて分かりやすい対話形式のポッドキャスト用スクリプトを作成してください。

                    【ルール】
                    - 自然な口語体（話し言葉）で進行すること。
                    - 専門用語は生徒が質問し、先生が噛み砕いて説明する流れにすること。
                    - 出力は必ず以下のJSON構造のみとしてください（他テキスト不要）。

                    【出力形式】
                    [
                    {{"speaker": "生徒", "text": "ねえ先生、〇〇について教えて！"}},
                    {{"speaker": "先生", "text": "いいよ。〇〇というのはね..."}}
                    ]

                    【解説内容】
                    {texts[0]}"""
                            raw_json = ai_engine.gemini_once_json(prompt)

                            raw_json_ext = ai_engine._extract_json(raw_json)
                            script_data = json.loads(raw_json_ext)
                            
                            if isinstance(script_data, list):
                                with open(json_path, "w", encoding="utf-8") as f:
                                    json.dump(script_data, f, ensure_ascii=False)
                            else:
                                st.error("台本のフォーマットが正しくありません。")
                                script_data = None
                        except Exception as e:
                            show_friendly_error(e)
            
            if script_data and isinstance(script_data, list):
                playlist = []
                for i, line in enumerate(script_data):
                    text = line.get("text", "").strip()
                    if not text: continue
                    speaker = line.get("speaker", "先生")
                    voice = "ja-JP-KeitaNeural" if "先生" in speaker else "ja-JP-NanamiNeural"
                    mp3_name = f"podcast_{topic_id}_{i}.mp3"
                    mp3_path = os.path.join(media_dir, mp3_name)
                    
                    if not os.path.exists(mp3_path):
                        with st.spinner(f"音声合成中 ({i+1}/{len(script_data)})..."):
                            try:
                                extra_flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
                                subprocess.run(["edge-tts", "--voice", voice, "--text", text, "--write-media", mp3_path], check=True, **extra_flags)
                            except Exception as e:
                                st.error(f"音声の生成に失敗しました: {e}")
                    
                    # テキスト表示
                    st.markdown(f"**{'👨‍🏫' if '先生' in speaker else '👩‍🎓'} {speaker}**: {text}")
                    
                    # プレイリストに追加（Base64化）
                    if os.path.exists(mp3_path):
                        try:
                            with open(mp3_path, "rb") as f:
                                b64 = base64.b64encode(f.read()).decode()
                                playlist.append({
                                    "speaker": speaker,
                                    "text": text,
                                    "b64": f"data:audio/mp3;base64,{b64}"
                                })
                        except: pass

                if playlist:
                    st.write("---")
                    player_html = f"""
                    <div style="background: #f8f9fb; padding: 15px; border-radius: 12px; border: 1px solid #dee2e6; margin: 10px 0; font-family: sans-serif;">
                        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
                            <span style="font-weight: bold; color: #1e90ff;">🎙️ ポッドキャスト連続再生</span>
                            <span id="audio-info" style="font-size: 0.8rem; color: #6c757d;">準備完了</span>
                        </div>
                        <audio id="main-player" controls style="width: 100%; height: 45px;"></audio>
                        <div id="now-playing" style="font-size: 0.85rem; margin-top: 10px; color: #495057; border-left: 3px solid #1e90ff; padding-left: 8px; min-height: 1.2em; line-height: 1.4;"></div>
                        <div style="margin-top: 12px; display: flex; gap: 8px;">
                            <button onclick="playPrev()" style="flex: 1; padding: 6px; cursor: pointer; border: 1px solid #ccc; border-radius: 6px; background: #fff; font-size: 0.8rem;">⏮ 前へ</button>
                            <button onclick="playNext()" style="flex: 1; padding: 6px; cursor: pointer; border: 1px solid #ccc; border-radius: 6px; background: #fff; font-size: 0.8rem;">次へ ⏭</button>
                        </div>
                    </div>

                    <script>
                    const playlist = {json.dumps(playlist)};
                    const player = document.getElementById('main-player');
                    const info = document.getElementById('audio-info');
                    const nowPlaying = document.getElementById('now-playing');
                    let currentIdx = 0;

                    function loadTrack(idx) {{
                        if (idx < 0 || idx >= playlist.length) return;
                        currentIdx = idx;
                        player.src = playlist[idx].b64;
                        const icon = playlist[idx].speaker.includes("先生") ? "👨‍🏫" : "👩‍🎓";
                        nowPlaying.innerText = icon + " " + playlist[idx].speaker + ": " + playlist[idx].text;
                        info.innerText = "再生中: " + (idx + 1) + " / " + playlist.length;
                    }}

                    function playNext() {{
                        if (currentIdx + 1 < playlist.length) {{
                            loadTrack(currentIdx + 1);
                            player.play();
                        }} else {{
                            info.innerText = "再生完了";
                            nowPlaying.innerText = "✨ 最後まで聴き終わりました！";
                        }}
                    }}
                    
                    function playPrev() {{
                        if (currentIdx - 1 >= 0) {{
                            loadTrack(currentIdx - 1);
                            player.play();
                        }}
                    }}

                    player.onended = playNext;
                    loadTrack(0);
                    </script>
                    """
                    st.components.v1.html(player_html, height=185)
                            
            if st.button("❌ 音声解説を閉じる", width="stretch"):
                st.session_state.generate_audio = False
                st.session_state.lesson_ui_stack.remove("audio")
                st.rerun()

def show_test_screen():
    """6. テスト画面 [手順6]"""
    # --- 1. 画面最上部へのアンカー設置 ---
    st.markdown('<div id="top" style="margin-top:-100px;"></div>', unsafe_allow_html=True)
    st.markdown("[▼ ページラストへ](#bottom)")
    
    st.title("📝 確認テスト")
    subj = st.session_state.current_subject
    topic = st.session_state.current_topic
    cfg = st.session_state.cfg_data

    # --- クラウド版準拠：復習テスト時の上部統計表示 ---
    if topic["id"] == "review" and st.session_state.test_qs:
        total_q_db = database.count_all_questions(subj)
        today_q_count = len(st.session_state.test_qs)
        st.markdown(f"""
            <div style="background-color: #eef4fb; padding: 12px; border-radius: 8px; border: 1px solid #d0e0f0; margin-bottom: 20px;">
                <span style="font-size: 0.9rem; color: #555;">蓄積問題数（全体）: <b>{total_q_db}問</b> ｜ 今回の復習対象: <b>{today_q_count}問</b></span><br>
                <span style="font-size: 0.8rem; color: #777;">※忘却曲線に基づいて出題されます。全問回答しなくても「採点」に進めます。</span>
            </div>
        """, unsafe_allow_html=True)
    
    if not st.session_state.test_qs:
        with st.spinner("Geminiが問題を生成中..."):
            try:
                fmt = cfg.get("topic_settings", {}).get(topic["id"], "記述式問題")
                qs, _ = ai_engine.build_test_set(subj, topic["id"], subj, topic["name"], rag_store_name=cfg.get("rag_store_name"), question_format=fmt, use_web_search=cfg.get("use_web_search"))
                st.session_state.test_qs = qs
            except Exception as e:
                show_friendly_error(e)
                if st.button("メニューに戻る"): navigate_to("menu")
                return

    if st.session_state.test_qs:
        # 1. 問題の表示と入力の受付
        for q in st.session_state.test_qs:
            # --- クラウド版準拠：復習テスト用のバッジ・背景色判定とUI分岐 ---
            if topic["id"] == "review":
                score = q.get("review_score", 0)
                if score >= 999:
                    badge, bg_color = "🆕 未出題", "#d4edda" # 緑系
                else:
                    badge, bg_color = "⚠️ 要復習", "#fff3cd" # 黄系
                
                # 背景色付きのヘッダーを表示
                st.markdown(f"""
                    <div style="background-color: {bg_color}; padding: 8px 15px; border-radius: 8px 8px 0 0; border: 1px solid #ccc; border-bottom: none; margin-top: 15px;">
                        <b style="color: #333;">問 {q['q']}　{badge}</b> 
                        <span style="font-size: 0.85rem; margin-left: 15px; color: #555;">
                            [正解率: {q.get('correct_rate', 0)*100:.0f}% ｜ 出題: {q.get('asked_count', 0)}回]
                        </span>
                    </div>
                """, unsafe_allow_html=True)
                
                # 問題本文を枠で囲む
                with st.container(border=True):
                    render_ai_response(q["question"])
                    st.checkbox("🗑️ この小問を削除（採点時に実行）", key=f"del_{q['q']}")
            else:
                # 通常テスト時はシンプルに表示
                st.subheader(f"問 {q['q']}")
                render_ai_response(q["question"])

            # --- 以下、入力UI部分は既存機能の完全維持 ---
            q_fmt = q.get("format", "記述式問題")

            if q_fmt == "正誤問題":
                st.radio("回答を選択", ["○ (正しい)", "× (誤り)", "未回答"], index=2, horizontal=True, key=f"ans_{q['q']}")
            elif q_fmt == "5肢択一問題":
                st.radio("回答を選択", ["1", "2", "3", "4", "5", "未回答"], index=5, horizontal=True, key=f"ans_{q['q']}")
            else:
                st.text_area("回答を入力", key=f"ans_{q['q']}")

            st.file_uploader("📁 ファイルを添付（スマホはカメラOK）", key=f"file_{q['q']}")
            
        # 2. 提出ボタン (既存ロジックをそのまま維持)
        st.markdown('<div id="bottom"></div>', unsafe_allow_html=True)
        st.markdown("[▲ ページトップへ](#top)")
        if st.button("✅ 回答提出", width="stretch"):
            final_answers = []
            has_images = False
            deleted_count = 0
            
            for q in st.session_state.test_qs:
                # 削除フラグが立っている問題の処理
                is_deleted = False
                if topic["id"] == "review" and st.session_state.get(f"del_{q['q']}", False):
                    database.delete_question(subj, q["pool_id"])
                    is_deleted = True
                    deleted_count += 1
                    
                if is_deleted:
                    continue # 削除された問題は採点に回さない

                # 「未回答」を空文字列として処理
                raw_ans = st.session_state.get(f"ans_{q['q']}", "")
                if raw_ans == "未回答":
                    ans_text = ""
                else:
                    ans_text = raw_ans.strip()
                
                uploaded_file = st.session_state.get(f"file_{q['q']}")
                
                img_paths = []
                if uploaded_file is not None:
                    has_images = True
                    with tempfile.NamedTemporaryFile(delete=False, suffix="_" + uploaded_file.name) as tmp:
                        tmp.write(uploaded_file.getvalue())
                        img_paths.append(tmp.name)

                # 復習テストで未回答のものはスキップ
                if topic["id"] == "review" and not ans_text and not img_paths:
                    continue

                # テキストが空で画像がある場合、AIへの指示を補完する
                u_ans_for_ai = ans_text if ans_text else ("（テキスト回答なし。添付画像を確認して採点してください）" if img_paths else "（未回答）")

                final_answers.append({
                    "q": q['q'],
                    "original_q_data": q,
                    "user_answer": ans_text,
                    "user_answer_for_ai": u_ans_for_ai,
                    "img_path": img_paths
                })

            if deleted_count > 0:
                msg = f"✅ チェックされた {deleted_count} 問の小問をデータベースから削除しました。"
                st.success(msg)
                st.toast(msg, icon="🗑️")
                time.sleep(1)

            # 復習テストで1問も回答がなかった場合、メニューへ戻る
            if topic["id"] == "review" and len(final_answers) == 0:
                st.warning("回答が1問もなかったため、復習テストをスキップして学習メニューに進みました。")
                st.session_state.test_qs = None
                navigate_to("menu")
                return

            st.session_state.user_ans = final_answers
            st.session_state.test_qs = [ans["original_q_data"] for ans in final_answers]

            with st.spinner("AiTuが採点中..."):
                try:
                    if topic["id"] == "review":
                        lesson_text = ""
                        for q in st.session_state.test_qs:
                            tid = q.get("topic_id")
                            if tid:
                                lt = database.load_explane(subj, tid)
                                if lt and lt not in lesson_text:
                                    lesson_text += f"\n[分野ID: {tid} の説明]\n{lt}\n"
                        q_format = "各問題ごとの出題形式"
                    else:
                        lesson_text = database.load_explane(subj, topic["id"]) or ""
                        q_format = cfg.get("topic_settings", {}).get(topic["id"], "記述式問題")

                    notes_block = f"\n\n【ユーザー指定の留意事項】\n{cfg.get('notes', '')}" if cfg.get("notes") else ""
                    if cfg.get("use_web_search"):
                        notes_block += "\n【重要：WEB検索の実行】あなたはGoogle検索機能を利用可能です。上記の「留意事項」に法改正や最新情報の確認指示がある場合は、必ず検索を実行して最新の情報を取得した上で採点・解説を行ってください。"
                    
                    lesson_scope_block = f"\n【絶対の採点基準】\n以下の「説明本文」の内容を正解の絶対基準とします。\n説明本文と矛盾する解説は行わないでください。\n--- 説明本文 ---\n{lesson_text}\n--- ここまで ---\n" if lesson_text else ""

                    explain_level = cfg.get("explain_level", "中学生でも理解できるレベル")
                    test_len = len(st.session_state.test_qs)

                    # クラウド版準拠：復習時は科目名、通常時はトピック名で資料(RAG画像)を探す
                    query_for_rag = topic['name'] if topic['id'] != "review" else subj
                    grade_prompt = f"あなたは採点担当の家庭教師です。科目「{subj}」の「{topic['name']}」のテスト（{test_len}問）を採点し、解説してください。\n【出題形式】この問題は「{q_format}」形式で出題されています。採点基準をその形式に合わせてください。{notes_block}\n{lesson_scope_block}\n{get_full_media_block(subj, query_for_rag)}\n--- 採点対象 ---"
                    contents = [grade_prompt]
                    
                    for i, q in enumerate(st.session_state.test_qs):
                        u_ans_data = final_answers[i]
                        
                        # 復習・通常問わず、DBの形式データを直接AIに伝える
                        q_fmt = q.get("format", "記述式問題")
                        contents.append(f"問{i+1}【出題形式：{q_fmt}】: {q['question']}\n模範解答: {q['answer']}\nユーザー回答（テキスト）: {u_ans_data['user_answer_for_ai']}")
                       
                        for img_p in u_ans_data["img_path"]:
                            try:
                                contents.extend([f"問{i+1} の手書き・添付ファイル：", *ai_engine.file_to_parts(img_p)])
                            except Exception as img_e:
                                contents.append(f"（ファイル読み込みエラー: {img_e}）")
                    
                    contents.append(f"""\n--- ここまで ---\n【解説方針】{explain_level} に合わせた言葉遣いで解説。手書き画像がある場合はその内容（数式・図・文字）を読み取って正誤を判定。\n【図表出力ルール】解説に図解が必要な際、提供された画像データに適切なものがあれば `<img src="ファイル名">` を優先して使用してください。該当画像がない場合に限り、Plotlyを用いたPythonコードを作成してください（matplotlib不可）。\n【重要：エスケープ】数式のバックスラッシュは2つ重ね、改行は通常の「\\n」。図表のPythonコードは必ずバッククォート3つで囲む。\n【矛盾判定ルール】テキスト回答と画像回答が矛盾する場合はその問いを採点不能とし、explanation にその旨を記載。\n\n【出力形式】以下のJSON構造のみを出力してください（Markdownなどは不要）。total_scoreは{test_len}問中の正解数（0〜{test_len}の整数）。\n{{ "total_score": 3, "results": [ {{"q": 1, "correct": true, "interpreted": "画像から読み取った内容（画像がない場合は空文字）", "explanation": "解説文"}} ], "overall_comment": "総評", "weakness": "弱点（なければ空文字）", "recommendation": "advance" }}""")

                    if has_images:
                        raw = ai_engine.gemini_once_json_multimodal(contents, use_web_search=cfg.get("use_web_search", False))
                    else:
                        raw = ai_engine.gemini_once_json("\n".join(c for c in contents if isinstance(c, str)), use_web_search=cfg.get("use_web_search", False))
                    
                    result = safe_json_parse(raw)
                    st.session_state.test_res = result
                    
                    # 1. 個別の問題結果を更新
                    for res in result.get("results", []):
                        q_idx = res.get("q", 1) - 1
                        if 0 <= q_idx < len(st.session_state.test_qs):
                            database.update_question_result(subj, st.session_state.test_qs[q_idx]["pool_id"], bool(res.get("correct")), res.get("explanation"))
                    
                    # 2. 【移植箇所】分野全体の進捗データ（doneフラグ等）を更新してDBへ保存
                    if "progress" not in cfg: cfg["progress"] = {}
                    if "weaknesses" not in cfg: cfg["weaknesses"] = {}
                    
                    tid = topic["id"]
                    # 満点を5点として、結果からスコアと評価を取得
                    score = min(test_len, max(0, int(result.get("total_score", 0))))
                    
                    # 進捗フラグをTrueにし、最終学習日を記録
                    cfg["progress"][tid] = {
                        "done": True, 
                        "score": score, 
                        "last_date": datetime.date.today().isoformat()
                    }
                    
                    # AIが判定した弱点があれば保存
                    if result.get("weakness"):
                        cfg["weaknesses"][tid] = {
                            "text": result["weakness"], 
                            "date": datetime.date.today().isoformat()
                        }
                    
                    # configテーブル（JSONデータ）を上書き保存
                    database.save_cfg(subj, cfg)
                    
                    # 3. 後処理と画面遷移
                    for ans in final_answers:
                        for img_p in ans["img_path"]:
                            try: os.remove(img_p)
                            except: pass
                    
                    st.session_state.result_chat_history = []
                    navigate_to("result")
                except Exception as e:
                    show_friendly_error(e)

def show_result_screen():
    """7. 採点結果画面 [手順7]"""
    # 状態クリア用のフラグがある場合は、ウィジェット描画前にクリアする
    if st.session_state.get("clear_result_chat"):
        st.session_state["result_chat_input_widget"] = ""
        st.session_state.clear_result_chat = False

    res = st.session_state.test_res
    if not res:
        st.warning("採点結果が見つかりません。")
        if st.button("メニューへ"): navigate_to("menu")
        return

    st.title(f"📊 採点結果: {res.get('total_score', 0)} / 5")
    st.info(res.get("overall_comment", ""))
    if res.get("weakness"): st.warning(f"弱点: {res['weakness']}")
    
    # --- ▼ AIのアドバイス表示を追加 ---
    recom = res.get("recommendation", "stay")
    if recom == "advance":
        st.success("🌟 **AiTuのアドバイス:** 素晴らしい！このまま次のステップへ進みましょう。")
    else:
        st.info("📚 **AiTuのアドバイス:** この分野を一度復習してから先に進むことをお勧めします。")
    # ----------------------------

    for r in res.get("results", []):
        q_idx = r.get("q", 1) - 1
        with st.expander(f"問{r.get('q')} {'✅ 正解' if r.get('correct') else '❌ 不正解'}"):
            if q_idx < len(st.session_state.test_qs):
                # 文字列へのキャスト(str)と、.get()を使ってエラーを完全に防ぐ
                st.markdown("**問題:**")
                render_ai_response(str(st.session_state.test_qs[q_idx].get('question', '')))
                
                # AIが画像から読み取ったテキストがあれば優先表示
                user_ans = st.session_state.user_ans[q_idx]['user_answer']
                interpreted = r.get("interpreted", "")
                if user_ans:
                    u_ans_disp = user_ans + (f" (画像: {interpreted})" if interpreted else "")
                else:
                    u_ans_disp = f"(画像) {interpreted}" if interpreted else ("（画像回答あり）" if st.session_state.user_ans[q_idx].get("img_path") else "（未回答）")

                st.write(f"**あなたの回答:** {u_ans_disp}")
                
                st.markdown("**正解:**")
                render_ai_response(str(st.session_state.test_qs[q_idx].get('answer', '')))
                
            # 解説にPlotlyコードが含まれる場合もリッチ表示
            st.markdown("**解説:**")
            render_ai_response(str(r.get("explanation", "")))

    # 解説チャット
    st.divider()
    st.subheader("💬 解説について質問する")

    # 履歴の表示
    for msg in st.session_state.result_chat_history:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                render_ai_response(msg["content"])
            else:
                st.markdown(msg["content"])

    res_file = st.file_uploader("📁 ファイルを添付", key="res_file")

    # クラウド版仕様：st.chat_input を st.text_area + button に変更
    p = st.text_area("解説で分からないことがあれば聞いてください", placeholder="ここを詳しく教えて！", key="result_chat_input_widget")

    if st.button("🚀 解説について質問を送信", width="stretch", type="primary"):
        if p.strip():
            st.session_state.result_chat_history.append({"role": "user", "content": p})
            with st.spinner("回答中..."):
                try:
                    # 送信データの準備
                    user_msg = f"テスト結果:{res} 質問:{p}"
                    file_paths = []
                    
                    if res_file is not None:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{res_file.name}") as tmp:
                            tmp.write(res_file.getvalue())
                            file_paths.append(tmp.name)
                    
                    # 履歴をAIが解釈できる形式に変換
                    history = [{"role": "user" if m["role"]=="user" else "model", "parts": [m["content"]]} for m in st.session_state.result_chat_history[:-1]]
                    
                    if file_paths:
                        rep = ai_engine.gemini_chat_multimodal("AiTuです。テストの解説についてお答えします。", history, user_msg, file_paths)
                    else:
                        rep = ai_engine.gemini_chat("AiTuです。テストの解説についてお答えします。", history, user_msg)
                    
                    st.session_state.result_chat_history.append({"role": "assistant", "content": rep})
                    st.session_state.clear_result_chat = True
                    
                    # 一時ファイルの削除
                    for fp in file_paths:
                        try: os.remove(fp)
                        except: pass
                    st.rerun()
                except Exception as e:
                    show_friendly_error(e)

    st.divider()
    if st.button("🏠 学習メニューへ戻る", width="stretch"):
        st.session_state.result_chat_history = []
        st.session_state.test_qs = None
        st.session_state.test_res = None
        st.session_state.user_ans = None
        navigate_to("menu")

def show_select_subject_screen():
    """8. 既存分野を選択画面 [手順8: 復習テスト自動判別]"""
    st.title("📂 学習する科目を選択")
    subs = database.list_subjects()
    selected = st.selectbox("科目一覧", subs)
    
    if st.button("▶ 学習開始", width="stretch"):
        # 1. 選択された科目をセッションに保存
        st.session_state.current_subject = selected
        
        # 2. ここで設定データ(cfg_data)をロードして保存する
        cfg = database.load_cfg(selected)
        st.session_state.cfg_data = cfg
        
        # 3. AIエンジンにモデル設定を反映
        ai_engine.set_model(cfg.get("gemini_model", ai_engine.get_model()))
        ai_engine.set_embedding_model(cfg.get("embedding_model", ai_engine.get_embedding_model()))
        
        # 4. 復習問題があるかチェック
        qs = database.get_review_questions(selected)
        if qs:
            st.info("忘却曲線に基づき、本日復習すべき問題があります。復習テストから開始します。")
            # tkinter版に合わせ、最大100問を取得しメタデータをすべて含める
            st.session_state.test_qs = [
                {
                    "q": i+1, 
                    "question": q["question"], 
                    "answer": q["answer"],
                    "pool_id": q["id"], 
                    "topic_id": q.get("topic_id", ""), 
                    "format": q.get("format", "記述式問題"),
                    "review_score": q.get("review_score", 0),
                    "correct_rate": q.get("correct_rate", 0),
                    "asked_count": q.get("asked_count", 0)
                } 
                for i, q in enumerate(qs[:100])
            ]
            st.session_state.current_topic = {"id": "review", "name": "復習テスト"}
            navigate_to("test")
        else:
            navigate_to("menu")
            
    if st.button("← 戻る", width="stretch"): 
        navigate_to("start")


def show_anki_import_screen():
    """Ankiパッケージ (.apkg) からのインポート画面"""
    st.title("🃏 Ankiパッケージ (.apkg) からインポート")
    
    uploaded_file = st.file_uploader("📁 .apkgファイルを選択してください", type=["apkg"])
    
    default_subj = ""
    if uploaded_file:
        default_subj = os.path.splitext(uploaded_file.name)[0]
        
    subj = st.text_input("📚 科目名（DBファイル名になります）", value=default_subj)
    use_ai = st.checkbox("🧠 Gemini AIでシラバスを自動生成する", value=True)
    st.caption("※ OFF にするとAnki内のカテゴリ情報から簡易シラバスを作成します（APIなし・高速）")
    
    # 既存科目への上書き確認
    subjects = database.list_subjects()
    confirm_overwrite = True
    if subj and subj in subjects:
        st.warning(f"⚠️ 科目「{subj}」は既に存在します。上書き（問題の追加）を続行する場合はチェックを入れてください。")
        confirm_overwrite = st.checkbox("上書きを許可する", value=False)

    col1, col2 = st.columns([1, 4])
    if col1.button("← 戻る", width="stretch"):
        navigate_to("start")
        
    if col2.button("🚀 インポート開始", width="stretch"):
        if not uploaded_file:
            st.error("ファイルを選択してください。")
            return
        if not subj:
            st.error("科目名を入力してください。")
            return
        if not confirm_overwrite:
            st.error("上書きの許可にチェックを入れてください。")
            return
            
        with st.spinner("インポート処理を実行しています..."):
            log_area = st.empty()
            log_text = []
            
            def progress_cb(msg):
                log_text.append(msg)
                # 最新の15行程度を表示
                log_area.code("\n".join(log_text[-15:]), language="text")

            try:
                from anki_importer import AnkiImporter
                
                # Streamlitのメモリ上のファイルを一時ファイルとして保存
                with tempfile.NamedTemporaryFile(delete=False, suffix=".apkg") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name
                
                importer = AnkiImporter(tmp_path, subj)
                result = importer.run(progress_cb=progress_cb, use_ai_syllabus=use_ai)
                
                os.remove(tmp_path) # 一時ファイルの削除
                
                if result["success"]:
                    st.success(result["message"])
                    st.session_state.current_subject = subj
                    st.session_state.cfg_data = database.load_cfg(subj)
                    ai_engine.set_model(st.session_state.cfg_data.get("gemini_model", ai_engine.get_model()))
                    
                    # シラバス編集画面へ渡すためのデータをセット
                    st.session_state.anki_plan = result["plan"]
                    import time
                    time.sleep(1)
                    navigate_to("anki_plan_editor")
                else:
                    st.error(result["message"])
            except Exception as e:
                show_friendly_error(e)


def show_anki_plan_editor_screen():
    """インポートしたシラバスの編集画面"""
    subj = st.session_state.current_subject
    plan = st.session_state.get("anki_plan", [])
    
    st.title(f"📋 章の確認・編集：{subj}")
    st.write("AIが生成した章の名前を確認してください。変更したい場合は直接書き直せます。")
    
    with st.form("anki_plan_editor_form"):
        new_plan = []
        for ch_i, chapter in enumerate(plan):
            st.markdown(f"**ID: {chapter.get('id', '')}**")
            new_name = st.text_input("章名", value=chapter.get("name", ""), key=f"ch_{ch_i}")
            new_ch = dict(chapter)
            new_ch["name"] = new_name
            
            subs = chapter.get("sub_topics", [])
            new_subs = []
            if subs:
                for sub_i, sub in enumerate(subs):
                    new_sub_name = st.text_input(f"小項目名 (ID: {sub.get('id', '')})", value=sub.get("name", ""), key=f"ch_{ch_i}_sub_{sub_i}")
                    new_sub = dict(sub)
                    new_sub["name"] = new_sub_name
                    new_subs.append(new_sub)
            
            new_ch["sub_topics"] = new_subs
            new_plan.append(new_ch)
            st.divider()
            
        col1, col2 = st.columns(2)
        if col1.form_submit_button("✅ 保存してメニューへ", width="stretch"):
            database.save_cfg(subj, {"plan": new_plan, "anki_imported": True})
            st.session_state.cfg_data = database.load_cfg(subj)
            navigate_to("menu")
            
        if col2.form_submit_button("→ スキップ（編集しない）", width="stretch"):
            database.save_cfg(subj, {"anki_imported": True})
            st.session_state.cfg_data = database.load_cfg(subj)
            navigate_to("menu")



def show_free_chat_screen():
    """自由質問画面 [手順4から遷移]"""
    st.title("💬 自由質問")
    subj = st.session_state.current_subject
    cfg = st.session_state.cfg_data
    
    # クラウド版準拠：現在学習中のトピックがあればそれを優先してRAG検索
    topic_name = st.session_state.get("current_topic", {}).get("name", subj)
    sys_prompt = f"あなたはAiTuです。科目「{subj}」について自由に質問に答えてください。{get_full_media_block(subj, query=topic_name)}"
    
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                render_ai_response(msg["content"])
            else:
                st.markdown(msg["content"])
    
    # フォーム形式の入力欄（ファイル添付とセットで配置）
    with st.container(border=True):
        uploaded_files = st.file_uploader("📁 ファイルを添付（スマホはカメラOK）", accept_multiple_files=True, key="free_chat_files")
        
        # 入力内容を一時保存する領域
        if "free_chat_p_to_process" not in st.session_state:
            st.session_state.free_chat_p_to_process = None

        # コールバック関数：送信ボタンが押された瞬間に実行される
        def handle_free_chat_submit():
            # 現在の入力値を退避
            st.session_state.free_chat_p_to_process = st.session_state.free_chat_input_widget
            # ウィジェットの値を空にする（再描画前に実行されるのでエラーにならない）
            st.session_state.free_chat_input_widget = ""

        p_input = st.text_area("質問を入力してください", placeholder="何でも聞いてください", key="free_chat_input_widget", height=100)
        st.button("🚀 質問を送信", width="stretch", type="primary", on_click=handle_free_chat_submit)

    # コールバックで保存された値があれば処理を開始
    if st.session_state.free_chat_p_to_process:
        p = st.session_state.free_chat_p_to_process
        st.session_state.free_chat_p_to_process = None # 処理済みとしてクリア
        
        combined_files = uploaded_files if uploaded_files else []
        user_content = p if not combined_files else f"【添付画像あり】\n{p}"
        st.session_state.chat_history.append({"role": "user", "content": user_content})
        
        # 画面更新のために一旦表示（spinner表示用）
        with st.chat_message("user"): st.markdown(p)
        with st.chat_message("assistant"):
            with st.spinner("考え中..."):
                try:
                    file_paths = []
                    for f in combined_files:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{f.name}") as tmp:
                            tmp.write(f.getvalue())
                            file_paths.append(tmp.name)

                    history = [{"role": "user" if m["role"]=="user" else "model", "parts": [m["content"]]} for m in st.session_state.chat_history[:-1]]
                    
                    if file_paths:
                        rep = ai_engine.gemini_chat_multimodal(sys_prompt, history, p, file_paths)
                    else:
                        rep = ai_engine.gemini_chat(sys_prompt, history, p, rag_store_name=cfg.get("rag_store_name"), use_web_search=cfg.get("use_web_search"))
                    
                    render_ai_response(rep)
                    st.session_state.chat_history.append({"role": "assistant", "content": rep})
                    
                    for fp in file_paths:
                        try: os.remove(fp)
                        except: pass
                except Exception as e:
                    show_friendly_error(e)
        st.rerun()

    st.divider()
    if st.button("← 学習メニューへ戻る", width="stretch"):
        navigate_to("menu")

def show_stats_screen():
    """学習状況ダッシュボード画面"""
    subj = st.session_state.current_subject
    cfg = st.session_state.cfg_data
    plan = cfg.get("plan", [])
    with_ai = st.session_state.get("stats_with_ai", False)

    st.title(f"📊 {subj} ― 学習状況ダッシュボード")

    if not plan:
        st.warning("学習計画が未設定です。")
        if st.button("← メニューへ戻る"): navigate_to("menu")
        return

    # メニューに戻るボタン（上部）
    if st.button("← 学習メニューへ戻る", key="back_top"):
        navigate_to("menu")

    with st.spinner("データを集計中... (AI講評がある場合は少し時間がかかります)"):
        # データ取得
        radar_base = database.get_radar_data(subj, plan, topic_settings=cfg.get("topic_settings", {}))
        forecast = database.get_review_forecast(subj)
        heatmap  = database.get_heatmap_data(subj)

        # ----------------------------------------------------
        # AI評価コメントの生成
        # ----------------------------------------------------
        ai_comments = {}
        if with_ai:
            weaknesses_data = cfg.get("weaknesses", {})
            ai_prompt = f"""あなたは親切で的確な学習コーチです。以下の学習データを分析し、JSON形式でコメントとアドバイスを返してください。
【科目】{subj} 【蓄積問題数】{database.count_all_questions(subj)}問
【分野別正解率】{", ".join(f"{d['label']}({d['format'] or '未設定'}): {round(d['rate']*100,1)}%" for d in radar_base) if radar_base else "データなし"}
【直近7日間の復習予測】{", ".join(f"{d['date']}({d['count']}問)" for d in forecast)}
【弱点記録】{json.dumps(weaknesses_data, ensure_ascii=False) if weaknesses_data else "なし"}

【出力形式】以下のJSONのみを出力してください（Markdownなどは不要）:
{{ "radar_comment": "...", "radar_advice": "...", "forecast_comment": "...", "forecast_advice": "...", "heatmap_comment": "...", "heatmap_advice": "...", "overall_comment": "...", "overall_advice": "..." }}"""
            try: ai_comments = json.loads(ai_engine._extract_json(ai_engine.gemini_once_json(ai_prompt)))
            except: pass

        # ----------------------------------------------------
        # 1. レーダーチャートの構築
        # ----------------------------------------------------
        all_topic_ids = []
        for top in plan:
            subs = top.get("sub_topics", [])
            if subs:
                for st_obj in subs: all_topic_ids.append(st_obj["id"])
            else:
                all_topic_ids.append(top["id"])

        format_options = [
            ("各分野の選択出題形式の集計", cfg.get("topic_settings", {})),
            ("すべての形式（総合）", {}),
            ("記述式問題", {t: "記述式問題" for t in all_topic_ids}),
            ("正誤問題", {t: "正誤問題" for t in all_topic_ids}),
            ("5肢択一問題", {t: "5肢択一問題" for t in all_topic_ids}),
            ("穴埋め問題", {t: "穴埋め問題" for t in all_topic_ids}),
            ("論証問題", {t: "論証問題" for t in all_topic_ids}),
            ("計算問題", {t: "理系用計算問題（途中式あり）" for t in all_topic_ids}),
            ("証明・導出", {t: "理系用証明・導出問題" for t in all_topic_ids})
        ]

        radar_fig = go.Figure()
        buttons = []
        for i, (fmt_name, ts) in enumerate(format_options):
            radar = database.get_radar_data(subj, plan, topic_settings=ts)
            if not radar: continue
            labels = [d["label"] for d in radar]
            rates  = [round(d["rate"] * 100, 1) for d in radar]
            fmt_set = set([d["format"] for d in radar if d["format"]])
            
            fmt_display = list(fmt_set)[0] if len(fmt_set) == 1 else "複数形式混在" if len(fmt_set) > 1 else "未設定" if i == 0 else fmt_name
            hover_texts = [f"{d['label']}<br>{round(d['rate']*100,1)}%<br>形式: {fmt_display}" for d in radar]

            line_color = "#3d7ebf" if i == 0 else "#e67e22" if i == 1 else "#2a9d8f"
            fill_color = "rgba(61,126,191,0.25)" if i == 0 else "rgba(230,126,34,0.25)" if i == 1 else "rgba(42,157,143,0.25)"

            if labels:
                radar_fig.add_trace(go.Scatterpolar(
                    r=rates+[rates[0]], theta=labels+[labels[0]], fill="toself",
                    fillcolor=fill_color, line=dict(color=line_color, width=2),
                    name=fmt_name, visible=(i==0), hovertext=hover_texts+[hover_texts[0]], hoverinfo="text"
                ))
                visibilities = [False] * len(format_options)
                visibilities[i] = True
                buttons.append(dict(label=fmt_name, method="update", args=[{"visible": visibilities}]))

        if buttons:
            radar_fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=False,
                updatemenus=[dict(
                    active=0, 
                    buttons=buttons, 
                    x=1.0, 
                    xanchor="right", 
                    y=1.3,        # グラフと被らないよう少し上に
                    yanchor="top", 
                    bgcolor="#ffffff",    # 背景を白に固定
                    bordercolor="#1e90ff",# 枠線をつけて見やすく
                    borderwidth=1,
                    font=dict(color="#333333", size=12) # 文字色を濃いグレーに
                )],
                margin=dict(t=50, b=40, l=40, r=40)
            )

        # ----------------------------------------------------
        # 2. 復習予測（棒グラフ）の構築
        # ----------------------------------------------------
        topic_name_map = {}
        ordered_tids = []
        for top in plan:
            subs = top.get("sub_topics", [])
            if subs:
                for st_obj in subs:
                    topic_name_map[st_obj["id"]] = st_obj["name"]
                    ordered_tids.append(st_obj["id"])
            else:
                topic_name_map[top["id"]] = top["name"]
                ordered_tids.append(top["id"])

        fc_dates = [d["date"] for d in forecast]
        fc_dates_display = []
        for i, d in enumerate(fc_dates):
            dt = datetime.date.fromisoformat(d)
            short_d = f"{dt.month}/{dt.day}" 
            if i == 0: fc_dates_display.append(f"{short_d} (今日)")
            else: fc_dates_display.append(short_d)

        active_tids = set().union(*(d.get("topics", {}).keys() for d in forecast))
        all_forecast_topics = [tid for tid in ordered_tids if tid in active_tids]
        for tid in active_tids:
            if tid not in all_forecast_topics: all_forecast_topics.append(tid)

        colors = ["#3d7ebf", "#e67e22", "#2a9d8f", "#e74c3c", "#9b59b6", "#f1c40f", "#1abc9c", "#34495e", "#7f8c8d", "#d35400"]
        bar_fig = go.Figure()

        if not all_forecast_topics:
            bar_fig.add_trace(go.Bar(x=fc_dates_display, y=[0]*7))
        else:
            for idx, tid in enumerate(all_forecast_topics):
                t_name = topic_name_map.get(tid, tid)
                y_vals = [d.get("topics", {}).get(tid, 0) for d in forecast]
                if sum(y_vals) == 0: continue
                
                hover_texts = [f"日付: {fc_dates[i]}<br>分野: {t_name}<br>問題数: {v}問" for i, v in enumerate(y_vals)]
                text_vals = [str(v) if v > 0 else "" for v in y_vals]
                
                bar_fig.add_trace(go.Bar(
                    name=t_name, x=fc_dates_display, y=y_vals, text=text_vals, textposition="inside",
                    hovertext=hover_texts, hoverinfo="text", marker_color=colors[idx % len(colors)]
                ))
            
            total_counts = [d["count"] for d in forecast]
            bar_fig.add_trace(go.Scatter(
                x=fc_dates_display, y=total_counts, mode="text",
                text=[str(v) if v > 0 else "" for v in total_counts],
                textposition="top center", hoverinfo="skip", showlegend=False
            ))

        bar_fig.update_layout(
            barmode="stack", xaxis=dict(type='category'), margin=dict(t=20, b=40, l=40, r=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        # ----------------------------------------------------
        # 3. 学習ヒートマップの構築
        # ----------------------------------------------------
        today = datetime.date.today()
        cur = today - datetime.timedelta(days=363)
        cur -= datetime.timedelta(days=cur.weekday())

        metrics = ["回答数", "正解数", "正解率"]
        z_data = {m: [] for m in metrics}
        hover_data = {m: [] for m in metrics}
        col_labels, week_dates = [], []
        week_vals = {m: [] for m in metrics}

        while cur <= today + datetime.timedelta(days=6 - today.weekday()):
            stats = heatmap.get(cur.isoformat(), {"count": 0, "correct": 0})
            cnt, cor = stats["count"], stats["correct"]
            rate = round((cor / cnt * 100), 1) if cnt > 0 else 0
            
            week_dates.append(cur.isoformat())
            week_vals["回答数"].append(cnt)
            week_vals["正解数"].append(cor)
            week_vals["正解率"].append(rate)
            
            if len(week_dates) == 7:
                for m in metrics:
                    z_data[m].append(week_vals[m][:])
                    h_list = [f"日付: {week_dates[i]}<br><b>{m}: {week_vals[m][i]}</b><br>(計: {cnt}問 / 正解: {cor}問)" for i in range(7)]
                    hover_data[m].append(h_list)
                col_labels.append(week_dates[0][:7])
                week_dates = []
                for m in metrics: week_vals[m] = []
            cur += datetime.timedelta(days=1)

        heat_fig = go.Figure()
        for i, m in enumerate(metrics):
            z_matrix = [list(row) for row in zip(*z_data[m])]
            h_matrix = [list(row) for row in zip(*hover_data[m])]
            cs = [[0.0, "#ebedf0"], [1.0, "#196127"]] if m == "回答数" else [[0.0, "#ebedf0"], [1.0, "#0d47a1"]] if m == "正解数" else [[0.0, "#ebedf0"], [0.5, "#f1c40f"], [1.0, "#27ae60"]]
            heat_fig.add_trace(go.Heatmap(
                z=z_matrix, 
                x=list(range(len(z_data[m]))), 
                y=["月","火","水","木","金","土","日"],
                text=h_matrix, 
                hovertemplate="%{text}<extra></extra>", 
                colorscale=cs, 
                showscale=False,
                xgap=1,             # ← 3から1に変更（罫線を細く）
                ygap=1,             # ← 3から1に変更（罫線を細く）
                visible=(i==0), 
                name=m
            ))

        buttons = []
        for i, m in enumerate(metrics):
            vis = [False] * len(metrics)
            vis[i] = True
            buttons.append(dict(label=m, method="update", args=[{"visible": vis}]))

        shown_months = {}; tick_vals = []; tick_texts = []
        for i, lbl in enumerate(col_labels):
            if lbl not in shown_months:
                shown_months[lbl] = i; tick_vals.append(i); tick_texts.append(lbl)

        heat_fig.update_layout(
            updatemenus=[dict(
                active=0, 
                buttons=buttons, 
                x=1.0, 
                xanchor="right", 
                y=1.3,        # グラフと被らないよう少し上に
                yanchor="top", 
                bgcolor="#ffffff",    # 背景を白に固定
                bordercolor="#1e90ff",# 枠線をつけて見やすく
                borderwidth=1,
                font=dict(color="#333333", size=12) # 文字色を濃いグレーに
            )],
            xaxis=dict(tickvals=tick_vals, ticktext=tick_texts, showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False, autorange="reversed"),
            plot_bgcolor="#f0f0f0",
            margin=dict(t=40, b=40, l=40, r=40), height=280
        )

    # --- UIのレンダリング開始 ---

    # 1. AI全体講評を最上部に配置 (クラウド版準拠)
    if with_ai and ai_comments.get("overall_comment"):
        st.subheader("🌟 全体 講評・アドバイス")
        st.info(f"📝 **講評:**\n\n{ai_comments.get('overall_comment')}")
        st.success(f"💡 **アドバイス:**\n\n{ai_comments.get('overall_advice')}")
        st.divider()

    # ツールチップ用の説明文を定義
    radar_info_text = """**【レーダーチャートの仕様説明】**

**◆ レーダーチャートの計算**
各分野に含まれる全問題の「過去の累積正解率の平均」を表示しています。
※白紙回答は分野ごとの出題では不正解扱いで正解率を下げますが、復習問題ではスキップ扱い(出題されていない扱い)です。

**◆ 学習メニューの「理解度」との違い**
学習メニューに表示される「理解度」は、各問題を最後に解いた直近のテストで正解できている問題数をカウントしています。
レーダーチャートは過去の全履歴を含めた長期的な定着度を、理解度は直近の状態を表しています。"""

    heat_info_text = """**【ヒートマップの仕様説明】**

**◆ 各指標の定義**
・**回答数**：AIが採点（送信）を行った問題の総数です。
・**正解数**：AIが「正解」と判定した問題の総数です。
・**正解率**：(正解数 ÷ 回答数) × 100 で算出されます。

**◆ 白紙回答（未入力）の扱い**
・**確認テスト**：回答数にカウントされ「不正解」となるため、その日の正解率を下げる。
・**復習テスト**：採点対象から除外され、回答数・正解数ともに影響なし。"""

    st.subheader("① 分野別 弱点レーダーチャート", help=radar_info_text)
    st.plotly_chart(radar_fig, width="stretch")
    if with_ai and ai_comments.get("radar_comment"):
        st.info(f"🤖 **AI評価:** {ai_comments.get('radar_comment')}")
        st.success(f"💡 **アドバイス:** {ai_comments.get('radar_advice')}")

    st.divider()

    st.subheader("② 直近7日間の復習予測")
    st.plotly_chart(bar_fig, width="stretch")
    if with_ai and ai_comments.get("forecast_comment"):
        st.info(f"🤖 **AI評価:** {ai_comments.get('forecast_comment')}")
        st.success(f"💡 **アドバイス:** {ai_comments.get('forecast_advice')}")

    st.divider()

    st.subheader("③ 学習継続ヒートマップ（過去52週）", help=heat_info_text)
    # HTMLのdivタグで囲んで横スクロール可能にする
    st.markdown('<div class="scroll-container">', unsafe_allow_html=True)

    # スマホでも1マスが潰れないよう、横幅を800pxに固定して生成
    heat_fig.update_layout(width=800, height=300) 

    # use_container_width=False にするのがポイント（画面幅に圧縮させない）
    st.plotly_chart(heat_fig, use_container_width=False)

    st.markdown('</div>', unsafe_allow_html=True)
    
    if with_ai and ai_comments.get("heatmap_comment"):
        st.info(f"🤖 **AI評価:** {ai_comments.get('heatmap_comment')}")
        st.success(f"💡 **アドバイス:** {ai_comments.get('heatmap_advice')}")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("← 学習メニューへ戻る", key="back_bottom", width="stretch"):
        navigate_to("menu")


def show_anki_export_screen():
    """Ankiエクスポート画面 (移植版)"""
    subj = st.session_state.current_subject
    cfg = st.session_state.cfg_data
    if not subj: navigate_to("start")

    st.title(f"🃏 AnkiDec出力 : {subj}")

    tab1, tab2 = st.tabs(["既存の問題を出力", "✨ AIで新規問題を生成して出力"])

    # --- Tab 1: 既存問題のエクスポート ---
    with tab1:
        st.subheader("DBに保存されている問題を出力")
        export_mode = st.selectbox(
            "出力する範囲を選択",
            ["全ての小問を出力", "弱点の小問を出力", "直近不正解の小問を出力"],
            key="exp_mode"
        )
        
        if st.button("生成準備を開始", key="btn_exp_db"):
            filter_map = {"全ての小問を出力": "ALL", "弱点の小問を出力": "WEAK", "直近不正解の小問を出力": "RECENT_WRONG"}
            rows = database.get_questions_for_export(subj, filter_map[export_mode])
            
            if not rows:
                st.warning("該当する問題がありません。")
            else:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".apkg") as tmp:
                    media_dir = database.get_media_dir(subj)
                    success, msg = anki_exporter.export_deck(tmp.name, subj, export_mode, rows, media_dir)
                    if success:
                        with open(tmp.name, "rb") as f:
                            st.download_button(
                                label="📥 Ankiパッケージ(.apkg)をダウンロード",
                                data=f.read(),
                                file_name=f"Anki_{subj}_{export_mode}.apkg",
                                mime="application/octet-stream"
                            )
                        st.success("エクスポートの準備が完了しました。")
                    else:
                        st.error(msg)

    # --- Tab 2: AIによる新規生成 ---
    with tab2:
        st.subheader("学習計画から新しい問題を生成")
        st.info("※ここで生成される問題はデータベースには保存されず、直接Anki用ファイルとして書き出されます。")
        
        # 分野選択
        plan = cfg.get("plan", [])
        topic_options = []
        for top in plan:
            subs = top.get("sub_topics", [])
            if subs:
                for st_obj in subs: topic_options.append({"id": st_obj["id"], "name": st_obj["name"]})
            else:
                topic_options.append({"id": top["id"], "name": top["name"]})
        
        selected_topics = st.multiselect(
            "生成対象の分野を選択",
            options=topic_options,
            format_func=lambda x: f"{x['id']}: {x['name']}",
            default=topic_options[:1] if topic_options else None
        )
        
        num_per_topic = st.number_input("1分野あたりの問題数", min_value=1, max_value=20, value=5)

        if st.button("🚀 AI生成を開始 (時間がかかります)", key="btn_gen_ai"):
            if not selected_topics:
                st.error("分野を1つ以上選択してください。")
            else:
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                try:
                    for i, topic in enumerate(selected_topics):
                        status_text.text(f"⏳ 生成中 ({i+1}/{len(selected_topics)}): {topic['name']}")
                        
                        # そのトピックに関連する画像だけを10枚抽出
                        media_block = get_full_media_block(subj, topic["name"])
                        lesson_text = database.load_explane(subj, topic["id"]) or ""
                        lesson_scope = (f"\n\n【出題範囲の限定】必ず以下の「説明本文」の内容のみから作成してください。\n--- 説明本文 ---\n{re.sub(r'```python\\s*\\n([\\s\\S]*?)```', '【図表省略】', lesson_text)}\n--- ここまで ---" if lesson_text else "")
                        
                        q_format = cfg.get("topic_settings", {}).get(topic["id"], "記述式問題")
                        prompt_modifiers = ""
                        ans_hint = "模範解答"
                        if q_format == "正誤問題":
                            prompt_modifiers += "\n【出題形式：正誤問題】問題文は必ず「〇」か「×」で答えられる文章にし、問題文の冒頭に必ず「次の記述の正誤を答えてください。」という一文を入れてください。"
                            ans_hint = "〇 または ×"
                        elif q_format == "5肢択一問題":
                            prompt_modifiers += "\n【出題形式：5肢択一問題】問題文の最後に必ず「1. 〜 2. 〜 3. 〜 4. 〜 5. 〜」という形式で5つの選択肢を提示してください。"
                            ans_hint = "選択肢の番号（1〜5）"
                        elif q_format == "穴埋め問題":
                            prompt_modifiers += "\n【出題形式：穴埋め問題】問題文の重要なキーワードを（　）で空欄にし、そこに入る語句を答えさせる形式にしてください。1つの問題につき空欄は1〜2箇所としてください。"
                        
                        prompt = f"""科目「{subj}」の「{topic['name']}」について、Anki用の問題と解答を {num_per_topic}問 作成してください。
{prompt_modifiers}

【重複・バラエティに関する絶対ルール】
1. 今回作成する {num_per_topic}問 の中で、問う内容や概念が重複しないように細心の注意を払ってください。
2. 各問題は、分野内の異なる側面（定義、計算、理由、例外、応用など）を網羅するようにバラエティ豊かに構成してください。

【図表・メディア活用のスマート・ルール】
1. あなたには、この科目のために用意された画像リスト（下記）が提供されています。
2. **問題文(`question`)での画像活用：**
   - 画像の中に答え（用語や数値など）が直接書かれている場合は、その画像を問題文に使用してはいけません。
   - 「この図が示す現象は何か？」「図中のAは何を指しているか？」といった、画像の内容を分析・解釈させる問題の場合は、積極的に画像を使用して出題してください。
3. **解答(`answer`)や解説(`explanation`)での画像活用：**
   - 理解を助けるために、解答や解説の中では積極的に図解としての画像を挿入してください。
4. **【厳禁】** [※図1] や (画像:...) のようなテキスト形式での引用はシステムが読み取れないため「絶対に禁止」です。必ず `<img src="ファイル名">` 形式を使用してください。
5. Ankiアプリ用データのため、Pythonコード(Plotly)は絶対に使用しないでください。画像タグ（<img>）のみを使用してください。

{media_block}
{lesson_scope}

【出力形式】以下のJSON構造のみを出力（他テキスト不要）：
[ {{"question": "問題文", "answer": "{ans_hint}", "explanation": "詳しい解説"}} ]"""

                        # APIリトライと待機時間の実装
                        max_retries = 3
                        success_gen = False
                        for attempt in range(max_retries):
                            try:
                                raw = ai_engine.gemini_once_json(prompt, use_web_search=cfg.get("use_web_search"))
                                new_qs = json.loads(ai_engine._extract_json(raw))
                                if isinstance(new_qs, list):
                                    results.extend(new_qs)
                                    success_gen = True
                                    # 大量生成時は API 制限にかかりやすいため、長めに待機
                                    time.sleep(20)
                                    break
                            except Exception as e:
                                if attempt < max_retries - 1:
                                    status_text.text(f"⚠️ リトライ中 ({attempt+1}/{max_retries}): {topic['name']}")
                                    time.sleep(30)
                                else:
                                    st.error(f"❌ {topic['name']} の生成に失敗しました: {e}")

                        progress_bar.progress((i + 1) / len(selected_topics))

                    if results:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".apkg") as tmp:
                            media_dir = database.get_media_dir(subj)
                            success, msg = anki_exporter.export_deck(tmp.name, subj, "AI_Generated", results, media_dir)
                            if success:
                                with open(tmp.name, "rb") as f:
                                    st.download_button(
                                        label="📥 生成されたAnkiパッケージをダウンロード",
                                        data=f.read(),
                                        file_name=f"Anki_AI_Gen_{subj}.apkg",
                                        mime="application/octet-stream"
                                    )
                                st.success(f"合計 {len(results)} 問の生成が完了しました！")
                except Exception as e:
                    show_friendly_error(e)

    if st.button("← 学習メニューへ戻る"):
        navigate_to("menu")


# --- 3. メインルーティング ---
def main():
    apply_custom_styles()
    pages = {
        "start": show_start_screen,
        "new_subject": show_new_subject_screen,
        "confirm_plan": show_confirm_plan_screen,
        "menu": show_menu_screen,
        "edit_settings": show_edit_settings_screen,
        "stats": show_stats_screen,
        "lesson": show_lesson_screen,
        "test": show_test_screen,
        "result": show_result_screen,
        "select_subject": show_select_subject_screen,
        "free_chat": show_free_chat_screen,
        "anki_import": show_anki_import_screen,
        "anki_plan_editor": show_anki_plan_editor_screen,
        "anki_export": show_anki_export_screen,
        "image_batch_import": show_image_batch_import_screen
    }
    pages[st.session_state.page]()

if __name__ == "__main__":
    main()
