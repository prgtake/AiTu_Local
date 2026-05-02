# Copyright (c) 2026 Datan (データン)
# Licensed under a Custom Hybrid License (Free for Individuals, Paid for Commercial).
# See README.md for licensing details.
# -*- coding: utf-8 -*-
"""
=======================================================
  app_tkinter.py (UI層)
  tkinterによるGUI表示とユーザーイベントのハンドリング
  ai_engine.py と database.py、anki_exporter.py、
  anki_importer.py、html_builder.pyに依存します。
  ※google.genai は直接インポートしません（完全分離）
=======================================================
"""
import sys
import os
import time
import re
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import json
import datetime

# =====================================================
#  ディレクトリ設定（EXE化対応）
# =====================================================
if getattr(sys, "frozen", False):
    # EXEとして実行されている場合
    BASE_DIR = os.path.dirname(sys.executable)
    # 必要に応じて一時解凍先を取得（リソース読み込み用）
    BUNDLE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    # 通常のスクリプトとして実行されている場合
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = BASE_DIR

# 作業ディレクトリをEXEのある場所に固定
# これにより database.py 等が使う相対パスが正しく動作します
os.chdir(BASE_DIR)

import ai_engine
import database
import html_builder
import anki_exporter

# =====================================================
#  メディア要約ブロック生成（AI生成プロンプト共通ヘルパー）
# =====================================================
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

# =====================================================
#  共通ウィジェット・設定
# =====================================================

# アプリのバージョンを定義（バグ報告・サポート時にタイトルバーで確認できる）
APP_VERSION = "1.0.2"

# 実行環境(OS)を判定して最適なフォントファミリを設定
if sys.platform.startswith("win"):
    _BASE_FONT = "メイリオ"           # Windows用
elif sys.platform == "darwin":
    _BASE_FONT = "Hiragino Sans"    # Mac用
else:
    _BASE_FONT = "Noto Sans CJK JP" # Chromebook (Linux)用

# 自動判定したフォントを各スタイルに適用
FONT_NORMAL  = (_BASE_FONT, 11)
FONT_BOLD    = (_BASE_FONT, 11, "bold")
FONT_TITLE   = (_BASE_FONT, 14, "bold")
FONT_SMALL   = (_BASE_FONT, 9)

BG           = "#f5f5f5"
ACCENT       = "#3d7ebf"
BTN_FG       = "white"

def safe_json_loads(raw_text: str) -> dict:
    """
    AIのエスケープミスによるクラッシュを防ぐ安全なJSON読み込み。
    ai_engine._extract_json で修復済みのテキストを受け取るが、
    それでも失敗する場合に文字単位で未エスケープバックスラッシュを修正する。
    """
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    def _fix_unescaped_backslashes(text: str) -> str:
        result = []
        in_string = False
        escape_next = False
        for idx, ch in enumerate(text):
            if escape_next:
                result.append(ch)
                escape_next = False
                continue
            if ch == '\\':
                next_ch = text[idx + 1] if idx + 1 < len(text) else ''
                if next_ch in ('"', '\\', '/', 'b', 'f', 'n', 'r', 't', 'u'):
                    result.append(ch)
                    escape_next = True
                elif in_string:
                    result.append('\\\\')
                else:
                    result.append(ch)
                continue
            if ch == '"':
                in_string = not in_string
            result.append(ch)
        return ''.join(result)

    try:
        return json.loads(_fix_unescaped_backslashes(raw_text))
    except Exception:
        pass

    return {
        "total_score": 0,
        "results": [],
        "overall_comment": "【システム】AIからの応答を解析できませんでした。お手数ですが、もう一度やり直してください。",
        "weakness": "",
        "recommendation": "advance"
    }

def _add_image_attach_ui(parent, bg_color=None):
    """ファイル添付UIの生成（PCカメラ撮影対応版）"""
    bg        = bg_color or BG
    file_list = []
    frame     = tk.Frame(parent, bg=bg)
    top_row   = tk.Frame(frame, bg=bg)
    top_row.pack(fill="x")
    _FILETYPES = [("Gemini対応ファイル", "*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp;*.pdf;*.txt;*.md;*.csv;*.py;*.js;*.ts;*.html;*.css;*.json;*.xml;*.yaml;*.yml;*.mp3;*.wav;*.m4a;*.aac;*.flac;*.mp4;*.mov;*.avi;*.mkv;*.webm"), ("すべてのファイル", "*.*")]
    badge_row = tk.Frame(frame, bg=bg)
    badge_row.pack(fill="x")

    def _refresh_badges():
        for w in badge_row.winfo_children(): w.destroy()
        for i, fp in enumerate(file_list):
            ext  = os.path.splitext(fp)[1].lower()
            icon = "🖼️" if ext in (".png",".jpg",".jpeg",".gif",".webp",".bmp") else "📄" if ext == ".pdf" else "🎬" if ext in (".mp4",".mov",".avi",".mkv",".webm") else "🎵" if ext in (".mp3",".wav",".m4a",".aac",".flac") else "📎"
            badge = tk.Frame(badge_row, bg="#e3f2fd", relief="solid", bd=1)
            badge.pack(side="left", padx=(0, 4), pady=2)
            tk.Label(badge, text=f"{icon} {os.path.basename(fp)}", font=FONT_SMALL, bg="#e3f2fd", fg="#1565c0").pack(side="left", padx=4)
            def make_del(idx):
                def _del(): del file_list[idx]; _refresh_badges()
                return _del
            tk.Button(badge, text="✕ 添付解除", font=FONT_SMALL, bg="#e3f2fd", fg="#888", relief="flat", cursor="hand2", command=make_del(i)).pack(side="left")

    def attach():
        paths = filedialog.askopenfilenames(title="添付ファイルを選択（複数可）", filetypes=_FILETYPES)
        for p in paths:
            if p and p not in file_list: file_list.append(p)
        _refresh_badges()
        
    def open_camera():
        try:
            import cv2
            from PIL import Image, ImageTk
        except ImportError:
            messagebox.showerror("ライブラリ不足", "カメラ機能を使用するには opencv-python と Pillow が必要です。\nコマンドプロンプトやターミナルで以下を実行してください:\n\npip install opencv-python Pillow")
            return

        cam_dlg = tk.Toplevel(parent)
        cam_dlg.title("📷 カメラで撮影")
        cam_dlg.geometry("640x560")
        cam_dlg.transient(parent.winfo_toplevel())
        cam_dlg.grab_set()

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            messagebox.showerror("エラー", "カメラが見つからないか、アクセスできません。")
            cam_dlg.destroy()
            return

        video_label = tk.Label(cam_dlg, bg="black")
        video_label.pack(fill="both", expand=True)
        cam_dlg._after_id = None

        def update_frame():
            ret, frame_img = cap.read()
            if ret:
                cv_img = cv2.cvtColor(frame_img, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(cv_img)
                # 画面サイズに合わせてリサイズ（アスペクト比維持）
                pil_img.thumbnail((640, 480), Image.Resampling.LANCZOS)
                imgtk = ImageTk.PhotoImage(image=pil_img)
                video_label.imgtk = imgtk
                video_label.configure(image=imgtk)
            cam_dlg._after_id = cam_dlg.after(15, update_frame)

        def capture():
            ret, frame_img = cap.read()
            if ret:
                import tempfile
                import datetime
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                # 一時ファイルとして保存
                fd, path = tempfile.mkstemp(suffix=f"_{timestamp}.jpg")
                os.close(fd)
                cv2.imwrite(path, frame_img)
                
                if path not in file_list:
                    file_list.append(path)
                _refresh_badges()
            close_camera()

        def close_camera():
            if cam_dlg._after_id is not None:
                cam_dlg.after_cancel(cam_dlg._after_id)
            if cap.isOpened():
                cap.release()
            cam_dlg.destroy()

        btn_f = tk.Frame(cam_dlg)
        btn_f.pack(pady=10)
        tk.Button(btn_f, text="📸 撮影して添付", font=FONT_BOLD, bg="#d84315", fg="white", cursor="hand2", padx=16, pady=4, command=capture).pack(side="left", padx=10)
        tk.Button(btn_f, text="キャンセル", font=FONT_NORMAL, bg="#888", fg="white", cursor="hand2", padx=16, pady=4, command=close_camera).pack(side="left", padx=10)

        cam_dlg.protocol("WM_DELETE_WINDOW", close_camera)
        update_frame()

    def clear_all():
        file_list.clear(); _refresh_badges()

    styled_btn(top_row, "📎 ファイルを添付", attach, width=16, bg="#1565c0").pack(side="left", padx=(0, 4))
    styled_btn(top_row, "📷 カメラで撮影", open_camera, width=16, bg="#00796b").pack(side="left", padx=(0, 4))
    styled_btn(top_row, "🗑 添付クリア", clear_all, width=14,  bg="#888").pack(side="left")
    return frame, file_list

def create_resizable_text(parent, width=80, default_height=3):
    f = tk.Frame(parent, bg=BG)
    txt = tk.Text(f, font=FONT_NORMAL, width=width, height=default_height, relief="solid", wrap="word", undo=True)
    txt.pack(side="top", fill="x")
    grip = tk.Label(f, text="≡ ドラッグで広げる", font=FONT_SMALL, bg="#e0e0e0", fg="#555", cursor="sb_v_double_arrow")
    grip.pack(side="top", fill="x")
    def on_press(event):
        grip._start_y      = event.y_root
        grip._start_height = txt.winfo_height()
    def on_drag(event):
        dy       = event.y_root - grip._start_y
        line_px  = txt.winfo_height() / max(txt.cget("height"), 1)
        new_h    = int((grip._start_height + dy) / max(line_px, 18))
        txt.configure(height=max(2, new_h))
    grip.bind("<Button-1>",  on_press)
    grip.bind("<B1-Motion>", on_drag)
    return f, txt

def styled_btn(parent, text, command, width=18, bg=ACCENT):
    return tk.Button(parent, text=text, command=command, font=FONT_BOLD, bg=bg, fg=BTN_FG, activebackground="#2a5f9e", relief="flat", cursor="hand2", width=width, pady=4)

def section_label(parent, text):
    return tk.Label(parent, text=text, font=FONT_TITLE, bg=BG, fg="#222")

class TutorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"AiTu - GeminiによるAiTutor (v{APP_VERSION})")
        self.geometry("900x800")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.withdraw()

        self.current_subject = None
        self.cfg_data        = {}
        self.current_topic   = None
        self.chat_history    = []
        self.test_history    = []
        self.test_questions  = []
        self.user_answers    = []
        self._screen_id      = 0

        self.after(100, self._show_start_dialog)

    def _create_scrollable_container(self, parent_frame):
        canvas = tk.Canvas(parent_frame, bg=BG, highlightthickness=0)
        v_scroll = tk.Scrollbar(parent_frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_win, width=e.width))

        canvas.configure(yscrollcommand=v_scroll.set)
        v_scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        def _on_mousewheel(e):
            if e.delta:
                canvas.yview_scroll(int(-1*(e.delta/120)), "units")
            elif e.num == 4:
                canvas.yview_scroll(-1, "units")
            elif e.num == 5:
                canvas.yview_scroll(1, "units")

        def _bind(e): 
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_mousewheel)
            canvas.bind_all("<Button-5>", _on_mousewheel)
        def _unbind(e): 
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")
        
        canvas.bind("<Enter>", _bind)
        canvas.bind("<Leave>", _unbind)

        return inner

    def _show_start_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("学習開始")
        dlg.attributes("-topmost", True)
        dlg.focus_force()
        dlg.after(500, lambda: dlg.attributes("-topmost", False))
        dlg.configure(bg=BG)
        dlg.grab_set()
        dlg.resizable(True, True)
        dlg.update_idletasks()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"620x180+{(sw-620)//2}+{(sh-180)//2}")
        tk.Label(dlg, text="どちらを選択しますか？", font=FONT_BOLD, bg=BG).pack(pady=24)
        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack()
        
        def _open_main(): self.deiconify(); self.lift(); self.focus_force()
        
        def on_new(): 
            dlg.destroy()
            _open_main()
            if hasattr(self, "_draft_subject_data"):
                self._draft_subject_data = {}
            self._show_new_subject_screen()
            
        def on_existing():
            subs = database.list_subjects()
            dlg.destroy()
            if not subs:
                messagebox.showinfo("情報", "既存の科目がありません。新規作成してください。")
                self._show_start_dialog()
            else:
                _open_main(); self._show_subject_list_screen(subs)
                
        def on_anki(): dlg.destroy(); _open_main(); self._show_anki_import_screen()
        
        styled_btn(dlg, "📝 新規分野を設定",      on_new,      width=16).pack(in_=btn_frame, side="left", padx=8)
        styled_btn(dlg, "📂 既存分野を選択",      on_existing, width=16).pack(in_=btn_frame, side="left", padx=8)
        styled_btn(dlg, "🃏 Ankiから作成",        on_anki,     width=16).pack(in_=btn_frame, side="left", padx=8)
        self.wait_window(dlg)

    def _show_new_subject_screen(self):
        self._clear()
        draft = getattr(self, "_draft_subject_data", {})
        
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)
        f = self._create_scrollable_container(outer)
        f.configure(padx=30, pady=20)
        
        f.columnconfigure(1, weight=1)
        f.rowconfigure(5, weight=1)
        section_label(f, "📝 新規分野の設定").grid(row=0, column=0, columnspan=2, pady=(0,20), sticky="w")
        
        labels = ["分野名（例：統計学）", "目標到達レベル（例：大学入試合格レベル）", "目標到達までの時間（例：20時間）※任意", "説明のレベル（例：中学生にも分かるレベル）"]
        draft_keys = ["subj", "level", "hours", "explain_level"]
        self._entries = []
        for i, lbl in enumerate(labels):
            tk.Label(f, text=lbl, font=FONT_NORMAL, bg=BG).grid(row=i+1, column=0, sticky="w", pady=6)
            e = tk.Entry(f, font=FONT_NORMAL, width=40, relief="solid")
            e.grid(row=i+1, column=1, sticky="ew", padx=12, pady=6)
            e.insert(0, draft.get(draft_keys[i], ""))
            self._entries.append(e)

        tk.Label(f, text="Geminiモデルコード", font=FONT_NORMAL, bg=BG).grid(row=5, column=0, sticky="w", pady=6)
        model_frame = tk.Frame(f, bg=BG)
        model_frame.grid(row=5, column=1, sticky="ew", padx=12, pady=6)
        self._model_entry = tk.Entry(model_frame, font=FONT_NORMAL, width=36, relief="solid")
        self._model_entry.pack(side="left")
        self._model_entry.insert(0, draft.get("gemini_model", ai_engine.get_model()))
        tk.Label(model_frame, text="  ※例: gemini-2.0-flash", font=FONT_SMALL, bg=BG, fg="#888").pack(side="left")

        tk.Label(f, text="Embeddingモデル", font=FONT_NORMAL, bg=BG).grid(row=6, column=0, sticky="w", pady=6)
        emb_frame = tk.Frame(f, bg=BG)
        emb_frame.grid(row=6, column=1, sticky="ew", padx=12, pady=6)
        self._emb_entry = tk.Entry(emb_frame, font=FONT_NORMAL, width=36, relief="solid")
        self._emb_entry.pack(side="left")
        self._emb_entry.insert(0, draft.get("embedding_model", ai_engine.get_embedding_model()))
        tk.Label(emb_frame, text="  ※標準: models/gemini-embedding-001", font=FONT_SMALL, bg=BG, fg="#888").pack(side="left")

        tk.Label(f, text="留意事項（任意）", font=FONT_NORMAL, bg=BG).grid(row=7, column=0, sticky="nw", pady=6)
        notes_hint = (
            "法律系分野の例：\n"
            "1.説明は法律の条文を明示するスタイルを厳守すること。\n"
            "2.法律用語・専門用語は極めて厳密に採点すること。"
            "日常用語での言い換えや、類義語の使用は一切認めず、"
            "必ず「不正解」とすること。\n"
            "3.文脈や意味が合っていても、条文上の正しい語句（法定用語）が"
            "使われていなければ0点とすること。\n"
            "4.解説では「意味は通じますが、法律用語としては〇〇が正解です。"
            "なぜなら?」と、法的な定義の違いを明確に指摘して訂正すること。"
        )
        self._notes_box = scrolledtext.ScrolledText(f, font=FONT_NORMAL, height=12, relief="solid", wrap="word")
        self._notes_box.grid(row=7, column=1, sticky="nsew", padx=12, pady=6)
        
        notes_val = draft.get("notes", "")
        if notes_val:
            self._notes_box.insert("end", notes_val)
            self._notes_box.configure(fg="black")
        else:
            self._notes_box.insert("end", notes_hint)
            self._notes_box.configure(fg="gray")
            
        def _notes_focus_in(e):
            if self._notes_box.cget("fg") == "gray": self._notes_box.delete("1.0", "end"); self._notes_box.configure(fg="black")
        def _notes_focus_out(e):
            if not self._notes_box.get("1.0", "end").strip(): self._notes_box.insert("end", notes_hint); self._notes_box.configure(fg="gray")
        self._notes_box.bind("<FocusIn>",  _notes_focus_in)
        self._notes_box.bind("<FocusOut>", _notes_focus_out)

        tk.Label(f, text="参考資料 (RAG / コーパス) ※任意", font=FONT_NORMAL, bg=BG).grid(row=8, column=0, sticky="nw", pady=6)
        self._rag_store_var = tk.StringVar(value=draft.get("rag_store_name", ""))
        self._rag_display_var = tk.StringVar()
        stores = ai_engine.get_file_search_stores()
        self._store_options = {"使用しない": ""}
        for s in stores: self._store_options[s["display"]] = s["name"]
        rag_keys = list(self._store_options.keys())
        
        current_display = rag_keys[0] if rag_keys else ""
        for disp, name in self._store_options.items():
            if name == self._rag_store_var.get():
                current_display = disp
                break
        self._rag_display_var.set(current_display)
        
        rag_dropdown = tk.OptionMenu(f, self._rag_display_var, *rag_keys, command=lambda choice: self._rag_store_var.set(self._store_options[choice]))
        rag_dropdown.config(font=FONT_NORMAL, width=35)
        rag_dropdown.grid(row=8, column=1, sticky="w", padx=12, pady=6)

        tk.Label(f, text="RAG資料の性質", font=FONT_NORMAL, bg=BG).grid(row=9, column=0, sticky="nw", pady=6)
        self._rag_type_var = tk.StringVar(value=draft.get("rag_type", "systematic"))
        rag_type_frame = tk.Frame(f, bg=BG)
        rag_type_frame.grid(row=9, column=1, sticky="w", padx=12, pady=6)
        tk.Radiobutton(rag_type_frame, text="教科書・参考書モード（目次と内容を忠実に再現）", variable=self._rag_type_var, value="systematic", bg=BG).pack(anchor="w")
        tk.Radiobutton(rag_type_frame, text="問題集・プリントモード（AIが構成を整理し、足りない知識を補足）", variable=self._rag_type_var, value="fragmented", bg=BG).pack(anchor="w")

        tk.Label(f, text="🌐 WEB検索", font=FONT_NORMAL, bg=BG).grid(row=10, column=0, sticky="w", pady=6)
        self._use_web_search_var = tk.BooleanVar(value=draft.get("use_web_search", False))
        web_cb_frame = tk.Frame(f, bg=BG)
        web_cb_frame.grid(row=10, column=1, sticky="w", padx=12, pady=6)
        tk.Checkbutton(
            web_cb_frame,
            text="最新WEB情報を検索反映（法改正対応等）",
            variable=self._use_web_search_var,
            font=FONT_NORMAL, bg=BG
        ).pack(side="left")
        tk.Label(web_cb_frame, text="  ※「留意事項」に検索して欲しい内容を具体的に記載してください", font=FONT_SMALL, bg=BG, fg="#888").pack(side="left")

        def on_create():
            subj  = self._entries[0].get().strip()
            level = self._entries[1].get().strip()
            hours = self._entries[2].get().strip()
            explain_level = self._entries[3].get().strip()
            gemini_model  = self._model_entry.get().strip() or ai_engine.get_model()
            emb_model     = self._emb_entry.get().strip() or ai_engine.get_embedding_model()
            notes_raw = self._notes_box.get("1.0", "end").strip()
            notes = "" if self._notes_box.cget("fg") == "gray" else notes_raw
            rag_store_name = self._rag_store_var.get()
            rag_type = self._rag_type_var.get()
            use_web = self._use_web_search_var.get()
            
            self._draft_subject_data = {
                "subj": subj, "level": level, "hours": hours,
                "explain_level": explain_level, "gemini_model": gemini_model,
                "embedding_model": emb_model,
                "notes": notes, "rag_store_name": rag_store_name,
                "rag_type": rag_type, "use_web_search": use_web
            }
            
            if not subj or not level or not explain_level:
                messagebox.showwarning("入力エラー", "すべての必須項目を入力してください。")
                return

            if subj in database.list_subjects():
                if not messagebox.askyesno(
                    "確認",
                    f"科目「{subj}」は既に存在します。\n\n学習計画を作り直しますか？\n⚠️ 蓄積された小問・成績データもすべてリセットされます。"
                ):
                    return

            ai_engine.set_model(gemini_model)
            ai_engine.set_embedding_model(emb_model)

            dlg = tk.Toplevel(self)
            dlg.title("学習計画の作成中")
            dlg.attributes("-topmost", True)
            dlg.grab_set()  # 背面の操作をブロックし、ボタン連打を防ぐ
            
            sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
            dlg.geometry(f"400x150+{(sw-400)//2}+{(sh-150)//2}")
            dlg.configure(bg=BG)
            
            tk.Label(dlg, text="⏳ Geminiが学習計画を作成中…\nしばらくお待ちください", font=FONT_TITLE, bg=BG, fg="red").pack(expand=True)
            dlg.update()
            
            def task():
                hours_line = f"- 目標到達時間: {hours}" if hours else "- 目標到達時間: あなたの知見に基づいて、このレベルの習得に適切な時間を設定してください。"
                hours_json = hours if hours else "（Geminiが適切な値を設定）"

                if rag_store_name:
                    if rag_type == "systematic":
                        rag_instruction = "【最重要指令】\n必ず提供された参考資料(RAG)のテキスト全体を検索・参照し、実際のテキストに記載されている「目次」「章立て」を完全に再現してください。資料に存在しない章を勝手に想像して追加することは厳禁です。"
                    else:
                        rag_instruction = "【構成指示】\n提供された参考資料(RAG)は断片的な知識の集合です。資料の内容を網羅しつつ、あなたが持つ一般的な教育の知見に基づいて、最も学習しやすい論理的で体系的な章立て（目次）を構築してください。"
                else:
                    rag_instruction = "あなたの知見に基づき、網羅的な章立てを作成してください。"

                prompt = f"""あなたは優秀な学習コーチです。以下の条件に基づき、最も効率的で体系的な学習計画をJSON形式で作成してください。

【構成指針】
{rag_instruction}

【基本情報】
- 分野名: {subj}
- 目標到達レベル: {level}
{hours_line}

【出力ルール】
- レベルを落とさず、かつ初心者にも分かりやすい論理的な順序で章立てを行ってください。
- 各章(plan)には、その章を習得するための複数の節(sub_topics)を含めてください。
- `estimated_minutes` は、そのレベルに到達するために必要な現実的な学習時間を割り当ててください。

【出力形式】
※必ず以下のJSON構造のみを出力してください。余計な解説文や挨拶は一切不要です。
{{
  "subject": "{subj}",
  "goal_level": "{level}",
  "total_hours": "{hours_json}",
  "plan": [
    {{
      "id": "1",
      "name": "章の名前",
      "estimated_minutes": 120,
      "sub_topics": [
        {{ "id": "1-1", "name": "節の名前", "estimated_minutes": 60 }}
      ]
    }}
  ]
}}"""
                try:
                    raw = ai_engine.gemini_once_json(prompt, rag_store_name=rag_store_name, use_web_search=use_web)
                    plan_data = json.loads(raw)
                    plan_data["notes"] = notes
                    plan_data["rag_store_name"] = rag_store_name
                    plan_data["rag_type"] = rag_type
                    plan_data["explain_level"] = explain_level
                    plan_data["gemini_model"]  = gemini_model
                    plan_data["use_web_search"] = use_web

                    self.after(0, dlg.destroy)
                    self.after(0, lambda: self._show_plan_confirm_screen(subj, plan_data))
                except Exception as e:
                    self.after(0, dlg.destroy)
                    self.after(0, lambda err=e: self._show_friendly_error(err, "学習計画の生成エラー"))
                    
            threading.Thread(target=task, daemon=True).start()

        btn_row = tk.Frame(f, bg=BG)
        btn_row.grid(row=11, column=0, columnspan=2, pady=20)
        styled_btn(btn_row, "学習計画を作成 →", on_create, width=22).pack(side="left", padx=8)
        styled_btn(btn_row, "← 戻る", lambda: self._show_start_dialog(), width=12, bg="#888").pack(side="left", padx=8)

    def _show_plan_confirm_screen(self, subj, plan_data):
        self._clear()
        self._pending_plan = plan_data
        f = tk.Frame(self, bg=BG, padx=20, pady=14)
        f.pack(fill="both", expand=True)
        section_label(f, f"📋 学習計画の確認：{subj}").pack(anchor="w", pady=(0,4))
        rag_info = "RAG: 使用" if plan_data.get('rag_store_name') else "RAG: 未使用"

        tk.Label(f, text=f"目標レベル: {plan_data.get('goal_level','')} ／ 目標時間: {plan_data.get('total_hours','')} ／ 説明レベル: {plan_data.get('explain_level','')} ／ {rag_info}", font=FONT_SMALL, bg=BG, fg="gray").pack(anchor="w", pady=(0,6))

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack(side="bottom", pady=10)
        def on_confirm():
            confirmed = self._pending_plan
            confirmed["progress"], confirmed["weaknesses"] = {}, {}
            database.save_cfg(subj, confirmed)
            self.current_subject, self.cfg_data = subj, confirmed

            database.reset_subject_learning_data(subj)
            try:
                media_dir = database.get_media_dir(subj)
                for fname in os.listdir(media_dir):
                    if fname.startswith("podcast_") and (fname.endswith(".html") or fname.endswith(".mp3")):
                        try:
                            os.remove(os.path.join(media_dir, fname))
                        except Exception:
                            pass
            except Exception:
                pass

            messagebox.showinfo("保存完了", f"「{subj}」の学習計画を保存しました。")
            self._show_menu_screen()
            
        styled_btn(btn_f, "✅ 確定して保存", on_confirm, width=20).pack(side="left", padx=10)
        styled_btn(btn_f, "← 戻る", lambda: self._show_new_subject_screen(), width=12, bg="#888").pack(side="left", padx=10)

        grid_outer = tk.Frame(f, bg=BG, relief="solid", bd=1)
        grid_outer.pack(side="top", fill="both", expand=True)
        cv  = tk.Canvas(grid_outer, bg=BG, highlightthickness=0)
        vsb = tk.Scrollbar(grid_outer, orient="vertical",   command=cv.yview)
        hsb = tk.Scrollbar(grid_outer, orient="horizontal", command=cv.xview)
        inner = tk.Frame(cv, bg=BG)
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=inner, anchor="nw")
        cv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        hsb.pack(side="bottom", fill="x")
        vsb.pack(side="right",  fill="y")
        cv.pack(side="left", fill="both", expand=True)

        col_w = [6, 8, 38, 10]
        for ci, (h, w) in enumerate(zip(["No.", "所要(分)", "分野名 / 細々分野名", "備考"], col_w)):
            tk.Label(inner, text=h, font=FONT_BOLD, bg="#dce8f5", width=w, relief="groove", anchor="center").grid(row=0, column=ci, sticky="nsew", padx=1, pady=1)

        ri = 1
        for top in plan_data.get("plan", []):
            subs = top.get("sub_topics", [])
            if subs:
                for ci, (val, w, bold, bg_) in enumerate(zip([top["id"], top.get("estimated_minutes",""), f"▼ {top['name']}", ""], col_w, [True,True,True,False], ["#eef4fb"]*4)):
                    tk.Label(inner, text=val, font=FONT_BOLD if bold else FONT_NORMAL, bg=bg_, width=w, relief="groove", anchor="w" if ci==2 else "center").grid(row=ri, column=ci, sticky="nsew", padx=1, pady=1)
                ri += 1
                for st in subs:
                    for ci, (val, w) in enumerate(zip([f"  {st['id']}", st.get("estimated_minutes",""), f"   {st['name']}", ""], col_w)):
                        tk.Label(inner, text=val, font=FONT_NORMAL, bg="white", width=w, relief="groove", anchor="w" if ci==2 else "center").grid(row=ri, column=ci, sticky="nsew", padx=1, pady=1)
                    ri += 1
            else:
                for ci, (val, w) in enumerate(zip([top["id"], top.get("estimated_minutes",""), top["name"], ""], col_w)):
                    tk.Label(inner, text=val, font=FONT_NORMAL, bg="white", width=w, relief="groove", anchor="w" if ci==2 else "center").grid(row=ri, column=ci, sticky="nsew", padx=1, pady=1)
                ri += 1

    def _show_anki_import_screen(self):
        self._clear()
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)
        f = self._create_scrollable_container(outer)
        f.configure(padx=30, pady=20)

        section_label(f, "🃏 Ankiパッケージ (.apkg) からインポート").grid(row=0, column=0, columnspan=2, pady=(0, 20), sticky="w")
        f.columnconfigure(1, weight=1)

        tk.Label(f, text="📁 .apkgファイル：", font=FONT_BOLD, bg=BG).grid(row=1, column=0, sticky="e", padx=(0, 8), pady=6)
        file_var = tk.StringVar()
        file_frame = tk.Frame(f, bg=BG)
        file_frame.grid(row=1, column=1, sticky="ew", padx=12, pady=6)
        file_entry = tk.Entry(file_frame, textvariable=file_var, font=FONT_NORMAL, width=38, relief="solid", state="readonly")
        file_entry.pack(side="left", expand=True, fill="x")

        def _browse():
            p = filedialog.askopenfilename(title="Ankiパッケージを選択", filetypes=[("Anki Package", "*.apkg"), ("All Files", "*.*")])
            if p:
                file_var.set(p)
                if not subj_var.get():
                    subj_var.set(os.path.splitext(os.path.basename(p))[0])

        styled_btn(file_frame, "参照...", _browse, width=8).pack(side="left", padx=(6, 0))

        tk.Label(f, text="📚 科目名：", font=FONT_BOLD, bg=BG).grid(row=2, column=0, sticky="e", padx=(0, 8), pady=6)
        subj_var = tk.StringVar()
        subj_entry = tk.Entry(f, textvariable=subj_var, font=FONT_NORMAL, width=38, relief="solid")
        subj_entry.grid(row=2, column=1, sticky="ew", padx=12, pady=6)
        tk.Label(f, text="  ※ DBファイル名になります（英数字・日本語可）", font=FONT_SMALL, bg=BG, fg="#888").grid(row=3, column=1, sticky="w", padx=12)

        ai_syllabus_var = tk.BooleanVar(value=True)
        tk.Label(f, text="🧠 シラバス生成：", font=FONT_BOLD, bg=BG).grid(row=4, column=0, sticky="e", padx=(0, 8), pady=6)
        cb_frame = tk.Frame(f, bg=BG)
        cb_frame.grid(row=4, column=1, sticky="w", padx=12, pady=6)
        tk.Checkbutton(cb_frame, text="Gemini AIでシラバスを自動生成する", variable=ai_syllabus_var, font=FONT_NORMAL, bg=BG).pack(side="left")
        tk.Label(cb_frame, text="  ※ OFF にするとAnki内のカテゴリ情報から簡易シラバスを作成（APIなし・高速）", font=FONT_SMALL, bg=BG, fg="#888").pack(side="left")

        tk.Label(f, text="📋 進捗：", font=FONT_BOLD, bg=BG).grid(row=5, column=0, sticky="ne", padx=(0, 8), pady=6)
        log_text = scrolledtext.ScrolledText(f, font=FONT_SMALL, width=55, height=10, state="disabled", relief="solid", wrap="word")
        log_text.grid(row=5, column=1, sticky="ew", padx=12, pady=6)

        _import_screen_id = self._screen_id

        def _log(msg: str):
            def _do():
                if self._screen_id != _import_screen_id: return
                try:
                    log_text.configure(state="normal")
                    log_text.insert("end", msg + "\n")
                    log_text.see("end")
                    log_text.configure(state="disabled")
                except Exception: pass
            self.after(0, _do)

        import_btn = [None]

        def _start_import():
            apkg_path = file_var.get().strip()
            subject   = subj_var.get().strip()

            if not apkg_path: return messagebox.showerror("エラー", ".apkgファイルを選択してください。")
            if not subject:   return messagebox.showerror("エラー", "科目名を入力してください。")
            if not os.path.exists(apkg_path): return messagebox.showerror("エラー", "指定されたファイルが見つかりません。")

            if database.list_subjects() and subject in database.list_subjects():
                if not messagebox.askyesno("確認", f"科目「{subject}」は既に存在します。\n問題を追加しますか？（学習計画は上書きされます）"):
                    return

            import_btn[0].configure(state="disabled")

            def _run():
                try:
                    from anki_importer import AnkiImporter
                    importer = AnkiImporter(apkg_path, subject)
                    result   = importer.run(progress_cb=_log, use_ai_syllabus=ai_syllabus_var.get())

                    if result["success"]:
                        def _on_success():
                            import_btn[0].configure(state="normal")
                            self.current_subject = subject
                            self.cfg_data = database.load_cfg(subject)
                            ai_engine.set_model(self.cfg_data.get("gemini_model", ai_engine.get_model()))
                            self._show_anki_plan_editor(result["plan"])
                        self.after(0, _on_success)
                    else:
                        def _on_fail():
                            import_btn[0].configure(state="normal")
                            messagebox.showerror("インポート失敗", result["message"])
                        self.after(0, _on_fail)
                except ImportError:
                    self.after(0, lambda: messagebox.showerror("モジュール未インストール", "anki_importer.py が見つかりません。"))

            threading.Thread(target=_run, daemon=True).start()

        btn_f = tk.Frame(f, bg=BG)
        btn_f.grid(row=6, column=0, columnspan=2, pady=16)

        btn = styled_btn(btn_f, "🚀 インポート開始", _start_import, width=18)
        btn.pack(side="left", padx=10)
        import_btn[0] = btn
        styled_btn(btn_f, "← 戻る", lambda: self._show_start_dialog(), width=12, bg="#888").pack(side="left", padx=10)

    def _show_anki_plan_editor(self, plan: list):
        self._clear()
        subj = self.current_subject

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)
        f = self._create_scrollable_container(outer)
        f.configure(padx=30, pady=20)

        section_label(f, f"📋 章の確認・編集：{subj}").pack(anchor="w", pady=(0, 4))
        tk.Label(f, text="AIが生成した章の名前を確認してください。変更したい場合は直接書き直せます。", font=FONT_SMALL, bg=BG, fg="#555").pack(anchor="w", pady=(0, 12))

        table_frame = tk.Frame(f, bg=BG, relief="solid", bd=1)
        table_frame.pack(fill="both", expand=True, pady=(0, 12))

        hdr = tk.Frame(table_frame, bg="#dce8f5")
        hdr.pack(fill="x")
        tk.Label(hdr, text="ID", font=FONT_BOLD, bg="#dce8f5", width=18, anchor="w", padx=6).pack(side="left")
        tk.Label(hdr, text="章・小項目名（編集可）", font=FONT_BOLD, bg="#dce8f5", anchor="w", padx=6).pack(side="left", fill="x", expand=True)

        entries = []

        def _add_row(level: int, label_id: str, name: str, ch_i: int, sub_i=None):
            row = tk.Frame(table_frame, bg="white" if level == 1 else "#f5f8ff")
            row.pack(fill="x", pady=1)
            indent = 0 if level == 0 else 20
            tk.Label(row, text=label_id, font=FONT_SMALL, bg=row["bg"], width=18, anchor="w", padx=6 + indent).pack(side="left")
            var = tk.StringVar(value=name)
            e = tk.Entry(row, textvariable=var, font=FONT_NORMAL, relief="flat", bg=row["bg"])
            e.pack(side="left", fill="x", expand=True, padx=(0, 6), pady=2)
            entries.append((ch_i, sub_i, var))

        for ch_i, chapter in enumerate(plan):
            _add_row(0, chapter.get("id", ""), chapter.get("name", ""), ch_i)
            for sub_i, sub in enumerate(chapter.get("sub_topics") or []):
                _add_row(1, f"  {sub.get('id','')}", sub.get("name", ""), ch_i, sub_i)

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack(pady=12)

        def _save_and_go():
            new_plan = [dict(ch) for ch in plan]
            for ch_i, sub_i, var in entries:
                new_name = var.get().strip()
                if not new_name: continue
                if sub_i is None:
                    new_plan[ch_i]["name"] = new_name
                else:
                    subs = new_plan[ch_i].get("sub_topics") or []
                    if sub_i < len(subs):
                        subs[sub_i]["name"] = new_name
                    new_plan[ch_i]["sub_topics"] = subs

            database.save_cfg(subj, {"plan": new_plan, "anki_imported": True})
            self.cfg_data = database.load_cfg(subj)
            self._show_menu_screen()

        def _skip():
            database.save_cfg(subj, {"anki_imported": True})
            self.cfg_data = database.load_cfg(subj)
            self._show_menu_screen()

        styled_btn(btn_f, "✅ 保存してメニューへ", _save_and_go, width=20).pack(side="left", padx=8)
        styled_btn(btn_f, "→ スキップ（編集しない）", _skip, width=20, bg="#888").pack(side="left", padx=8)

    def _show_anki_reclassify(self):
        self._clear()
        subj = self.current_subject
        plan = self.cfg_data.get("plan", [])

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)
        f = self._create_scrollable_container(outer)
        f.configure(padx=30, pady=20)

        section_label(f, f"🔄 AIで問題を再分類：{subj}").pack(anchor="w", pady=(0, 4))
        tk.Label(f, text="キーワードマッチングより精度の高いAI分類で全問題を再振り分けします。\n問題数が多い場合は時間がかかります（APIの利用料が発生します）。", font=FONT_SMALL, bg=BG, fg="#555").pack(anchor="w", pady=(0, 12))

        ctrl_frame = tk.Frame(f, bg=BG)
        ctrl_frame.pack(anchor="w", pady=(0, 8))
        tk.Label(ctrl_frame, text="1回あたりの処理件数：", font=FONT_NORMAL, bg=BG).pack(side="left")
        batch_var = tk.StringVar(value="20")
        tk.Entry(ctrl_frame, textvariable=batch_var, font=FONT_NORMAL, width=6, justify="center", relief="solid").pack(side="left", padx=4)
        tk.Label(ctrl_frame, text="件　（多いほど速いが API の負荷が上がります）", font=FONT_SMALL, bg=BG, fg="#888").pack(side="left")

        log_text = scrolledtext.ScrolledText(f, font=FONT_SMALL, width=60, height=12, state="disabled", relief="solid", wrap="word")
        log_text.pack(fill="both", expand=True, pady=(0, 10))

        _reclassify_screen_id = self._screen_id

        def _log(msg: str):
            def _do():
                if self._screen_id != _reclassify_screen_id: return
                try:
                    log_text.configure(state="normal")
                    log_text.insert("end", msg + "\n")
                    log_text.see("end")
                    log_text.configure(state="disabled")
                except Exception: pass
            self.after(0, _do)

        run_btn = [None]

        def _start():
            try:
                batch_size = int(batch_var.get().strip())
                if batch_size < 1: raise ValueError
            except ValueError:
                return messagebox.showerror("エラー", "件数は1以上の整数を入力してください。")

            run_btn[0].configure(state="disabled")

            def _task():
                try:
                    from anki_importer import batch_classify_with_ai
                    batch_classify_with_ai(subject=subj, plan=plan, batch_size=batch_size, delay_sec=2.0, progress_cb=_log)
                    self.after(0, lambda: [run_btn[0].configure(state="normal"), messagebox.showinfo("完了", "AIによる再分類が完了しました。")])
                except Exception as e:
                    self.after(0, lambda: [run_btn[0].configure(state="normal"), messagebox.showerror("エラー", str(e))])

            threading.Thread(target=_task, daemon=True).start()

        def _reorganize():
            if not messagebox.askyesno("確認", "全ての画像要約データを基に、学習計画（章立て）をゼロから再構築します。\n既存の「未分類」などの分け方は破棄されますが、画像や問題は消えません。\n\n実行しますか？"):
                return
            
            run_btn[0].configure(state="disabled")
            reorg_btn.configure(state="disabled")

            def _task():
                try:
                    from anki_importer import reorganize_syllabus_from_summaries
                    res = reorganize_syllabus_from_summaries(subject=subj, progress_cb=_log)
                    if res["success"]:
                        self.after(0, lambda: messagebox.showinfo("完了", "シラバスの再構成が完了しました。メニューに戻ります。"))
                        self.after(0, self._show_menu_screen)
                    else:
                        self.after(0, lambda m=res["message"]: messagebox.showerror("エラー", m))
                except Exception as e:
                    self.after(0, lambda err=e: _log(f"❌ システムエラー: {err}"))
                finally:
                    self.after(0, lambda: [run_btn[0].configure(state="normal"), reorg_btn.configure(state="normal")])
            
            threading.Thread(target=_task, daemon=True).start()

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack(pady=6)
        reorg_btn = styled_btn(btn_f, "🤖 AIで章立てから再構成する (おすすめ)", _reorganize, width=32, bg="#6a1b9a")
        reorg_btn.pack(side="left", padx=8)
        run_btn[0] = styled_btn(btn_f, "🔄 既存の章へAIで再分類", _start, width=22, bg="#00796b")
        run_btn[0].pack(side="left", padx=8)
        styled_btn(btn_f, "← メニューへ戻る", self._show_menu_screen, width=16, bg="#888").pack(side="left", padx=8)

    def _import_folder_images(self):
        """指定フォルダ内の画像をアプリに取り込み、AIで解析してメディアフォルダに登録する"""
        subj = self.current_subject
        folder_path = filedialog.askdirectory(title="図解（画像ファイル）が入っているフォルダを選択")
        if not folder_path: return

        dlg = tk.Toplevel(self)
        dlg.title("画像取り込み・解析中")
        dlg.geometry("450x150")
        dlg.attributes("-topmost", True)
        tk.Label(dlg, text="📷 画像を取り込み、AIで内容を解析しています...\n（枚数が多い場合は時間がかかります）", font=FONT_NORMAL, bg=BG).pack(pady=10)
        msg_var = tk.StringVar(value="準備中...")
        tk.Label(dlg, textvariable=msg_var, font=FONT_SMALL, bg=BG, fg="#1565c0").pack(pady=5)
        dlg.update()

        def task():
            try:
                import shutil
                media_dir = database.get_media_dir(subj)
                valid_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
                image_files = [fname for fname in os.listdir(folder_path) if os.path.splitext(fname)[1].lower() in valid_exts]
                        
                if not image_files:
                    self.after(0, dlg.destroy)
                    self.after(0, lambda: messagebox.showinfo("情報", "選択したフォルダに画像ファイルが見つかりませんでした。"))
                    return

                copied_count, analyzed_count, skipped_count = 0, 0, 0
                existing_summaries = database.get_all_media_summaries(subj)
                is_aborted = False # ← 追加：中断フラグ

                for fname in image_files:
                    src_path = os.path.join(folder_path, fname)
                    dst_path = os.path.join(media_dir, fname)
                    
                    if fname in existing_summaries:
                        if not os.path.exists(dst_path):
                            shutil.copy2(src_path, dst_path)
                        skipped_count += 1
                        continue

                    shutil.copy2(src_path, dst_path)
                    copied_count += 1
                    self.after(0, lambda m=f"AIが画像内容を学習中... {fname}": msg_var.set(m))
                    
                    summary = ""
                    for attempt in range(3):
                        summary = ai_engine.analyze_image_for_summary(dst_path)
                        if summary: break
                        
                        wait_sec = 20 * (attempt + 1)
                        self.after(0, lambda m=f"⚠️ 混雑中... {wait_sec}秒待機して再試行します ({attempt+1}/3)": msg_var.set(m))
                        time.sleep(wait_sec)

                    if summary:
                        # summary からベクトル（Embedding）を生成
                        self.after(0, lambda m=f"ベクトルデータを生成中... {fname}": msg_var.set(m))
                        emb = ai_engine.get_embedding(summary)
                        
                        database.save_media_summary(subj, fname, summary, embedding=emb)
                        existing_summaries[fname] = summary
                        analyzed_count += 1
                        time.sleep(4)  # 無料APIのレート制限（15回/分）対策の待機時間
                    else:
                        # ← 追加：中断フラグを立ててループを抜ける
                        is_aborted = True
                        self.after(0, lambda: messagebox.showwarning("API制限", f"「{fname}」の解析時にAPI制限に達したため中断しました。\n\n時間をおいてから再度同じフォルダを取り込むと、この続きから再開できます。"))
                        break

                self.after(0, dlg.destroy)
                
                # ← 追加：中断された場合は、完了ポップアップを出さずに終了する
                if is_aborted:
                    return
                
                msg = ""
                if analyzed_count > 0: msg += f"新たに {analyzed_count} 枚の図解をAIに学習させました！\n"
                if skipped_count > 0:  msg += f"（既に学習済みの {skipped_count} 枚はスキップしました）\n"
                if analyzed_count == 0 and skipped_count > 0:
                    msg = f"すべての画像（{skipped_count}枚）は既に学習済みです。\n新しく追加された画像はありませんでした。"
                elif analyzed_count > 0:
                    msg += "\nこれらは今後、問題や解説を作成する際の図として自動的に活用されます。"
                    
                self.after(0, lambda: messagebox.showinfo("取込処理の終了", msg))

            except Exception as e:
                self.after(0, dlg.destroy)
                self.after(0, lambda err=e: self._show_friendly_error(err, "画像処理エラー"))

        threading.Thread(target=task, daemon=True).start()

    def _show_subject_list_screen(self, subjects):
        self._clear()
        f = tk.Frame(self, bg=BG, padx=30, pady=20)
        f.pack(fill="both", expand=True)
        section_label(f, "📂 学習する科目を選択").pack(anchor="w", pady=(0,10))
        
        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack(side="bottom", pady=16)
        
        lb_frame = tk.Frame(f, bg=BG)
        lb_frame.pack(side="top", fill="both", expand=True)
        scrollbar = tk.Scrollbar(lb_frame)
        scrollbar.pack(side="right", fill="y")
        lb = tk.Listbox(lb_frame, font=FONT_NORMAL, yscrollcommand=scrollbar.set, height=15, selectmode="single", relief="solid")
        for s in subjects: lb.insert("end", s)
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=lb.yview)

        def on_select():
            sel = lb.curselection()
            if not sel: return messagebox.showwarning("選択エラー", "科目を選択してください。")
            self.current_subject = subjects[sel[0]]
            self.cfg_data = database.load_cfg(self.current_subject)
            ai_engine.set_model(self.cfg_data.get("gemini_model", ai_engine.get_model()))
            ai_engine.set_embedding_model(self.cfg_data.get("embedding_model", ai_engine.get_embedding_model()))
            total_q  = database.count_all_questions(self.current_subject)
            today_qs = database.get_review_questions(self.current_subject)
            if total_q == 0: self._show_menu_screen()
            elif not today_qs:
                messagebox.showinfo("復習テスト", f"蓄積問題数: {total_q}問\n\n本日復習すべき問題はありません。\n（全問が定着済みです）\n\n学習メニューに進みます。")
                self._show_menu_screen()
            else: self._show_review_test_screen()
            
        styled_btn(btn_f, "▶️ この科目で学習開始", on_select, width=22).pack(side="left", padx=10)
        styled_btn(btn_f, "← 戻る", lambda: self._show_start_dialog(), width=12, bg="#888").pack(side="left", padx=10)

    def _build_progress_table(self, parent_frame, canvas_height=300):
        cfg  = self.cfg_data
        plan = cfg.get("plan", [])
        prog = cfg.get("progress", {})

        plan_outer = tk.LabelFrame(parent_frame, text="学習計画・進捗状況", font=FONT_BOLD, bg=BG, padx=4, pady=4)
        plan_outer.pack(side="top", fill="both", expand=True, pady=(0,4))

        p_cv  = tk.Canvas(plan_outer, bg=BG, highlightthickness=0, height=canvas_height)
        p_vsb = tk.Scrollbar(plan_outer, orient="vertical", command=p_cv.yview)
        p_inner = tk.Frame(p_cv, bg=BG)
        p_inner.bind("<Configure>", lambda e: p_cv.configure(scrollregion=p_cv.bbox("all")))
        p_cv.create_window((0,0), window=p_inner, anchor="nw")
        p_cv.configure(yscrollcommand=p_vsb.set)
        p_vsb.pack(side="right", fill="y")
        p_cv.pack(side="left",  fill="both", expand=True)

        def _on_mousewheel(event): p_cv.yview_scroll(int(-1*(event.delta/120)), "units")
        p_cv.bind_all("<MouseWheel>", _on_mousewheel)
        self._current_table_canvas = p_cv 

        FMT_ABBR = {
            "正誤問題": "正誤", "5肢択一問題": "択一", "穴埋め問題": "穴埋",
            "記述式問題": "記述", "論証問題": "論証",
            "理系用計算問題（途中式あり）": "計算", "理系用証明・導出問題": "証明",
        }
        topic_settings = cfg.get("topic_settings", {})

        headers = ["ID", "分野名", "進捗 ℹ️", "理解度 ℹ️"]
        for ci, h in enumerate(headers):
            lbl = tk.Label(p_inner, text=h, font=FONT_BOLD, bg="#dce8f5", width=[10,42,10,12][ci], relief="groove")
            lbl.grid(row=0, column=ci, sticky="ew")
            
            if h == "進捗 ℹ️":
                lbl.configure(cursor="hand2", fg="#1565c0")
                lbl.bind("<Button-1>", lambda e: messagebox.showinfo(
                    "進捗について",
                    "「✅ 完了」は、その分野の確認テストを受験し、採点結果画面を表示したタイミングでマークされます。\n"
                    "（テスト未受験の場合は「・ 未学習」となります）"
                ))
            elif h == "理解度 ℹ️":
                lbl.configure(cursor="hand2", fg="#1565c0")
                lbl.bind("<Button-1>", lambda e: messagebox.showinfo(
                    "理解度の表示について",
                    "ここの数値は「現在その分野で選択している出題形式」における成績のみを集計しています。\n\n"
                    "例：「記述式問題」を選択している場合は、記述式問題の（直近正解数 / 全問題数）を表示します。"
                ))

        row_idx = 1
        topic_list = []

        for top in plan:
            subs = top.get("sub_topics", [])
            if subs:
                tk.Label(p_inner, text=top["id"], font=FONT_NORMAL, bg=BG, width=10, relief="groove").grid(row=row_idx, column=0, sticky="ew")
                tk.Label(p_inner, text=f"【{top['name']}】", font=FONT_BOLD, bg="#eef4fb", width=42, anchor="w", relief="groove").grid(row=row_idx, column=1, sticky="ew")
                tk.Label(p_inner, text="", bg="#eef4fb", width=10, relief="groove").grid(row=row_idx, column=2, sticky="ew")
                tk.Label(p_inner, text="", bg="#eef4fb", width=12, relief="groove").grid(row=row_idx, column=3, sticky="ew")
                row_idx += 1
                for st in subs:
                    tid   = st["id"]
                    p     = prog.get(tid, {})
                    done  = "✅ 完了" if p.get("done") else "・ 未学習"
                    fmt        = topic_settings.get(tid)
                    stats      = database.get_topic_mastery_stats(self.current_subject, tid, question_format=fmt)
                    fmt_abbr   = FMT_ABBR.get(fmt, "") if fmt else ""
                    score = f"{stats['correct']}/{stats['total']}[{fmt_abbr}]" if fmt_abbr else f"{stats['correct']} / {stats['total']}" if stats["total"] > 0 else f"-/-[{fmt_abbr}]" if fmt_abbr else "- / -"

                    tk.Label(p_inner, text=f"  {tid}", font=FONT_NORMAL, bg=BG, width=10, relief="groove").grid(row=row_idx, column=0, sticky="ew")
                    tk.Label(p_inner, text=f"  {st['name']} ({st.get('estimated_minutes',60)}分)", font=FONT_NORMAL, bg=BG, width=42, anchor="w", relief="groove").grid(row=row_idx, column=1, sticky="ew")
                    tk.Label(p_inner, text=done, font=FONT_NORMAL, bg=BG, width=10, relief="groove").grid(row=row_idx, column=2, sticky="ew")
                    
                    bg_color = BG
                    if p.get("done") and stats["total"] > 0:
                        rate = stats["correct"] / stats["total"]
                        bg_color = "#ffcccc" if rate < 0.2 else "#ffe0cc" if rate < 0.4 else "#ffffcc" if rate < 0.6 else "#e0ffcc" if rate < 0.8 else "#ccffcc" if rate < 1.0 else "#cce5ff"
                    tk.Label(p_inner, text=score, font=FONT_NORMAL, bg=bg_color, width=12, relief="groove").grid(row=row_idx, column=3, sticky="ew")
                    row_idx += 1
                    topic_list.append((f"{tid}: {st['name']}", tid))
            else:
                tid   = top["id"]
                p     = prog.get(tid, {})
                done  = "✅ 完了" if p.get("done") else "・ 未学習"
                fmt        = topic_settings.get(tid)
                stats      = database.get_topic_mastery_stats(self.current_subject, tid, question_format=fmt)
                fmt_abbr   = FMT_ABBR.get(fmt, "") if fmt else ""
                score = f"{stats['correct']}/{stats['total']}[{fmt_abbr}]" if fmt_abbr else f"{stats['correct']} / {stats['total']}" if stats["total"] > 0 else f"-/-[{fmt_abbr}]" if fmt_abbr else "- / -"

                tk.Label(p_inner, text=tid, font=FONT_NORMAL, bg=BG, width=10, relief="groove").grid(row=row_idx, column=0, sticky="ew")
                tk.Label(p_inner, text=f"{top['name']} ({top.get('estimated_minutes',60)}分)", font=FONT_NORMAL, bg=BG, width=42, anchor="w", relief="groove").grid(row=row_idx, column=1, sticky="ew")
                tk.Label(p_inner, text=done, font=FONT_NORMAL, bg=BG, width=10, relief="groove").grid(row=row_idx, column=2, sticky="ew")
                
                bg_color = BG
                if p.get("done") and stats["total"] > 0:
                    rate = stats["correct"] / stats["total"]
                    bg_color = "#ffcccc" if rate < 0.2 else "#ffe0cc" if rate < 0.4 else "#ffffcc" if rate < 0.6 else "#e0ffcc" if rate < 0.8 else "#ccffcc" if rate < 1.0 else "#cce5ff"
                tk.Label(p_inner, text=score, font=FONT_NORMAL, bg=bg_color, width=12, relief="groove").grid(row=row_idx, column=3, sticky="ew")
                row_idx += 1
                topic_list.append((f"{top['name']}", tid))
        return topic_list, prog

    def _show_menu_screen(self):
        self._clear()
        cfg   = self.cfg_data
        subj  = self.current_subject

        f = tk.Frame(self, bg=BG, padx=30, pady=16)
        f.pack(fill="both", expand=True)

        section_label(f, f"📚 {subj}　学習メニュー").pack(anchor="w")
        tk.Label(f, text=f"目標レベル: {cfg.get('goal_level','')} ／ 目標時間: {cfg.get('total_hours','')} ／ 説明レベル: {cfg.get('explain_level','')}", font=FONT_SMALL, bg=BG, fg="gray").pack(anchor="w", pady=(2,0))

        model_row = tk.Frame(f, bg=BG)
        model_row.pack(anchor="w", pady=(2, 8))
        tk.Label(model_row, text="🤖 Gemini：", font=FONT_SMALL, bg=BG, fg="gray").pack(side="left")
        tk.Label(model_row, text=cfg.get("gemini_model", ai_engine.get_model()), font=FONT_SMALL, bg=BG, fg="#1565c0").pack(side="left")
        tk.Label(model_row, text=" ｜ 🧠 Embedding：", font=FONT_SMALL, bg=BG, fg="gray").pack(side="left")
        tk.Label(model_row, text=cfg.get("embedding_model", ai_engine.get_embedding_model()), font=FONT_SMALL, bg=BG, fg="#1565c0").pack(side="left")
        tk.Label(model_row, text="  🌐 WEB検索: ON" if cfg.get("use_web_search") else "  WEB検索: OFF", font=FONT_SMALL, bg=BG, fg="#2e7d32" if cfg.get("use_web_search") else "#888").pack(side="left", padx=(12, 0))
        tk.Button(model_row, text="⚙️ 設定変更", font=FONT_SMALL, bg="#e0e0e0", fg="#333", relief="flat", cursor="hand2", padx=6, pady=2, command=self._show_edit_settings_screen).pack(side="left", padx=(8, 0))

        btn_f2 = tk.Frame(f, bg=BG)
        btn_f2.pack(side="bottom", pady=(5, 10))
        styled_btn(btn_f2, "🃏 AnkiDec出力",  self._show_anki_export_screen, width=20, bg="#e67e22").pack(side="left", padx=4)
        if cfg.get("anki_imported"):
            styled_btn(btn_f2, "🔄 AIで再分類", self._show_anki_reclassify, width=16, bg="#00796b").pack(side="left", padx=4)
        styled_btn(btn_f2, "📷 フォルダから図解を一括取込", self._import_folder_images, width=30, bg="#1565c0").pack(side="left", padx=4)

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack(side="bottom", pady=(10, 5))

        def on_start():
            sel = combo_var.get()
            if not sel: return
            tid = tname = None
            for d, i in topic_list:
                if d == sel:
                    tid, tname = i, d.split(": ", 1)[1] if ": " in d else d
                    break
            self.current_topic = {"id": tid, "name": tname}
            self.chat_history  = []
            self._show_lesson_screen()

        styled_btn(btn_f, "▶ 学習開始",       on_start,                                        width=14).pack(side="left", padx=4)
        styled_btn(btn_f, "📊 状況＋講評",    self._show_learning_stats,                       width=14, bg="#2e7d32").pack(side="left", padx=4)
        styled_btn(btn_f, "📈 状況（高速）",  lambda: self._show_learning_stats(with_ai=False), width=14, bg="#1565c0").pack(side="left", padx=4)
        styled_btn(btn_f, "💬 自由質問",      self._show_free_chat_screen,                     width=14, bg="#6a3d9a").pack(side="left", padx=4)
        styled_btn(btn_f, "🏠 ホームへ",      self._show_start_dialog,                         width=12, bg="#888").pack(side="left", padx=4)

        sel_frame = tk.Frame(f, bg=BG)
        sel_frame.pack(side="bottom", fill="x", pady=4)
        tk.Label(sel_frame, text="学習する分野を選択：", font=FONT_BOLD, bg=BG).pack(side="left")

        topic_list, prog = self._build_progress_table(f, canvas_height=300)

        default_idx = next((i for i, (disp, tid) in enumerate(topic_list) if not prog.get(tid, {}).get("done")), 0)

        combo_var = tk.StringVar()
        combo = ttk.Combobox(sel_frame, textvariable=combo_var, values=[d for d, _ in topic_list], font=FONT_NORMAL, width=40, state="readonly")
        combo.pack(side="left", padx=10)

        tk.Label(sel_frame, text="　出題形式：", font=FONT_BOLD, bg=BG).pack(side="left")
        format_var = tk.StringVar()
        format_combo = ttk.Combobox(sel_frame, textvariable=format_var, values=["正誤問題", "5肢択一問題", "穴埋め問題", "記述式問題", "論証問題", "理系用計算問題（途中式あり）", "理系用証明・導出問題"], font=FONT_NORMAL, width=28, state="readonly")
        format_combo.pack(side="left")

        if "topic_settings" not in self.cfg_data: self.cfg_data["topic_settings"] = {}

        def _update_format_combo(*args):
            sel = combo_var.get()
            tid = next((i for d, i in topic_list if d == sel), None)
            if tid: format_var.set(self.cfg_data["topic_settings"].get(tid, "記述式問題"))

        def _save_format(*args):
            sel = combo_var.get()
            tid = next((i for d, i in topic_list if d == sel), None)
            if tid:
                self.cfg_data["topic_settings"][tid] = format_var.get()
                database.save_cfg(self.current_subject, {"topic_settings": self.cfg_data["topic_settings"]})

        combo.bind("<<ComboboxSelected>>", _update_format_combo)
        format_combo.bind("<<ComboboxSelected>>", _save_format)

        if topic_list:
            combo.current(default_idx)
            _update_format_combo()

    def _show_edit_settings_screen(self):
        root = tk.Tk(); root.attributes("-topmost", True); root.withdraw()
        if not messagebox.askyesno("設定変更の確認", "設定変更画面へ進みますか？", parent=root):
            root.destroy(); return
        root.destroy()
        self._clear()
        
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)
        f = self._create_scrollable_container(outer)
        f.configure(padx=30, pady=20)
        
        f.columnconfigure(1, weight=1)
        f.rowconfigure(5, weight=1)
        section_label(f, f"⚙️ 設定の変更：{self.current_subject}").grid(row=0, column=0, columnspan=2, pady=(0,20), sticky="w")
        
        cfg = self.cfg_data
        
        labels = [("目標到達レベル", "goal_level"), ("目標到達までの時間", "total_hours"), ("説明のレベル", "explain_level")]
        self._edit_entries = {}
        for i, (lbl_text, key) in enumerate(labels):
            tk.Label(f, text=lbl_text, font=FONT_NORMAL, bg=BG).grid(row=i+1, column=0, sticky="w", pady=6)
            e = tk.Entry(f, font=FONT_NORMAL, width=40, relief="solid")
            e.grid(row=i+1, column=1, sticky="ew", padx=12, pady=6)            
            e.insert(0, cfg.get(key, ""))
            if key == "total_hours": e.configure(state="readonly", readonlybackground="#e0e0e0")
            self._edit_entries[key] = e
            
        tk.Label(f, text="Geminiモデルコード", font=FONT_NORMAL, bg=BG).grid(row=4, column=0, sticky="w", pady=6)
        model_e = tk.Entry(f, font=FONT_NORMAL, width=40, relief="solid")
        model_e.grid(row=4, column=1, sticky="ew", padx=12, pady=6)
        model_e.insert(0, cfg.get("gemini_model", ai_engine.get_model()))
        self._edit_entries["gemini_model"] = model_e

        tk.Label(f, text="Embeddingモデル", font=FONT_NORMAL, bg=BG).grid(row=5, column=0, sticky="w", pady=6)
        emb_e = tk.Entry(f, font=FONT_NORMAL, width=40, relief="solid")
        emb_e.grid(row=5, column=1, sticky="ew", padx=12, pady=6)
        emb_e.insert(0, cfg.get("embedding_model", ai_engine.get_embedding_model()))
        self._edit_entries["embedding_model"] = emb_e
        
        tk.Label(f, text="留意事項", font=FONT_NORMAL, bg=BG).grid(row=6, column=0, sticky="nw", pady=6)
        notes_box = scrolledtext.ScrolledText(f, font=FONT_NORMAL, height=12, relief="solid", wrap="word")
        notes_box.grid(row=6, column=1, sticky="nsew", padx=12, pady=6)
        notes_box.insert("end", cfg.get("notes", ""))
        self._edit_entries["notes"] = notes_box
        
        tk.Label(f, text="参考資料 (RAG / コーパス)", font=FONT_NORMAL, bg=BG).grid(row=7, column=0, sticky="nw", pady=6)
        rag_store_var = tk.StringVar(value=cfg.get("rag_store_name", ""))
        rag_display_var = tk.StringVar()
        stores = ai_engine.get_file_search_stores()
        store_options = {"使用しない": ""}
        for s in stores: store_options[s["display"]] = s["name"]
        rag_display_var.set(next((disp for disp, name in store_options.items() if name == rag_store_var.get()), "使用しない"))
        rag_dropdown = tk.OptionMenu(f, rag_display_var, *store_options.keys(), command=lambda choice: rag_store_var.set(store_options[choice]))
        rag_dropdown.config(font=FONT_NORMAL, width=35)
        rag_dropdown.grid(row=7, column=1, sticky="w", padx=12, pady=6)

        tk.Label(f, text="RAG資料の性質", font=FONT_NORMAL, bg=BG).grid(row=8, column=0, sticky="nw", pady=6)
        rag_type_var = tk.StringVar(value=cfg.get("rag_type", "systematic"))
        rag_type_frame = tk.Frame(f, bg=BG)
        rag_type_frame.grid(row=8, column=1, sticky="w", padx=12, pady=6)
        tk.Radiobutton(rag_type_frame, text="教科書・参考書モード（目次と内容を忠実に再現）", variable=rag_type_var, value="systematic", bg=BG).pack(anchor="w")
        tk.Radiobutton(rag_type_frame, text="問題集・プリントモード（AIが構成を整理し、足りない知識を補足）", variable=rag_type_var, value="fragmented", bg=BG).pack(anchor="w")

        tk.Label(f, text="🌐 WEB検索", font=FONT_NORMAL, bg=BG).grid(row=9, column=0, sticky="w", pady=6)
        use_web_var = tk.BooleanVar(value=cfg.get("use_web_search", False))
        web_cb_frame = tk.Frame(f, bg=BG)
        web_cb_frame.grid(row=9, column=1, sticky="w", padx=12, pady=6)
        tk.Checkbutton(web_cb_frame, text="最新WEB情報を検索反映", variable=use_web_var, font=FONT_NORMAL, bg=BG).pack(side="left")

        def on_save():
            new_emb = self._edit_entries["embedding_model"].get().strip()
            if new_emb != cfg.get("embedding_model", ai_engine.get_embedding_model()):
                if not messagebox.askyesno("確認", "Embeddingモデルを変更すると、既存の画像検索データやRAG（外部資料）との互換性がなくなり、正しく動作しなくなる可能性があります。\n\n本当に変更しますか？"):
                    return

            self.cfg_data["goal_level"] = self._edit_entries["goal_level"].get().strip()
            self.cfg_data["total_hours"] = self._edit_entries["total_hours"].get().strip()
            self.cfg_data["explain_level"] = self._edit_entries["explain_level"].get().strip()
            self.cfg_data["gemini_model"] = self._edit_entries["gemini_model"].get().strip()
            self.cfg_data["embedding_model"] = new_emb
            self.cfg_data["notes"] = self._edit_entries["notes"].get("1.0", "end").strip()
            self.cfg_data["rag_store_name"] = rag_store_var.get()
            self.cfg_data["rag_type"] = rag_type_var.get()
            self.cfg_data["use_web_search"] = use_web_var.get()
            ai_engine.set_model(self.cfg_data["gemini_model"])
            ai_engine.set_embedding_model(self.cfg_data["embedding_model"])
            database.save_cfg(self.current_subject, self.cfg_data)
            messagebox.showinfo("保存完了", "設定を変更しました。")
            self._show_menu_screen()

        btn_row = tk.Frame(f, bg=BG)
        btn_row.grid(row=10, column=0, columnspan=2, pady=20)
        styled_btn(btn_row, "✅ 保存", on_save, width=16).pack(side="left", padx=8)
        styled_btn(btn_row, "キャンセル", self._show_menu_screen, width=12, bg="#888").pack(side="left", padx=8)

    def _show_anki_export_screen(self):
        self._clear()
        if hasattr(self, "_current_table_canvas"): self.unbind_all("<MouseWheel>") 

        subj = self.current_subject
        f = tk.Frame(self, bg=BG, padx=30, pady=16)
        f.pack(fill="both", expand=True)

        section_label(f, f"🃏 AnkiDec出力 (既存問題) : {subj}").pack(anchor="w", pady=(0,8))

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack(side="bottom", pady=10)
        
        sel_frame = tk.Frame(f, bg=BG)
        sel_frame.pack(side="bottom", fill="x", pady=16)
        tk.Label(sel_frame, text="AnkiDecを出力する範囲を選択：", font=FONT_BOLD, bg=BG).pack(side="left")

        export_options = ["全ての小問を出力", "弱点の小問を出力", "直近不正解の小問を出力"]
        combo_var = tk.StringVar(value=export_options[0])
        combo = ttk.Combobox(sel_frame, textvariable=combo_var, values=export_options, font=FONT_NORMAL, width=30, state="readonly")
        combo.pack(side="left", padx=10)

        self._build_progress_table(f, canvas_height=200)

        def do_export():
            target_type = combo_var.get()
            filter_map = {"全ての小問を出力": "ALL", "弱点の小問を出力": "WEAK", "直近不正解の小問を出力": "RECENT_WRONG"}
            rows_dict = database.get_questions_for_export(subj, filter_map.get(target_type, "ALL"))

            if not rows_dict:
                return messagebox.showinfo("該当なし", "指定された条件に一致する問題がありません。")

            filepath = filedialog.asksaveasfilename(
                title="保存先を指定", defaultextension=".apkg",
                filetypes=[("Ankiパッケージ", "*.apkg"), ("CSVファイル", "*.csv")],
                initialfile=f"AnkiDeck_{subj}_{target_type}.apkg"
            )
            if not filepath: return

            media_dir = database.get_media_dir(subj)
            success, msg = anki_exporter.export_deck(filepath, subj, target_type, rows_dict, media_dir)
            if success:
                messagebox.showinfo("出力完了", msg)
            else:
                messagebox.showerror("エラー", msg)

        styled_btn(btn_f, "🃏 AnkiDecを出力", do_export, width=20, bg="#e67e22").pack(side="left", padx=8)
        styled_btn(btn_f, "✨ 既存小問と別のAnkiDecを作成", self._show_anki_generate_screen, width=32, bg="#3d7ebf").pack(side="left", padx=8)
        styled_btn(btn_f, "← 戻る", self._show_menu_screen, width=12, bg="#888").pack(side="left", padx=8)

    def _show_anki_generate_screen(self):
        self._clear()
        if hasattr(self, "_current_table_canvas"): self.unbind_all("<MouseWheel>")

        subj = self.current_subject
        f = tk.Frame(self, bg=BG, padx=30, pady=16)
        f.pack(fill="both", expand=True)

        section_label(f, f"✨ 既存小問と別のAnkiDecを作成 : {subj}").pack(anchor="w", pady=(0,8))
        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack(side="bottom", pady=10)

        msg_var = tk.StringVar()
        tk.Label(f, textvariable=msg_var, font=FONT_NORMAL, bg=BG, fg="#1565c0").pack(side="bottom", pady=4)

        num_frame = tk.Frame(f, bg=BG)
        num_frame.pack(side="bottom", fill="x", pady=4)
        tk.Label(num_frame, text="1分野あたりのDec数：", font=FONT_BOLD, bg=BG).pack(side="left")
        num_var = tk.StringVar(value="5")
        tk.Entry(num_frame, textvariable=num_var, font=FONT_NORMAL, width=6, justify="center", relief="solid").pack(side="left", padx=8)
        tk.Label(num_frame, text="問", font=FONT_NORMAL, bg=BG).pack(side="left")

        tk.Label(num_frame, text="　　一括出題形式：", font=FONT_BOLD, bg=BG).pack(side="left")
        format_options = ["分野別の設定に従う", "正誤問題", "5肢択一問題", "穴埋め問題", "記述式問題", "論証問題", "理系用計算問題（途中式あり）", "理系用証明・導出問題"]
        gen_format_var = tk.StringVar(value=format_options[0])
        gen_format_combo = ttk.Combobox(num_frame, textvariable=gen_format_var, values=format_options, font=FONT_NORMAL, width=25, state="readonly")
        gen_format_combo.pack(side="left", padx=8)

        sel_frame = tk.Frame(f, bg=BG)
        sel_frame.pack(side="bottom", fill="x", pady=(16, 4))
        tk.Label(sel_frame, text="AnkiDecを出力する範囲を選択（複数選択可）：", font=FONT_BOLD, bg=BG).pack(anchor="w")

        list_frame = tk.Frame(f, bg=BG)
        list_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        list_scroll = tk.Scrollbar(list_frame, orient="vertical")
        list_scroll.pack(side="right", fill="y")
        lb_topics = tk.Listbox(list_frame, font=FONT_NORMAL, height=6, selectmode="multiple", yscrollcommand=list_scroll.set, exportselection=False)
        lb_topics.pack(side="left", fill="x", expand=True)
        list_scroll.config(command=lb_topics.yview)

        topic_list, _ = self._build_progress_table(f, canvas_height=180)
        lb_topics.insert("end", "全分野")
        for disp, tid in topic_list: lb_topics.insert("end", disp)

        def do_generate():
            selected_indices = lb_topics.curselection()
            if not selected_indices: return messagebox.showwarning("選択エラー", "出力する分野を選択してください。")
            try:
                n_count = int(num_var.get().strip())
                if n_count <= 0: raise ValueError
            except ValueError:
                return messagebox.showwarning("入力エラー", "Dec数は1以上の整数を入力してください。")

            if not messagebox.askyesno("確認", "ここで生成される小問はDBには追加されず、AnkiDeckとして出力されます。\n\n生成を開始しますか？"):
                return

            target_tids, target_names = [], []
            if 0 in selected_indices:
                target_tids, target_names = [tid for disp, tid in topic_list], [disp for disp, tid in topic_list]
            else:
                for idx in selected_indices:
                    disp, tid = topic_list[idx - 1]
                    target_tids.append(tid)
                    target_names.append(disp)

            filepath = filedialog.asksaveasfilename(
                title="保存先を指定", defaultextension=".apkg",
                filetypes=[("Ankiパッケージ", "*.apkg"), ("CSVファイル", "*.csv")],
                initialfile=f"AnkiDeck_New_{subj}.apkg"
            )
            if not filepath: return

            override_format = gen_format_var.get()

            def task():
                results = []
                total = len(target_tids)

                for i, (tid, tname) in enumerate(zip(target_tids, target_names)):
                    # 画面に進捗を表示
                    self.after(0, lambda m=f"⏳ 生成中... ({i+1}/{total}) : {tname}": msg_var.set(m))
                    lesson_text = database.load_explane(subj, tid) or ""
                    lesson_scope = (f"\n\n【出題範囲の限定】必ず以下の「説明本文」で説明された内容のみから作成してください。\n--- 説明本文 ---\n{re.sub(r'```python\s*\n([\s\S]*?)```', '【図表の描画コードは省略】\n', lesson_text)}\n--- ここまで ---" if lesson_text else "")

                    # トピックごとに最適な画像ブロックを取得
                    media_block = get_full_media_block(subj, query=tname)

                    if override_format == "分野別の設定に従う":
                        q_format = self.cfg_data.get("topic_settings", {}).get(tid, "記述式問題")
                    else:
                        q_format = override_format

                    prompt_modifiers = ""
                    ans_hint = "模範解答"
                    if q_format == "正誤問題": prompt_modifiers += "\n【出題形式：正誤問題】問題文は必ず「〇」か「×」で答えられる文章にし、問題文の冒頭に必ず「次の記述の正誤を答えてください。」という一文を入れてください。"; ans_hint = "〇 または ×"
                    elif q_format == "5肢択一問題": prompt_modifiers += "\n【出題形式：5肢択一問題】問題文の中に、必ず1から5までの選択肢を含め、解答は正解の番号のみを記載してください。"; ans_hint = "正解の番号のみ"
                    elif q_format == "穴埋め問題": prompt_modifiers += "\n【出題形式：穴埋め問題】問題文のキーワード1箇所を空欄（[  ]）にし、解答にはその語句のみを記載。"; ans_hint = "空欄に入る語句"
                    elif q_format == "論証問題": prompt_modifiers += "\n【出題形式：論証問題】具体的な事例や複雑な状況を設定した長文問題とし、解答は理由や論拠を含めた記述式にしてください。"; ans_hint = "理由を含めた長文解答"
                    elif q_format == "理系用計算問題（途中式あり）": prompt_modifiers += "\n【出題形式：計算問題】解答には最終的な答えと計算過程を必ず詳しく記述してください。"; ans_hint = "途中式と最終的な答え"
                    elif q_format == "理系用証明・導出問題": prompt_modifiers += "\n【出題形式：証明・導出問題】数式を用いた論理的なステップを踏んだ記述にしてください。"; ans_hint = "証明または導出プロセス"
                    else: prompt_modifiers += "\n【出題形式：記述式問題】簡潔な文章または単語で答えられる問いにしてください。"; ans_hint = "簡潔な模範解答"

                    # --- 修正：画像利用の許可と指示を追加 ---
                    prompt_modifiers += (
                        "\n【図表・画像の利用ルール（重要）】"
                        "\n Ankiアプリ用データとして出力するため、Pythonコード（```python 〜 ```）は絶対に使用しないでください。"
                    )

                    # プロンプトの組み立て
                    prompt = f"""あなたは教育専門家およびAnkiカード作成のプロフェッショナルです。
科目「{subj}」の「{tname}」について、以下の学習内容を元に、効果的なAnki用の問題と解答を {n_count}問 作成してください。

【1. 利用可能な画像データの確認】
あなたは、この科目のために用意された画像リスト（下記）を持っています。問題を作成する前に、必ずこのリストの内容を確認してください。
{media_block}

【2. 問題作成のルール】
1. {prompt_modifiers}
2. 【情報の正確性】提供された「説明本文」がある場合は、その内容を絶対的な正解基準としてください。
3. 【画像・図解の積極活用】
   - 説明、問題、または解説に適切な画像があれば `<img src="ファイル名">` を積極的に使用してください。
   - **[重要]** [※図1] や (画像:...) のようなテキスト形式での引用はAnkiアプリが読み取れないため「絶対に禁止」です。必ずタグ形式で出力してください。
   - ただし、Ankiアプリの互換性のため、Pythonコード(```python 〜 ```)は絶対に使用しないでください。画像タグ（<img>）のみを使用してください。
4. 【質の高い解説】解答には、なぜそれが正解なのかという理由だけでなく、覚えるためのコツや関連知識を盛り込んでください。

{lesson_scope}

【出力形式】
※必ず以下のJSON配列形式のみを出力してください。
[
  {{
    "question": "問題文（必要に応じて <img src='...'> を含む）",
    "answer": "{ans_hint}",
    "explanation": "詳しい解説（必要に応じて <img src='...'> を含む）"
  }},
  ...{n_count}問
]"""

                    # APIリトライと待機時間の実装
                    max_retries = 3  
                    for attempt in range(max_retries):
                        try:
                            # 1回のリクエスト（1分野分）を実行
                            raw = ai_engine.gemini_once_json(prompt)
                            new_gen = json.loads(raw)
                            results.extend(new_gen)
                
                            # 【重要】次の分野へ行く前にしっかり休む（15〜20秒）
                            # これにより「短時間の連続リクエスト制限」を回避します
                            time.sleep(20) 
                            break  # 成功したらこの分野のリトライループを抜ける

                        except Exception as e:
                            err_str = str(e).lower()
                            # 混雑(503)やリクエスト過多(429)の場合は、長めに待機してリトライ
                            if ("503" in err_str or "429" in err_str) and attempt < max_retries - 1:
                                self.after(0, lambda m=f"⚠️ 混雑中... 30秒待機して再試行 ({attempt+1}/{max_retries})": msg_var.set(m))
                                time.sleep(30)
                                continue
                            
                            # 致命的なエラーやリトライ上限時はログを出してスキップ
                            print(f"Error generating {tname}: {e}")
                            break

                if not results:
                    self.after(0, lambda: messagebox.showerror("エラー", "問題の生成に失敗しました。"))
                    self.after(0, lambda: msg_var.set(""))
                    return

                media_dir = database.get_media_dir(subj)
                success, msg = anki_exporter.export_deck(filepath, subj, "New", results, media_dir)
                
                self.after(0, lambda s=success, m=msg: messagebox.showinfo("出力完了", m) if s else messagebox.showerror("エラー", m))
                self.after(0, lambda: msg_var.set(""))

            threading.Thread(target=task, daemon=True).start()

        styled_btn(btn_f, "🃏 AnkiDecを出力",   do_generate, width=20, bg="#e67e22").pack(side="left", padx=8)
        styled_btn(btn_f, "← AnkiDec出力へ戻る", self._show_anki_export_screen, width=20, bg="#555").pack(side="left", padx=8)
        styled_btn(btn_f, "🏠 学習メニューへ",   self._show_menu_screen, width=16, bg="#888").pack(side="left", padx=8)

    def _show_review_test_screen(self):
        self._clear()
        subj = self.current_subject
        all_qs = database.get_review_questions(subj)
        if not all_qs: return self._show_menu_screen()

        total_review_target, all_qs = len(all_qs), all_qs[:100]

        f = tk.Frame(self, bg=BG, padx=20, pady=14)
        f.pack(fill="both", expand=True)

        section_label(f, f"📝 復習テスト：{subj}").pack(anchor="w", pady=(0,2))
        pending_text = f"（※他 {total_review_target - 100}問は次回に持ち越し）" if total_review_target > 100 else ""
        tk.Label(f, text=(f"蓄積問題数（全体）: {database.count_all_questions(subj)}問　／　今回の復習対象: {len(all_qs)}問 {pending_text}\n忘却曲線に基づいて出題します。全問回答しなくても「採点して次へ」で先に進めます。"), font=FONT_SMALL, bg="#eef4fb", fg="#334", relief="groove", padx=6, pady=4, justify="left").pack(fill="x", pady=(0,6))

        scroll_frame = tk.Frame(f, bg=BG)
        scroll_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_frame, bg=BG, highlightthickness=0)
        scroll = tk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        inner  = tk.Frame(canvas, bg=BG)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._review_questions, self._review_answer_vars, self._review_delete_vars = all_qs, [], []

        for i, q in enumerate(all_qs):
            score = q["review_score"]

            # 復習テスト用のバッジ判定 ===
            # DBからリストアップされた時点で「今日復習すべき問題」であることが確定しているため、
            # 未出題（スコア999以上）以外はすべて「要復習」とする。
            if score >= 999:
                badge, badge_bg = "🆕 未出題", "#d4edda" # 緑系
            else:
                badge, badge_bg = "⚠️ 要復習", "#fff3cd" # 黄系

            qf = tk.LabelFrame(inner, text=f"問{i+1}　{badge}　[正解率: {q['correct_rate']*100:.0f}%  出題: {q['asked_count']}回]", font=FONT_SMALL, bg=badge_bg, padx=8, pady=4)
            qf.pack(fill="x", padx=4, pady=4)
            
            header_f = tk.Frame(qf, bg=badge_bg)
            header_f.pack(fill="x", anchor="w")
            
            disp_text = re.sub(r'(?<!`)\npython\n', '\n```python\n', q["question"].replace('\\n', '\n'))
            display_q = re.sub(r"```python[\s\S]*?```", "\n（📊 図表が含まれています。下の「🌐 リッチ表示」ボタンを押すとブラウザで確認できます）\n", disp_text)
            display_q = re.sub(r"<img[^>]+>", "\n（🖼️ 画像が含まれています。下の「🌐 リッチ表示」ボタンを押すとブラウザで確認できます）\n", display_q, flags=re.IGNORECASE)
            
            tk.Label(header_f, text=display_q, font=FONT_NORMAL, bg=badge_bg, wraplength=550, justify="left").pack(side="left", anchor="w")
            
            del_var = tk.BooleanVar(value=False)
            self._review_delete_vars.append({"q": q, "var": del_var})
            tk.Checkbutton(header_f, text="🗑️ この小問を削除（採点時に実行）", variable=del_var, font=FONT_SMALL, bg=badge_bg, fg="#a00", selectcolor=badge_bg).pack(side="right", padx=4)

            # 問題のデータから形式を取得しUIを分岐 ---
            q_fmt = q.get("format", "記述式問題")
            ans_frame = tk.Frame(qf, bg=badge_bg)
            ans_frame.pack(fill="x", pady=4, anchor="w")
            
            ans_var = tk.StringVar(value="未回答")
            ans_txt = None
            
            if q_fmt == "正誤問題":
                for rb_val in ["○ (正しい)", "× (誤り)", "未回答"]:
                    tk.Radiobutton(ans_frame, text=rb_val, variable=ans_var, value=rb_val, bg=badge_bg).pack(side="left", padx=5)
            elif q_fmt == "5肢択一問題":
                for rb_val in ["1", "2", "3", "4", "5", "未回答"]:
                    tk.Radiobutton(ans_frame, text=rb_val, variable=ans_var, value=rb_val, bg=badge_bg).pack(side="left", padx=5)
            else:
                txt_frame, ans_txt = create_resizable_text(ans_frame, width=80, default_height=3)
                txt_frame.pack(fill="x")

            img_ui_frame, img_var = _add_image_attach_ui(qf, bg_color=badge_bg)
            img_ui_frame.pack(fill="x", pady=(0, 4), anchor="w")
            self._review_answer_vars.append({"text": ans_txt, "var": ans_var, "img": img_var, "fmt": q_fmt})


        btn_row = tk.Frame(inner, bg=BG)
        btn_row.pack(fill="x", padx=4, pady=(6,12))
        styled_btn(btn_row, "🌐 リッチ表示", self._open_review_test_math, width=12, bg="#6a1b9a").pack(side="left", padx=8)
        styled_btn(btn_row, "✅ 採点して学習メニューへ", self._submit_review_test, width=26).pack(side="right", padx=8)

    def _submit_review_test(self):
        subj, all_qs, ans_data = self.current_subject, self._review_questions, self._review_answer_vars

        deleted_qids = []
        if hasattr(self, "_review_delete_vars"):
            for item in self._review_delete_vars:
                if item["var"].get():
                    database.delete_question(subj, item["q"]["id"])
                    deleted_qids.append(item["q"]["id"])
        
        if deleted_qids: messagebox.showinfo("削除完了", f"チェックされた {len(deleted_qids)}問の小問を削除しました。")

        # テキストエリアとラジオボタンの値を適切に取得 ---
        answered = []
        for i, (q, d) in enumerate(zip(all_qs, ans_data)):
            if q["id"] in deleted_qids:
                continue
            
            if d["fmt"] in ["正誤問題", "5肢択一問題"]:
                val = d["var"].get()
                u_ans = "" if val == "未回答" else val
            else:
                u_ans = d["text"].get("1.0", "end-1c").strip() if d["text"] else ""
            
            if u_ans or list(d["img"]):
                answered.append({"q": q, "user_answer": u_ans, "img_path": list(d["img"])})


        if not answered:
            if messagebox.askyesno("確認", "回答が1問もありません。\n復習テストをスキップして学習メニューへ進みますか？"):
                self._show_menu_screen()
            return

        has_images = any(a["img_path"] for a in answered)
        
        dlg = tk.Toplevel(self)
        dlg.title("採点中")
        dlg.attributes("-topmost", True)
        dlg.grab_set()
        
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"400x150+{(sw-400)//2}+{(sh-150)//2}")
        dlg.configure(bg=BG)
        
        msg = "⏳ Geminiが画像を解析・採点中…" if has_images else "⏳ Geminiが採点・解説中…"
        tk.Label(dlg, text=msg, font=FONT_TITLE, bg=BG).pack(expand=True)
        dlg.update()

        notes_val   = self.cfg_data.get("notes", "")
        notes_block = ("\n\n[ユーザー指定の留意事項]\n" + notes_val) if notes_val else ""
        if self.cfg_data.get("use_web_search"):
            notes_block += "\n【重要：WEB検索の実行】あなたはGoogle検索機能を利用可能です。上記の「留意事項」に法改正や最新情報の確認指示がある場合は、必ず検索を実行して最新の情報を取得した上で採点・解説を行ってください。"

        combined_lesson_text = "".join(f"\n[分野ID: {tid} の説明]\n{txt}\n" for tid, txt in ((t, database.load_explane(subj, t)) for t in set([item["q"]["topic_id"] for item in answered])) if txt)
        lesson_scope_block = f"\n【絶対の採点基準】\n以下の「説明本文」の内容を正解の絶対基準とします。ユーザーの回答がこの説明本文の趣旨と合っていれば正解としてください。\n--- 説明本文 ---\n{combined_lesson_text}\n--- ここまで ---\n" if combined_lesson_text else ""

        def grade():
            explain_level = self.cfg_data.get("explain_level", "中学生レベル")
            topic_settings = self.cfg_data.get("topic_settings", {})

            # 復習対象のトピック名をクエリとして使用
            t_names = list(set([item["q"].get("topic_id", "") for item in answered]))
            query_str = ", ".join(t_names)

            header = f"""あなたは厳格かつ親切な採点担当の家庭教師です。
科目「{subj}」の復習テスト（{len(answered)}問）を、以下の基準に従って採点し、詳細な解説を提供してください。

【1. 利用可能な画像データの確認】
あなたは、この科目のために用意された画像リスト（下記）を持っています。解説を作成する前に、必ずこのリストの内容を確認してください。
{get_full_media_block(subj, query=query_str)}

【2. 採点・解説の重要ルール】
1. 【正解基準】{lesson_scope_block} に基づき、その趣旨に合致していれば正解としてください。{notes_block}
2. 【手書き・添付回答の優先】ユーザーが手書き画像や添付ファイルを提出している場合、その内容（数式・図・文字）を最優先で読み取って正誤を判定してください。テキスト回答が空であっても、画像に回答があれば未回答とはせず、その内容で採点してください。
3. 【矛盾判定】ユーザーのテキスト回答と画像回答の内容が明らかに矛盾する場合は、その問いを「採点不能」とし、解説にその旨を記載してください。
4. 【解説の質】「{explain_level}」に合わせた分かりやすい言葉で、正解の根拠、暗記のコツ、よくある間違いなどを解説してください。
5. 【画像・図解の積極活用】
   - 解説に図解が必要な場合、提供された画像リストに適切なものがあれば `<img src="ファイル名">` を最優先で使用してください。
   - **[※資料...] や (画像:...) のようなテキスト形式での引用はシステムが読み取れないため「絶対に禁止」です。** 必ずタグ形式で出力してください。
   - 該当画像がない場合に限り、Plotlyを用いたPythonコード（```python 〜 ```）を作成してください（matplotlib不可）。

【3. 技術的制約】
- 数式のバックスラッシュは必ず2つ（\\）重ねてエスケープしてください。
- 改行は通常の「\\n」を使用してください。
- 図表のPythonコードは必ずバッククォート3つ（```python）で囲ってください。

--- 採点対象 ---"""
            contents = [header]


            for i, item in enumerate(answered):
                q_fmt = item["q"].get("format", "記述式問題")
                u_ans_raw = item["user_answer"].strip() if item["user_answer"] else ""
                has_img = bool(item["img_path"])

                if not u_ans_raw and not has_img:
                    u_ans_text = "（未回答）"
                elif not u_ans_raw and has_img:
                    u_ans_text = "（テキスト回答なし。添付画像を確認して採点してください）"
                else:
                    u_ans_text = u_ans_raw

                contents.append(f"問{i+1}【出題形式：{q_fmt}】: {item['q']['question']}\n模範解答: {item['q']['answer']}\nユーザー回答（テキスト）: {u_ans_text}")
                for img_path in item["img_path"]:
                    try: contents.extend([f"問{i+1} の手書き・添付ファイル：", *ai_engine.file_to_parts(img_path)])
                    except Exception as img_e: contents.append(f"（ファイル読み込みエラー: {img_e}）")
            contents.append(f"""
--- ここまで ---

【出力形式】
※必ず以下のJSON構造のみを出力してください。
{{
  "total_score": 2, 
  "results": [
    {{ "q": 1, "correct": true, "interpreted": "画像から読み取った内容（画像がない場合は空文字）", "explanation": "解説文" }}
  ],
  "overall_comment": "総評"
}}""")
            try:
                raw = ai_engine.gemini_once_json_multimodal(contents, use_web_search=self.cfg_data.get("use_web_search", False)) if has_images else ai_engine.gemini_once_json("\n".join(c for c in contents if isinstance(c, str)), use_web_search=self.cfg_data.get("use_web_search", False))
                result = safe_json_loads(raw)
                for idx, item in enumerate(answered):
                    res_list = result.get("results", [])
                    if idx < len(res_list):
                        database.update_question_result(subj, item["q"]["id"], bool(res_list[idx].get("correct", False)), res_list[idx].get("explanation", ""))
                self.after(0, dlg.destroy)
                self.after(0, lambda: self._show_review_result_screen(result, answered))
            except Exception as e:
                self.after(0, dlg.destroy)
                self.after(0, lambda err=e: self._show_friendly_error(err, "復習テスト採点エラー"))

        threading.Thread(target=grade, daemon=True).start()

    def _show_review_result_screen(self, result, answered):
        self._clear()
        subj = self.current_subject

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)
        f = self._create_scrollable_container(outer)
        f.configure(padx=20, pady=14)

        total = len(answered)
        try: score = min(total, max(0, int(result.get("total_score", 0))))
        except: score = 0
        s_color = "#2d6a2d" if total > 0 and score/total >= 0.8 else "#a05000" if total > 0 and score/total >= 0.6 else "#b00020"

        section_label(f, f"📊 復習テスト結果：{subj}").pack(anchor="w")
        tk.Label(f, text=f"得点: {score} / {total}", font=(_BASE_FONT, 18, "bold"), bg=BG, fg=s_color).pack(anchor="w", pady=4)

        def _hide_code(text):
            t = re.sub(r'(?<!`)\npython\n', '\n```python\n', text.replace('\\n', '\n'))
            t = re.sub(r"```python[\s\S]*?```", "\n（📊 図表が含まれています。下の「🌐 リッチ表示」ボタンを押すとブラウザで確認できます）\n", t)
            return re.sub(r"<img[^>]+>", "\n（🖼️ 画像が含まれています。下の「🌐 リッチ表示」ボタンを押すとブラウザで確認できます）\n", t, flags=re.IGNORECASE)

        tk.Label(f, text=_hide_code(result.get("overall_comment", "")), font=FONT_NORMAL, bg="#fffbe6", relief="groove", wraplength=840, justify="left", padx=8, pady=6).pack(fill="x", pady=4)

        detail_frame = tk.LabelFrame(f, text="各問の解説", font=FONT_BOLD, bg=BG, padx=8, pady=6)
        detail_frame.pack(fill="both", expand=True, pady=6)

        detail_box = scrolledtext.ScrolledText(detail_frame, font=FONT_NORMAL, height=16, state="disabled", relief="solid", wrap="word")
        detail_box.pack(fill="both", expand=True)
        detail_box.configure(state="normal")
        for i, res in enumerate(result.get("results", [])):
            mark = "✅" if res.get("correct") else "❌"
            if i < len(answered):
                item = answered[i]
                q_text, correct_ans, user_ans = item["q"]["question"], item["q"]["answer"], item["user_answer"]
                
                # AIが画像から読み取ったテキストがあれば優先表示
                interpreted = res.get("interpreted", "")
                if user_ans:
                    u_ans_disp = user_ans + (f" (画像: {interpreted})" if interpreted else "")
                else:
                    u_ans_disp = f"(画像) {interpreted}" if interpreted else ("（画像回答あり）" if item.get("img_path") else "（未回答）")
            else:
                q_text, correct_ans, user_ans = "", "", ""
                u_ans_disp = "（未回答）"
            
            detail_box.insert("end", f"{mark} 問{res.get('q', i+1)}：{_hide_code(q_text)}\n   【あなたの回答】{u_ans_disp}\n   【正解】{_hide_code(correct_ans)}\n   【解説】{_hide_code(res.get('explanation', ''))}\n\n")
        detail_box.configure(state="disabled")

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack(pady=16)
        styled_btn(btn_f, "📋 問題を表示",    self._open_review_test_math, width=14, bg="#37474f").pack(side="left", padx=8)
        styled_btn(btn_f, "🌐 リッチ表示",    lambda: self._open_review_result_math(result, answered), width=12, bg="#6a1b9a").pack(side="left", padx=8)
        styled_btn(btn_f, "🏠 学習メニューへ", self._show_menu_screen, width=20).pack(side="left", padx=8)

    def _show_learning_stats(self, with_ai=True):
        try: import plotly.graph_objects as go
        except ImportError: return messagebox.showerror("ライブラリ不足", "plotly がインストールされていません。\npip install plotly")

        subj = self.current_subject
        plan = self.cfg_data.get("plan", [])
        if not plan: return messagebox.showinfo("情報", "学習計画が未設定です。")

        radar    = database.get_radar_data(subj, plan, topic_settings=self.cfg_data.get("topic_settings", {}))
        forecast = database.get_review_forecast(subj)
        heatmap  = database.get_heatmap_data(subj)

        # ── ▼ レーダーチャートのドロップダウン対応処理 ▼ ──
        all_topic_ids = []
        for top in plan:
            subs = top.get("sub_topics", [])
            if subs:
                for st in subs: all_topic_ids.append(st["id"])
            else:
                all_topic_ids.append(top["id"])

        # ドロップダウンに表示する選択肢と、それぞれに適用する出題形式の辞書を作成
        format_options = [
            ("各分野の選択出題形式の集計", self.cfg_data.get("topic_settings", {})),
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
            if fmt_name == "各分野の選択出題形式の集計":
                fmt_display = list(fmt_set)[0] if len(fmt_set) == 1 else "複数形式混在" if len(fmt_set) > 1 else "未設定"
                title_label = fmt_display
            elif fmt_name == "すべての形式（総合）":
                fmt_display = "総合"
                title_label = "総合"
            else:
                fmt_display = fmt_name
                title_label = fmt_name

            hover_texts = [f"{d['label']}<br>{round(d['rate']*100,1)}%<br>形式: {fmt_display}" for d in radar]

            # 色を少し変えて視覚的に区別（現在の設定＝青、総合＝オレンジ、その他＝緑）
            line_color = "#3d7ebf" if i == 0 else "#e67e22" if i == 1 else "#2a9d8f"
            fill_color = "rgba(61,126,191,0.25)" if i == 0 else "rgba(230,126,34,0.25)" if i == 1 else "rgba(42,157,143,0.25)"

            if labels:
                # グラフの層（トレース）を形式の数だけ重ねて作成する
                radar_fig.add_trace(go.Scatterpolar(
                    r=rates+[rates[0]],
                    theta=labels+[labels[0]],
                    fill="toself",
                    fillcolor=fill_color,
                    line=dict(color=line_color, width=2),
                    name=fmt_name,
                    visible=(i==0), # 初期状態は「現在の設定(i=0)」のみ表示
                    hovertext=hover_texts+[hover_texts[0]],
                    hoverinfo="text"
                ))

                # ドロップダウンで選ばれた時に、この層だけをTrueにするリスト
                visibilities = [False] * len(format_options)
                visibilities[i] = True

                buttons.append(dict(
                    label=fmt_name,
                    method="update",
                    args=[{"visible": visibilities},
                          {"title": f"【{subj}】分野別弱点" + (f"（{title_label}）" if title_label else "")}]
                ))

        if buttons:
            # 初期表示用のタイトル
            radar_orig = database.get_radar_data(subj, plan, topic_settings=format_options[0][1])
            fmt_set_orig = set([d["format"] for d in radar_orig if d["format"]])
            radar_fmt_label_orig = list(fmt_set_orig)[0] if len(fmt_set_orig) == 1 else "複数形式混在" if len(fmt_set_orig) > 1 else None
            initial_title = f"【{subj}】分野別弱点" + (f"（{radar_fmt_label_orig}）" if radar_fmt_label_orig else "")

            radar_fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=False,
                updatemenus=[dict(
                    active=0,
                    buttons=buttons,
                    x=1.0, # チャート右上にドロップダウンを配置
                    xanchor="right",
                    y=1.2,
                    yanchor="top",
                    font=dict(size=12),
                    bgcolor="#f8f9fa",
                    bordercolor="#ccc"
                )],
                title=initial_title,
                margin=dict(t=90, b=40, l=40, r=40) # ドロップダウン用に上部のマージンを少し広く
            )
        else:
            radar_fig = go.Figure()
        # ── ▲ ここまで ▲ ──

        # 分野IDから分野名を取得し、順番（シラバス順）も保持する
        topic_name_map = {}
        ordered_tids = []
        for top in plan:
            subs = top.get("sub_topics", [])
            if subs:
                for st in subs:
                    topic_name_map[st["id"]] = st["name"]
                    ordered_tids.append(st["id"])
            else:
                topic_name_map[top["id"]] = top["name"]
                ordered_tids.append(top["id"])

        fc_dates = [d["date"] for d in forecast]
        # x軸のラベルで今日を強調
        fc_dates_display = []
        for i, d in enumerate(fc_dates):
            # 文字列 "2026-03-29" を "3/29" 形式に変換
            dt = datetime.date.fromisoformat(d)
            short_d = f"{dt.month}/{dt.day}" 
            
            if i == 0:
                # HTMLタグを含めて赤文字・太字にする
                fc_dates_display.append(f"<span style='color:#e74c3c'><b>{short_d}<br>(今日)</b></span>")
            else:
                fc_dates_display.append(short_d)

        # 予測データに含まれる分野IDを抽出（順番を計画通りにする）
        active_tids = set().union(*(d.get("topics", {}).keys() for d in forecast))
        all_forecast_topics = [tid for tid in ordered_tids if tid in active_tids]
        # 計画にないID（Ankiインポートの未分類など）があれば末尾に追加
        for tid in active_tids:
            if tid not in all_forecast_topics:
                all_forecast_topics.append(tid)
                
        colors = ["#3d7ebf", "#e67e22", "#2a9d8f", "#e74c3c", "#9b59b6", "#f1c40f", "#1abc9c", "#34495e", "#7f8c8d", "#d35400"]
        bar_fig = go.Figure()

        if not all_forecast_topics:
            bar_fig.add_trace(go.Bar(x=fc_dates_display, y=[0]*7))
        else:
            for idx, tid in enumerate(all_forecast_topics):
                t_name = topic_name_map.get(tid, tid)
                y_vals = [d.get("topics", {}).get(tid, 0) for d in forecast]

                # 期間中に1問も復習予定がない分野は、凡例から除外するために、値が全て0の分野はスキップ 
                if sum(y_vals) == 0:
                    continue

                # ホバーテキストを作成
                hover_texts = []
                for i, d in enumerate(forecast):
                    total = d["count"]
                    val = y_vals[i]
                    hover_texts.append(f"日付: {fc_dates[i]}<br>分野: {t_name}<br>問題数: {val}問 (合計: {total}問)")
                
                # 値が0でない日のみ、積み上げ棒の中に内訳の数字を表示
                text_vals = [str(v) if v > 0 else "" for v in y_vals]
                
                bar_fig.add_trace(go.Bar(
                    name=t_name,
                    x=fc_dates_display, 
                    y=y_vals, 
                    text=text_vals,
                    textposition="inside",
                    hovertext=hover_texts,
                    hoverinfo="text",
                    marker_color=colors[idx % len(colors)]
                ))
            
            # 【元の機能を復元】各棒の「合計値」を一番上に表示するための透明なレイヤーを追加
            total_counts = [d["count"] for d in forecast]
            bar_fig.add_trace(go.Scatter(
                x=fc_dates_display,
                y=total_counts,
                mode="text",
                text=[str(v) if v > 0 else "" for v in total_counts],
                textposition="top center",
                hoverinfo="skip",    # ホバー時の重複表示を防ぐ
                showlegend=False
            ))

        bar_fig.update_layout(
            barmode="stack",
            title=f"【{subj}】直近7日間の復習予測", 
            # 重要：自動判別をオフにし、リストの順番（今日→明日...）で強制的に並べる
            xaxis=dict(type='category'),
            margin=dict(t=60, b=60, l=60, r=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )


        # --- ヒートマップ用データの構築 ---
        today = datetime.date.today()
        cur = today - datetime.timedelta(days=363)
        cur -= datetime.timedelta(days=cur.weekday())

        metrics = ["回答数", "正解数", "正解率"]
        z_data = {m: [] for m in metrics}
        hover_data = {m: [] for m in metrics}
        col_labels = []

        week_dates = []
        week_vals = {m: [] for m in metrics}

        while cur <= today + datetime.timedelta(days=6 - today.weekday()):
            # DBから取得した {count: C, correct: CR} を取得
            stats = heatmap.get(cur.isoformat(), {"count": 0, "correct": 0})
            cnt = stats["count"]
            cor = stats["correct"]
            rate = round((cor / cnt * 100), 1) if cnt > 0 else 0
            
            week_dates.append(cur.isoformat())
            week_vals["回答数"].append(cnt)
            week_vals["正解数"].append(cor)
            week_vals["正解率"].append(rate)
            
            if len(week_dates) == 7:
                for m in metrics:
                    z_data[m].append(week_vals[m][:])
                    h_list = []
                    for i in range(7):
                        d = week_dates[i]
                        v = week_vals[m][i]
                        unit = "問" if m != "正解率" else "%"
                        h_list.append(f"日付: {d}<br><b>{m}: {v}{unit}</b><br>(計: {cnt}問 / 正解: {cor}問)")
                    hover_data[m].append(h_list)
                
                col_labels.append(week_dates[0][:7])
                week_dates = []
                for m in metrics: week_vals[m] = []
            cur += datetime.timedelta(days=1)

        heat_fig = go.Figure()

        # 各指標のトレース（レイヤー）を追加
        for i, m in enumerate(metrics):
            z_matrix = [list(row) for row in zip(*z_data[m])] # 転置
            h_matrix = [list(row) for row in zip(*hover_data[m])]
            
            # 指標ごとに色調を変える
            if m == "回答数": cs = [[0.0, "#ebedf0"], [1.0, "#196127"]] # 緑
            elif m == "正解数": cs = [[0.0, "#ebedf0"], [1.0, "#0d47a1"]] # 青
            else: cs = [[0.0, "#ebedf0"], [0.5, "#f1c40f"], [1.0, "#27ae60"]] # 黄〜緑

            heat_fig.add_trace(go.Heatmap(
                z=z_matrix, x=list(range(len(z_data[m]))), y=["月","火","水","木","金","土","日"],
                text=h_matrix, hovertemplate="%{text}<extra></extra>",
                colorscale=cs, showscale=False, xgap=3, ygap=3,
                visible=(i==0), name=m
            ))
        # ヒートマップのドロップダウン
        buttons = []
        for i, m in enumerate(metrics):
            vis = [False] * len(metrics)
            vis[i] = True
            buttons.append(dict(
                label=m, method="update",
                args=[{"visible": vis}, {"title": f"【{subj}】学習継続ヒートマップ（{m}）"}]
            ))

        shown_months = {}; tick_vals = []; tick_texts = []
        for i, lbl in enumerate(col_labels):
            if lbl not in shown_months:
                shown_months[lbl] = i; tick_vals.append(i); tick_texts.append(lbl)

        heat_fig.update_layout(
            updatemenus=[dict(active=0, buttons=buttons, x=1.0, y=1.22, xanchor="right", yanchor="top")],
            title=dict(text=f"【{subj}】学習継続ヒートマップ（回答数）", font=dict(size=16)),
            xaxis=dict(tickvals=tick_vals, ticktext=tick_texts, showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False, autorange="reversed"),
            plot_bgcolor="#ffffff", margin=dict(t=80, b=60, l=60, r=40), height=280
        )

        ai_comments = {}
        if with_ai:
            weaknesses_data = self.cfg_data.get("weaknesses", {})
            ai_prompt = f"""あなたは親切で的確な学習コーチです。
科目「{subj}」に関する以下の学習データを分析し、現在の到達度、得意・不得意の傾向、および今後の具体的な学習アドバイスをJSON形式で返してください。

【分析データ】
- 蓄積問題数: {database.count_all_questions(subj)}問
- 分野別正解率: {", ".join(f"{d['label']}({d['format'] or '未設定'}): {round(d['rate']*100,1)}%" for d in radar) if radar else "データなし"}
- 直近7日間の復習予測: {", ".join(f"{d['date']}({d['count']}問)" for d in forecast)}
- 弱点記録: {json.dumps(weaknesses_data, ensure_ascii=False) if weaknesses_data else "なし"}

【出力形式】
※必ず以下のJSON構造のみを出力してください。
{{
  "radar_comment": "分析コメント",
  "radar_advice": "具体的なアドバイス",
  "forecast_comment": "復習予測に対するコメント",
  "forecast_advice": "スケジュールのアドバイス",
  "heatmap_comment": "継続性に関するコメント",
  "heatmap_advice": "習慣化のアドバイス",
  "overall_comment": "全体の総括",
  "overall_advice": "最優先で取り組むべきこと"
}}"""
            try: ai_comments = json.loads(ai_engine.gemini_once_json(ai_prompt))
            except: pass

        # html_builder に組み立てと表示を委譲
        html_builder.open_dashboard_html(
            subj,
            radar_fig.to_html(full_html=False, include_plotlyjs=False),
            bar_fig.to_html(full_html=False, include_plotlyjs=False),
            heat_fig.to_html(full_html=False, include_plotlyjs=False),
            ai_comments,
            with_ai
        )

    def _show_lesson_screen(self, retry_weakness=""):
        self._clear()
        subj, topic = self.current_subject, self.current_topic
        f = tk.Frame(self, bg=BG, padx=20, pady=14)
        f.pack(fill="both", expand=True)

        title_row = tk.Frame(f, bg=BG)
        title_row.pack(fill="x")
        section_label(title_row, f"📖 {subj} ／ {topic['name']}　説明").pack(side="left")

        if retry_weakness:
            _rw_disp = re.sub(r"```python[\s\S]*?```", "（📊 図表あり）", retry_weakness.replace('\\n', '\n'))
            tk.Label(f, text=f"⚠️ 前回の弱点を重点的に説明します: {_rw_disp}", font=FONT_SMALL, bg="#fff3cd", fg="#856404", relief="groove").pack(fill="x", pady=4)

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack(side="bottom", pady=6)
        styled_btn(btn_f, "▶️ 質疑終了 → テスト開始", self._start_test, width=24).pack(side="left", padx=8)
        styled_btn(btn_f, "🔄 説明再作成", lambda: self._regenerate_lesson(retry_weakness), width=14, bg="#5a7a3a").pack(side="left", padx=8)
        styled_btn(btn_f, "🌐 リッチ表示", self._open_lesson_math, width=12, bg="#6a1b9a").pack(side="left", padx=8)
        styled_btn(btn_f, "🎙️ 音声解説(β)", self._open_podcast_overview, width=14, bg="#d84315").pack(side="left", padx=8)
        styled_btn(btn_f, "← メニューへ", self._show_menu_screen, width=14, bg="#888").pack(side="left", padx=8)

        lesson_img_row, self._lesson_img_var = _add_image_attach_ui(f)
        lesson_img_row.pack(side="bottom", fill="x", pady=(2, 0))

        input_frame = tk.Frame(f, bg=BG)
        input_frame.pack(side="bottom", fill="x")
        lesson_inp_frame, self.lesson_input = create_resizable_text(input_frame, width=70, default_height=2)
        lesson_inp_frame.pack(side="left", fill="x", expand=True, padx=(0,8))
        self.lesson_input.bind("<Control-Return>", lambda e: self._lesson_send())
        styled_btn(input_frame, "送信\n(Ctrl+↵)", self._lesson_send, width=8).pack(side="left")

        self.lesson_chat_box = scrolledtext.ScrolledText(f, font=FONT_NORMAL, height=22, state="disabled", relief="solid", wrap="word")
        self.lesson_chat_box.pack(side="top", fill="both", expand=True, pady=6)

        weakness_hint = f"\n今回は特に以下の弱点を重点的に説明してください：{retry_weakness}" if retry_weakness else ""
        notes_val = self.cfg_data.get("notes", "")
        notes_block = f"\n\n【ユーザー指定の留意事項】\n{notes_val}" if notes_val else ""
        if self.cfg_data.get("use_web_search"):
            notes_block += "\n【重要：WEB検索の実行】あなたはGoogle検索機能を利用可能です。上記の「留意事項」に法改正や最新情報の確認指示がある場合は、必ず検索を実行して最新の情報を取得した上で説明・回答を行ってください。"
        rag_name, rag_type = self.cfg_data.get("rag_store_name"), self.cfg_data.get("rag_type", "systematic")

        if rag_name:
            if rag_type == "systematic":
                strict_rule = "【情報源の明記と発展的補足のルール（最重要）】\n回答を作成する際は、以下のルールを厳守してください。\n1. 【基本解説】必ず提供された参考資料(RAG)を検索し、その記述や専門用語を忠実に使って解説してください。資料の内容と矛盾する説明は絶対にしないでください。この部分には必ず「[※テキストより]」と明記してください。\n2. 【発展・補足】ユーザーの理解を深めるため、資料に書かれていない発展的な知識、背景理由、具体例などをあなたの一般常識から補足することは大歓迎です。\n3. 【区別の徹底】ただし、AI自身が補足した発展的な知識の部分には、必ず「[※AIによる発展的な補足]」と明記し、教科書本来の記述と明確に区別できるようにしてください。"
            else:
                strict_rule = "【情報源の明記と補足ルール（最重要）】\n回答を作成する際は、以下のルールを厳守してください。\n1. 提供された参考資料(RAG)の中に解説の根拠となる情報があるか探し、該当箇所がある場合はその内容を最優先して解説し、「[※資料より]」と明記してください。\n2. 資料が断片的で情報が足りない場合や、理解を助けるための背景知識が必要な場合は、あなた自身の正確な一般知識を使って解説を補足してください。\n3. 補足した部分には、必ず「[※AIの一般知識による補足]」と明記してください。"
        else:
            strict_rule = "あなたの持つ正確で一般的な知識に基づいて、わかりやすく説明してください。"

        explain_level = self.cfg_data.get("explain_level", "中学生でも理解できるよう、平易な言葉・具体例を使用するレベル")

        self._lesson_system = f"""あなたは親切で分かりやすいプロ家庭教師の「AiTu」です。
科目「{subj}」の「{topic['name']}」について、以下の手順とルールを厳守して説明を行ってください。

【1. 挨拶のルール】
必ず冒頭で「AiTuです。」と名乗ってください。他の名前や一般的な挨拶は一切使用しないでください。

【2. 説明の手順】
1. 【画像データの確認】まず、提供された「利用可能な画像データ」のリストを確認してください。
2. 【構成】現在のユーザーの知識レベル「{explain_level}」を出発点とし、段階的（ステップバイステップ）に目標の習得レベルまで引き上げる構成を考えてください。
3. 【説明と図解】解説文を作成する際、リスト内に適切な画像があれば `<img src="ファイル名">` を使用して視覚的に説明してください。

【3. 学習支援のルール】
- 難しい概念は省略せず、平易な比喩や前提知識の補足によって理解させてください。
- 重要な暗記事項には、語呂合わせなどの「記憶術」を提示してください。
- 問題を解く際の「時短テクニック」や「解法のコツ」を盛り込んでください。
- 図や表を作成する場合、その中の重要データは必ず本文（テキスト）でも記述してください。{weakness_hint}{notes_block}

【4. 画像・図解の活用】{get_full_media_block(subj, query=topic['name'])}

【5. 情報源と補足のルール】
{strict_rule}

【6. Tkinter表示のための技術的制約】
- 数式のバックスラッシュは必ず2つ（\\）重ねてエスケープしてください。
- 改行は通常の「\\n」を使用してください。
- 新しく図解が必要な場合、提供画像がない時に限り Plotlyコード（```python）を作成してください（matplotlib不可）。
"""

        cached = database.load_explane(subj, topic["id"])
        if cached:
            self.chat_history = [{"role": "user",  "parts": [f"「{topic['name']}」の内容を説明してください。"]}, {"role": "model", "parts": [cached]}]
            self._append_chat(self.lesson_chat_box, "AiTu (保存済み)", cached)
            self.lesson_chat_box.configure(state="normal"); self.lesson_chat_box.see("1.0"); self.lesson_chat_box.configure(state="disabled")
        else:
            self._fetch_and_cache_lesson(retry_weakness)

    def _fetch_and_cache_lesson(self, retry_weakness="", user_request="", prev_text=""):
        subj, topic = self.current_subject, self.current_topic
        self._append_chat(self.lesson_chat_box, "システム", "⏳ 説明を生成中です…")

        def task():
            try:
                user_msg = f"「{topic['name']}」の内容を説明してください。"
                if prev_text: user_msg += f"\n\n【前回の説明文（参考）】\n{prev_text}"
                if user_request: user_msg += f"\n\n【追加の要望・修正指示】\n上記の「前回の説明文」をベースにして、以下の指示に従って再作成してください：\n{user_request}"
                
                reply = ai_engine.gemini_chat(self._lesson_system, [], user_msg, rag_store_name=self.cfg_data.get("rag_store_name"), use_web_search=self.cfg_data.get("use_web_search", False))
                database.save_explane(subj, topic["id"], reply, weakness=retry_weakness)
                self.chat_history = [{"role": "user", "parts": [user_msg]}, {"role": "model", "parts": [reply]}]
                
                self.after(0, lambda: [self.lesson_chat_box.configure(state="normal"), self.lesson_chat_box.delete("1.0", "end"), self.lesson_chat_box.configure(state="disabled"), self._append_chat(self.lesson_chat_box, "AiTu", reply), self.lesson_chat_box.configure(state="normal"), self.lesson_chat_box.see("1.0"), self.lesson_chat_box.configure(state="disabled")])
            except Exception as e:
                self.after(0, lambda err=e: self._append_chat(self.lesson_chat_box, "エラー", str(err)))

        threading.Thread(target=task, daemon=True).start()

    def _regenerate_lesson(self, retry_weakness=""):
        dlg = tk.Toplevel(self)
        dlg.title("説明の再作成")
        dlg.configure(bg=BG)
        dlg.grab_set()
        dlg.resizable(True, True)
        dlg.update_idletasks()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"520x300+{(sw-520)//2}+{(sh-300)//2}")
        
        tk.Label(dlg, text="新しい説明で上書き保存されます。\nどのように修正して再作成してほしいか、要望を入力してください。\n（空欄のまま再作成することも可能です）", font=FONT_NORMAL, bg=BG, justify="left").pack(pady=(15, 5), padx=20, anchor="w")
        text_frame, text_box = create_resizable_text(dlg, width=60, default_height=5)
        text_frame.pack(padx=20, pady=5, fill="both", expand=True)
        text_box.focus_set()
        
        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack(pady=15)
        
        def on_submit():
            user_req = text_box.get("1.0", "end-1c").strip()
            dlg.destroy()
            prev_text = next((h["parts"][0] for h in reversed(self.chat_history) if h["role"] == "model"), "")
            self.chat_history = []
            self.lesson_chat_box.configure(state="normal"); self.lesson_chat_box.delete("1.0", "end"); self.lesson_chat_box.configure(state="disabled")

            media_dir, topic_id = database.get_media_dir(self.current_subject), self.current_topic['id']
            html_path = os.path.join(media_dir, f"podcast_{topic_id}.html")
            if os.path.exists(html_path):
                try: os.remove(html_path)
                except: pass
            for fname in os.listdir(media_dir):
                if fname.startswith(f"podcast_{topic_id}_") and fname.endswith(".mp3"):
                    try: os.remove(os.path.join(media_dir, fname))
                    except: pass
            self._fetch_and_cache_lesson(retry_weakness, user_request=user_req, prev_text=prev_text)
            
        styled_btn(btn_frame, "✅ 再作成する", on_submit, width=16).pack(side="left", padx=10)
        styled_btn(btn_frame, "キャンセル", lambda: dlg.destroy(), width=12, bg="#888").pack(side="left", padx=10)

    def _lesson_send(self):
        msg = self.lesson_input.get("1.0", "end-1c").strip()
        file_paths = list(getattr(self, "_lesson_img_var", []))
        if not msg and not file_paths: return
        self.lesson_input.delete("1.0", "end")
        if hasattr(self, "_lesson_img_var"): self._lesson_img_var.clear()
        display_msg = (msg + (" " if msg and file_paths else "") + " ".join(f"📎[{os.path.basename(p)}]" for p in file_paths)).strip()
        self._append_chat(self.lesson_chat_box, "あなた", display_msg)

        def task():
            try:
                reply = ai_engine.gemini_chat_multimodal(self._lesson_system, self.chat_history, msg, file_paths, self.cfg_data.get("rag_store_name"), self.cfg_data.get("use_web_search", False)) if file_paths else ai_engine.gemini_chat(self._lesson_system, self.chat_history, msg or "（ファイルを確認してください）", self.cfg_data.get("rag_store_name"), self.cfg_data.get("use_web_search", False))
                self.chat_history.extend([{"role": "user", "parts": [display_msg]}, {"role": "model", "parts": [reply]}])
                self.after(0, lambda: self._append_chat(self.lesson_chat_box, "AiTu", reply))
            except Exception as e:
                self.after(0, lambda err=e: self._append_chat(self.lesson_chat_box, "エラー", str(err)))
        threading.Thread(target=task, daemon=True).start()

    def _start_test(self):
        self._clear()
        subj, topic = self.current_subject, self.current_topic
        f = tk.Frame(self, bg=BG, padx=20, pady=14)
        f.pack(fill="both", expand=True)
        section_label(f, f"📝 テスト：{topic['name']}").pack(anchor="w")
        tk.Label(f, text="⏳ 問題を準備中です…", font=FONT_NORMAL, bg=BG, fg="gray").pack(pady=10)
        self.update()

        def generate_test():
            try:
                questions, pool_size = ai_engine.build_test_set(subj, topic["id"], subj, topic["name"], rag_store_name=self.cfg_data.get("rag_store_name"), question_format=self.cfg_data.get("topic_settings", {}).get(topic["id"], "記述式問題"), use_web_search=self.cfg_data.get("use_web_search", False))
                self.after(0, lambda: self._render_test(questions, pool_size))
            except Exception as e:
                self.after(0, lambda err=e: self._show_friendly_error(err, "テスト生成エラー"))
                self.after(0, self._show_menu_screen)
        threading.Thread(target=generate_test, daemon=True).start()

    def _render_test(self, questions, pool_size=0):
        self._clear()
        self.test_questions = questions
        topic = self.current_topic
        f = tk.Frame(self, bg=BG, padx=20, pady=14)
        f.pack(fill="both", expand=True)

        section_label(f, f"📝 テスト：{topic['name']}").pack(anchor="w", pady=(0,4))
        tk.Label(f, text=(f"蓄積問題数: {pool_size}問  ／  " + ("復習4問＋新規1問" if pool_size >= 50 else f"復習{min(1, pool_size)}問＋新規{5 - min(1, pool_size)}問")), font=FONT_SMALL, bg="#eef4fb", fg="#334", relief="groove", padx=6, pady=3).pack(anchor="w", pady=(0,6))

        scroll_frame = tk.Frame(f, bg=BG)
        scroll_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_frame, bg=BG, highlightthickness=0)
        scroll = tk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        inner  = tk.Frame(canvas, bg=BG)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._answer_data = []
        for q in questions:
            disp_text = re.sub(r'(?<!`)\npython\n', '\n```python\n', q["question"].replace('\\n', '\n'))
            display_q = re.sub(r"```python[\s\S]*?```", "\n（📊 図表が含まれています。下の「🌐 リッチ表示」ボタンを押すとブラウザで確認できます）\n", disp_text)
            display_q = re.sub(r"<img[^>]+>", "\n（🖼️ 画像が含まれています。下の「🌐 リッチ表示」ボタンを押すとブラウザで確認できます）\n", display_q, flags=re.IGNORECASE)

            qf = tk.LabelFrame(inner, text=f"問 {q['q']}", font=FONT_BOLD, bg=BG, padx=10, pady=6)
            qf.pack(fill="x", padx=4, pady=6)
            tk.Label(qf, text=display_q, font=FONT_NORMAL, bg=BG, wraplength=750, justify="left").pack(anchor="w")

            # 問題のデータから形式を取得しUIを分岐 ---
            q_fmt = q.get("format", "記述式問題")
            ans_frame = tk.Frame(qf, bg=BG)
            ans_frame.pack(fill="x", pady=4, anchor="w")
            
            ans_var = tk.StringVar(value="未回答")
            ans_txt = None
            
            if q_fmt == "正誤問題":
                for rb_val in ["○ (正しい)", "× (誤り)", "未回答"]:
                    tk.Radiobutton(ans_frame, text=rb_val, variable=ans_var, value=rb_val, bg=BG).pack(side="left", padx=5)
            elif q_fmt == "5肢択一問題":
                for rb_val in ["1", "2", "3", "4", "5", "未回答"]:
                    tk.Radiobutton(ans_frame, text=rb_val, variable=ans_var, value=rb_val, bg=BG).pack(side="left", padx=5)
            else:
                txt_frame, ans_txt = create_resizable_text(ans_frame, width=80, default_height=3)
                txt_frame.pack(fill="x")

            img_row, img_list = _add_image_attach_ui(qf, bg_color=BG)
            img_row.pack(fill="x", pady=(0, 4), anchor="w")
            self._answer_data.append({"text": ans_txt, "var": ans_var, "img": img_list, "fmt": q_fmt})

        btn_f = tk.Frame(inner, bg=BG)
        btn_f.pack(fill="x", padx=4, pady=(4, 12))
        styled_btn(btn_f, "🌐 リッチ表示", self._open_test_math, width=12, bg="#6a1b9a").pack(side="left", padx=8)
        styled_btn(btn_f, "✅ 回答を提出する", self._submit_test, width=22).pack(side="right", padx=8)

    def _submit_test(self):

        # テキストエリアとラジオボタンの値を適切に取得 ---
        def get_ans(d):
            if d["fmt"] in ["正誤問題", "5肢択一問題"]:
                val = d["var"].get()
                return "" if val == "未回答" else val
            return d["text"].get("1.0", "end-1c").strip() if d["text"] else ""

        self.user_answers = [{"text": get_ans(d), "img_path": list(d["img"])} for d in self._answer_data]

        if any(not a["text"] and not a["img_path"] for a in self.user_answers):
            if not messagebox.askyesno("確認", "テキストも画像も入力されていない問いがあります。\nこのまま提出しますか？"): return

        has_images = any(a["img_path"] for a in self.user_answers)
        
        dlg = tk.Toplevel(self)
        dlg.title("採点中")
        dlg.attributes("-topmost", True)
        dlg.grab_set()
        
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"400x150+{(sw-400)//2}+{(sh-150)//2}")
        dlg.configure(bg=BG)
        
        msg = "⏳ Geminiが画像を解析・採点中…" if has_images else "⏳ Geminiが採点・解説中…"
        tk.Label(dlg, text=msg, font=FONT_TITLE, bg=BG).pack(expand=True)
        dlg.update()

        subj, topic = self.current_subject, self.current_topic
        notes_block = f"\n\n【ユーザー指定の留意事項】\n{self.cfg_data.get('notes', '')}" if self.cfg_data.get("notes") else ""
        if self.cfg_data.get("use_web_search"): notes_block += "\n【重要：WEB検索の実行】あなたはGoogle検索機能を利用可能です。上記の「留意事項」に法改正や最新情報の確認指示がある場合は、必ず検索を実行して最新の情報を取得した上で採点・解説を行ってください。"
        lesson_text = database.load_explane(subj, topic["id"]) or ""
        lesson_scope_block = f"\n【絶対の採点基準】\n以下の「説明本文」の内容を正解の絶対基準とします。\n説明本文と矛盾する解説は行わないでください。\n--- 説明本文 ---\n{lesson_text}\n--- ここまで ---\n" if lesson_text else ""

        def grade():
            explain_level = self.cfg_data.get("explain_level", "中学生でも理解できるレベル")

            header = f"""あなたは厳格かつ親切な採点担当の家庭教師です。
科目「{subj}」の「{topic['name']}」のテスト（5問）を、以下の基準に従って採点し、詳細な解説を提供してください。

【1. 利用可能な画像データの確認】
あなたは、この科目のために用意された画像リスト（下記）を持っています。解説を作成する前に、必ずこのリストの内容を確認してください。
{get_full_media_block(subj, query=topic['name'])}

【2. 採点・解説の重要ルール】
1. 【正解基準】{lesson_scope_block} に基づき、その趣旨に合致していれば正解としてください。{notes_block}
2. 【手書き・添付回答の優先】ユーザーが手書き画像や添付ファイルを提出している場合、その内容（数式・図・文字）を最優先で読み取って正誤を判定してください。テキスト回答が空であっても、画像に回答があれば未回答とはせず、その内容で採点してください。
3. 【矛盾判定】ユーザーのテキスト回答と画像回答の内容が明らかに矛盾する場合は、その問いを「採点不能」とし、解説にその旨を記載してください。
4. 【解説の質】「{explain_level}」に合わせた分かりやすい言葉で、正解の根拠や理解を深めるポイントを解説してください。
5. 【画像・図解の積極活用】
   - 解説に図解が必要な場合、提供された画像リストに適切なものがあれば `<img src="ファイル名">` を最優先で使用してください。
   - **[※資料...] や (画像:...) のようなテキスト形式での引用はシステムが読み取れないため「絶対に禁止」です。** 必ずタグ形式で出力してください。
   - 該当画像がない場合に限り、Plotlyを用いたPythonコード（```python 〜 ```）を作成してください（matplotlib不可）。

【3. 技術的制約】
- 数式のバックスラッシュは必ず2つ（\\）重ねてエスケープしてください。
- 改行は通常の「\\n」を使用してください。

--- 採点対象 ---"""
            contents = [header]

            for i, q in enumerate(self.test_questions):
                ans = self.user_answers[i]
                q_fmt = q.get("format", "記述式問題")
                u_ans_raw = ans['text'].strip() if ans['text'] else ""
                has_img = bool(ans["img_path"])

                if not u_ans_raw and not has_img:
                    u_ans_text = "（未回答）"
                elif not u_ans_raw and has_img:
                    u_ans_text = "（テキスト回答なし。添付画像を確認して採点してください）"
                else:
                    u_ans_text = u_ans_raw

                contents.append(f"問{i+1}【出題形式：{q_fmt}】: {q['question']}\n模範解答: {q['answer']}\nユーザー回答（テキスト）: {u_ans_text}")
                for img_path in ans["img_path"]:
                    contents.extend([f"問{i+1} の手書き・添付ファイル：", *ai_engine.file_to_parts(img_path)])

            contents.append(f"""
--- ここまで ---

【出力形式】
※必ず以下のJSON構造のみを出力してください。
{{
  "total_score": 3,
  "results": [
    {{ "q": 1, "correct": true, "interpreted": "画像から読み取った内容（画像がない場合は空文字）", "explanation": "解説文" }}
  ],
  "overall_comment": "総評",
  "weakness": "このテストから読み取れる具体的な弱点（なければ空文字）",
  "recommendation": "今後の進め方（'advance': 先に進む, 'review': 復習を推奨）"
}}""")

            try:
                raw = ai_engine.gemini_once_json_multimodal(contents, use_web_search=self.cfg_data.get("use_web_search", False)) if has_images else ai_engine.gemini_once_json("\n".join(c for c in contents if isinstance(c, str)), use_web_search=self.cfg_data.get("use_web_search", False))
                result = safe_json_loads(raw)
                for res_item in result.get("results", []):
                    if 0 <= (q_no := res_item.get("q", 0) - 1) < len(self.test_questions):
                        if (pool_id := self.test_questions[q_no].get("pool_id")) is not None:
                            database.update_question_result(subj, pool_id, bool(res_item.get("correct", False)), res_item.get("explanation", ""))
                self.after(0, dlg.destroy)
                self.after(0, lambda: self._show_result_screen(result))
            except Exception as e:
                self.after(0, dlg.destroy)
                self.after(0, lambda err=e: self._show_friendly_error(err, "採点エラー"))

        threading.Thread(target=grade, daemon=True).start()

    def _show_result_screen(self, result):
        self._clear()
        subj, topic = self.current_subject, self.current_topic
        cfg = self.cfg_data
        if "progress" not in cfg: cfg["progress"] = {}
        if "weaknesses" not in cfg: cfg["weaknesses"] = {}
        tid, score, rec = topic["id"], min(5, max(0, int(result.get("total_score", 0)))), result.get("recommendation", "advance")
        cfg["progress"][tid] = {"done": True, "score": score, "last_date": datetime.date.today().isoformat()}
        if result.get("weakness"): cfg["weaknesses"][tid] = {"text": result["weakness"], "date": datetime.date.today().isoformat()}
        database.save_cfg(subj, cfg)

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)
        f = self._create_scrollable_container(outer)
        f.configure(padx=20, pady=14)

        section_label(f, f"📊 採点結果：{topic['name']}").pack(anchor="w")
        tk.Label(f, text=f"得点: {score} / 5", font=(_BASE_FONT, 18, "bold"), bg=BG, fg="#2d6a2d" if score >= 4 else "#a05000" if score >= 3 else "#b00020").pack(anchor="w", pady=4)

        def _hide_code(text):
            t = re.sub(r'(?<!`)\npython\n', '\n```python\n', text.replace('\\n', '\n'))
            t = re.sub(r"```python[\s\S]*?```", "\n（📊 図表が含まれています。下の「🌐 リッチ表示」ボタンを押すとブラウザで確認できます）\n", t)
            return re.sub(r"<img[^>]+>", "\n（🖼️ 画像が含まれています。下の「🌐 リッチ表示」ボタンを押すとブラウザで確認できます）\n", t, flags=re.IGNORECASE)

        tk.Label(f, text=_hide_code(result.get("overall_comment", "")), font=FONT_NORMAL, bg="#fffbe6", relief="groove", wraplength=820, justify="left", padx=8, pady=6).pack(fill="x", pady=4)
        if result.get("weakness"): tk.Label(f, text=f"⚠️ 弱点: {_hide_code(result['weakness'])}", font=FONT_NORMAL, bg="#fff3cd", fg="#856404", relief="groove", wraplength=820, padx=8, pady=4).pack(fill="x", pady=2)

        detail_frame = tk.LabelFrame(f, text="各問の解説", font=FONT_BOLD, bg=BG, padx=10, pady=6)
        detail_frame.pack(fill="both", expand=True, pady=(4,2))

        detail_box = scrolledtext.ScrolledText(detail_frame, font=FONT_NORMAL, height=14, state="disabled", relief="solid", wrap="word")
        detail_box.pack(fill="both", expand=True)
        detail_box.configure(state="normal")
        for r in result.get("results", []):
            q_idx = r.get("q", 1) - 1
            if 0 <= q_idx < len(self.test_questions):
                q_text = self.test_questions[q_idx].get("question", "")
                correct_ans = self.test_questions[q_idx].get("answer", "")
                user_ans = self.user_answers[q_idx].get("text", "")
                has_img = bool(self.user_answers[q_idx].get("img_path"))
                
                # AIが画像から読み取ったテキストがあれば表示
                interpreted = r.get("interpreted", "")
                if user_ans:
                    u_ans_disp = user_ans + (f" (画像: {interpreted})" if interpreted else "")
                else:
                    u_ans_disp = f"(画像) {interpreted}" if interpreted else ("（画像回答あり）" if has_img else "（未回答）")
            else:
                q_text, correct_ans, u_ans_disp = "", "", "（未回答）"

            detail_box.insert("end", f"{'✅' if r.get('correct') else '❌'} 問{r.get('q')}：{_hide_code(q_text)}\n   【あなたの回答】{u_ans_disp}\n   【正解】{_hide_code(correct_ans)}\n   【解説】{_hide_code(r.get('explanation', ''))}\n\n")
        detail_box.configure(state="disabled")
        detail_box.see("1.0")

        tk.Label(f, text="解説について質問できます：", font=FONT_SMALL, bg=BG, fg="gray").pack(anchor="w", pady=(10,0))
        self.result_chat_box = scrolledtext.ScrolledText(f, font=FONT_NORMAL, height=6, state="disabled", relief="solid", wrap="word")
        self.result_chat_box.pack(fill="x", pady=(2,2))
        self.test_history = []
        
        self._result_system = f"""あなたは親切で分かりやすいプロ家庭教師の「AiTu」です。
科目「{subj}」の「{topic['name']}」に関するテスト採点結果について、ユーザーの質問に答えてください。

【基本ルール】
1. 必ず冒頭で「AiTuです。」と名乗ってください。
2. 採点結果（{json.dumps(result, ensure_ascii=False)}）の内容に基づき、正解の理由や間違えた原因を丁寧に解説してください。
3. ユーザーの理解度に合わせて、必要に応じて比喩や具体例を交えて説明してください。

【画像・図解の活用】
{get_full_media_block(subj, query=topic['name'])}
- 説明に図解が必要な場合、提供された画像リストに適切なものがあれば `<img src="ファイル名">` を最優先で使用してください。

【Tkinter表示のための技術的制約】
- 図やグラフが必要な際は、必ずPlotlyのPythonコード（```python）を出力してください（matplotlib不可）。
- 数式のバックスラッシュは2つ（\\）重ねてエスケープしてください。
"""

        inp_f = tk.Frame(f, bg=BG)
        inp_f.pack(fill="x", pady=(0,4))
        result_inp_frame, self.result_input = create_resizable_text(inp_f, width=70, default_height=2)
        result_inp_frame.pack(side="left", fill="x", expand=True, padx=(0,8))
        self.result_input.bind("<Control-Return>", lambda e: self._result_send())
        styled_btn(inp_f, "送信\n(Ctrl+↵)", self._result_send, width=8).pack(side="left")

        result_img_row, self._result_img_var = _add_image_attach_ui(f)
        result_img_row.pack(fill="x", pady=(2, 0))

        tk.Label(f, text="先に進むことをお勧めします ➡" if rec == "advance" else "もう一度復習することをお勧めします 🔄", font=FONT_BOLD, bg=BG, fg="#2d6a2d" if rec == "advance" else "#a05000").pack(pady=(12,2))

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack(pady=(2,16))
        styled_btn(btn_f, "📋 問題を表示", self._open_test_math, width=14, bg="#37474f").pack(side="left", padx=4)
        styled_btn(btn_f, "🌐 リッチ表示", lambda: self._open_result_math(result), width=12, bg="#6a1b9a").pack(side="left", padx=4)
        styled_btn(btn_f, "🔄 再学習する", lambda: [self.chat_history.clear(), self._show_lesson_screen(retry_weakness=result.get("weakness", ""))], width=14, bg="#c06000").pack(side="left", padx=4)
        styled_btn(btn_f, "🏠 メニューへ", self._show_menu_screen,  width=16).pack(side="left", padx=4)

    def _open_lesson_math(self):
        subj, topic = self.current_subject, self.current_topic
        texts = [h["parts"][0] for h in self.chat_history if h["role"] == "model"]
        if not texts: return messagebox.showinfo("リッチ表示", "説明が生成されていません。")
        sections = [{"heading": f"{subj} ／ {topic['name']}　説明", "body": texts[0]}]
        for u, m in zip(self.chat_history[2::2], self.chat_history[3::2]):
            if (q := u["parts"][0] if u.get("role") == "user" else "") and (a := m["parts"][0] if m.get("role") == "model" else ""):
                sections.append({"heading": f"Q: {q[:60]}…" if len(q) > 60 else f"Q: {q}", "body": a})
        html_builder.open_math_html(f"{subj} ／ {topic['name']}　説明", sections, subject=subj)

    def _open_podcast_overview(self):
        subj, topic = self.current_subject, self.current_topic
        topic_id = topic['id']
        texts = [h["parts"][0] for h in self.chat_history if h["role"] == "model"]
        if not texts: return messagebox.showinfo("音声解説", "先に説明を生成してください。")

        media_dir = database.get_media_dir(subj)
        html_path = os.path.join(media_dir, f"podcast_{topic_id}.html")
        
        if os.path.exists(html_path):
            return html_builder.open_local_html(html_path)

        dlg = tk.Toplevel(self)
        dlg.title("音声生成中")
        dlg.geometry("380x120")
        dlg.attributes("-topmost", True)
        tk.Label(dlg, text="🎙️ 対話形式の音声解説を生成しています...\n（AI台本作成 ＋ 音声合成）\n数秒〜数十秒かかります。", font=FONT_NORMAL, bg=BG).pack(expand=True)
        dlg.update()

        def task():
            try:
                prompt_sc = f"""あなたは教育系ポッドキャストの優秀な構成作家です。
提供された学習内容を元に、専門家の「先生」と、好奇心旺盛な「生徒」による、楽しくて分かりやすい対話形式のスクリプトを作成してください。

【構成ルール】
- 自然な口語体（話し言葉）で進行し、相槌や驚きなどのリアクションも含めてください。
- 先生は専門用語を分かりやすく噛み砕き、生徒は適宜「つまり、〇〇ってことですか？」と要約・確認を入れてください。
- 1回の対話で1つのポイントを深く掘り下げるようにしてください。

【出力形式】
※必ず以下のJSON配列形式のみを出力してください。
[
  {{ "speaker": "生徒", "text": "..." }},
  {{ "speaker": "先生", "text": "..." }}
]

【解説内容】
{texts[0]}"""
                raw_json = ai_engine.gemini_once_json(prompt_sc)
                script_data = safe_json_loads(raw_json)
                if not isinstance(script_data, list) or len(script_data) == 0: raise ValueError(f"台本の生成に失敗しました")

                import subprocess
                html_script_array = []
                for i, line in enumerate(script_data):
                    if not (text := line.get("text", "").strip()): continue
                    speaker = line.get("speaker", "先生")
                    voice = "ja-JP-KeitaNeural" if "先生" in speaker else "ja-JP-NanamiNeural"
                    mp3_name = f"podcast_{topic_id}_{i}.mp3"
                    mp3_path = os.path.join(media_dir, mp3_name)
                    extra_flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
                    subprocess.run(["edge-tts", "--voice", voice, "--text", text, "--write-media", mp3_path], check=True, **extra_flags)
                    html_script_array.append({"speaker": speaker, "text": text, "audio": mp3_name, "is_teacher": "先生" in speaker})

                html_bubbles = [f'<div class="chat-bubble {"teacher" if item["is_teacher"] else "student"}" id="bubble_{i}"><div class="name">{"👨‍🏫 先生" if item["is_teacher"] else "👩‍🎓 生徒"}</div><div class="message">{item["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")}</div></div>' for i, item in enumerate(html_script_array)]
                js_audio_array = json.dumps([item["audio"] for item in html_script_array], ensure_ascii=False)
                
                # html_builder に組み立てを委譲
                html = html_builder.get_podcast_html(topic["name"], html_bubbles, js_audio_array)

                with open(html_path, "w", encoding="utf-8") as f: f.write(html)
                
                html_builder.open_local_html(html_path)
                self.after(0, dlg.destroy)
            except Exception as e:
                self.after(0, dlg.destroy)
                self.after(0, lambda: messagebox.showerror("エラー", f"音声の生成に失敗しました:\n{e}"))

        threading.Thread(target=task, daemon=True).start()

    def _open_test_math(self):
        topic, subj = self.current_topic, self.current_subject
        sections = [{"heading": f"問 {q['q']}", "body": q["question"]} for q in self.test_questions]
        if not sections: return messagebox.showinfo("リッチ表示", "問題が生成されていません。")
        html_builder.open_math_html(f"テスト：{topic['name']}", sections, subject=subj)

    def _open_result_math(self, result):
        subj, topic = self.current_subject, self.current_topic
        summary = f"**得点: {min(5, max(0, int(result.get('total_score', 0))))} / 5**\n\n{result.get('overall_comment', '')}"
        if result.get("weakness"): summary += f"\n\n⚠️ **弱点:** {result['weakness']}"
        sections = [{"heading": "採点結果サマリー", "body": summary}]
        for r in result.get("results", []):
            q_idx = r.get("q", 1) - 1
            if 0 <= q_idx < len(self.test_questions):
                q_text = self.test_questions[q_idx].get("question", "")
                correct_ans = self.test_questions[q_idx].get("answer", "")
                user_ans = self.user_answers[q_idx].get("text", "")
                has_img = bool(self.user_answers[q_idx].get("img_path"))
                interpreted = r.get("interpreted", "")

                if user_ans:
                    u_ans_disp = user_ans + (f" (画像: {interpreted})" if interpreted else "")
                else:
                    u_ans_disp = f"(画像) {interpreted}" if interpreted else ("（画像回答あり）" if has_img else "（未回答）")
            else:
                q_text, correct_ans, u_ans_disp = "", "", "（未回答）"

            sections.append({"heading": f"問 {r.get('q')}", "body": f"**問題:** {q_text}\n\n**あなたの回答:** {u_ans_disp}\n\n**正解:** {correct_ans}\n\n**結果:** {'✅ 正解' if r.get('correct') else '❌ 不正解'}\n\n**解説:** {r.get('explanation', '')}"})
        html_builder.open_math_html(f"採点結果：{subj} ／ {topic['name']}", sections, subject=subj)

    def _open_review_test_math(self):
        subj = self.current_subject
        sections = [{"heading": f"問 {i+1}", "body": q["question"]} for i, q in enumerate(self._review_questions)]
        if not sections: return messagebox.showinfo("リッチ表示", "問題が生成されていません。")
        html_builder.open_math_html(f"復習テスト：{subj}", sections, subject=subj)

    def _open_review_result_math(self, result, answered):
        total = len(answered)
        try: score = min(total, max(0, int(result.get("total_score", 0))))
        except: score = 0
        sections = [{"heading": "採点結果サマリー", "body": f"**得点: {score} / {total}**\n\n{result.get('overall_comment', '')}"}]
        for i, res in enumerate(result.get("results", [])):
            q_text, correct_ans, user_ans = (answered[i]["q"]["question"], answered[i]["q"]["answer"], answered[i]["user_answer"]) if i < len(answered) else ("", "", "")
            sections.append({"heading": f"問 {res.get('q', i+1)}", "body": f"**問題:** {q_text}\n\n**あなたの回答:** {user_ans if user_ans else '（未回答）'}\n\n**正解:** {correct_ans}\n\n**結果:** {'✅ 正解' if res.get('correct') else '❌ 不正解'}\n\n**解説:** {res.get('explanation', '')}"})
        html_builder.open_math_html(f"復習テスト採点結果：{self.current_subject}", sections, subject=self.current_subject)

    def _result_send(self):
        msg = self.result_input.get("1.0", "end-1c").strip()
        file_paths = list(getattr(self, "_result_img_var", []))
        if not msg and not file_paths: return
        
        self.result_input.delete("1.0", "end")
        if hasattr(self, "_result_img_var"): self._result_img_var.clear()
        display_msg = (msg + (" " if msg and file_paths else "") + " ".join(f"📎[{os.path.basename(p)}]" for p in file_paths)).strip()
        self._append_chat(self.result_chat_box, "あなた", display_msg)

        def task():
            captured_screen_id = self._screen_id
            try:
                # テキストが空で画像がある場合、AIへの指示を補完する
                ai_msg = msg if msg else "（添付ファイルの内容について確認・回答してください）"
                reply = ai_engine.gemini_chat_multimodal(self._result_system, self.test_history, ai_msg, file_paths, self.cfg_data.get("rag_store_name"), self.cfg_data.get("use_web_search", False)) if file_paths else ai_engine.gemini_chat(self._result_system, self.test_history, msg or "（ファイルを確認してください）", self.cfg_data.get("rag_store_name"), self.cfg_data.get("use_web_search", False))
                self.test_history.extend([{"role": "user",  "parts": [display_msg]}, {"role": "model", "parts": [reply]}])
                if self._screen_id == captured_screen_id: self.after(0, lambda: self._append_chat(self.result_chat_box, "AiTu", reply))
            except Exception as e:
                if self._screen_id == captured_screen_id: self.after(0, lambda err=e: self._append_chat(self.result_chat_box, "エラー", str(err)))
        threading.Thread(target=task, daemon=True).start()

    def _show_free_chat_screen(self):
        self._clear()
        subj = self.current_subject
        cfg = self.cfg_data
        rag_name, notes_val, explain_level = cfg.get("rag_store_name"), cfg.get("notes", ""), cfg.get("explain_level", "中学生でも理解できるレベル")
        rag_type = cfg.get("rag_type", "systematic")

        notes_val_block = f"【留意事項】\n{notes_val}" if notes_val else ""
        web_search_block = "【重要：WEB検索の実行】あなたはGoogle検索機能を利用可能です。最新情報の確認指示がある場合は、必ず検索を実行して回答してください。" if cfg.get("use_web_search") else ""
        rag_rule_block = ""
        if rag_name:
            if rag_type == "systematic":
                rag_rule_block = "【情報源の明記ルール】\n1. 【基本解説】必ず提供された参考資料(RAG)を検索し、その記述を優先して「[※テキストより]」と明記してください。\n2. 【発展・補足】資料にない発展的な知識は「[※AIによる補足]」と明記して区別してください。"
            else:
                rag_rule_block = "【情報源の明記ルール】\n1. 参考資料(RAG)の内容を優先し、「[※資料より]」と明記してください。\n2. 不足部分はAIの一般知識で補い、「[※AIの一般知識による補足]」と明記してください。"
        
        if not hasattr(self, "free_chat_history"): self.free_chat_history = []

        self._free_chat_system = f"""あなたは親切で知識豊富なプロ家庭教師の「AiTu」です。
科目「{subj}」に関するユーザーの質問に対し、以下のルールを守って回答してください。

【基本ルール】
1. 必ず冒頭で「AiTuです。」と名乗ってください。
2. 回答は「{explain_level}」に合わせた語彙と深さで行ってください。
3. ユーザーの質問に対し、まずは結論を述べ、その後に具体的な理由や例を挙げてください。

【画像・図解の活用】
{get_full_media_block(subj, query=subj)}
- 説明に適切な画像がリスト内にあれば `<img src="ファイル名">` を積極的に使用してください。
- 適切な画像がない場合で、図表が必要な際に限り PlotlyのPythonコード（```python）を作成してください。

【情報源のルール】
{notes_val_block}
{rag_rule_block}
{web_search_block}

【Tkinter表示のための技術的制約】
- 数式のバックスラッシュは2つ（\\）重ねてエスケープしてください。
- 改行は通常の「\\n」を使用してください。
"""
        
        f = tk.Frame(self, bg=BG, padx=20, pady=14)
        f.pack(fill="both", expand=True)

        hdr_row = tk.Frame(f, bg=BG)
        hdr_row.pack(fill="x", pady=(0, 4))
        section_label(hdr_row, f"💬 自由質問：{subj}").pack(side="left")
        tk.Label(hdr_row, text="  ✅ RAG有効" if rag_name else "  RAGなし", font=FONT_SMALL, bg=BG, fg="#2e7d32" if rag_name else "#888").pack(side="left", padx=8)

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack(side="bottom", pady=6)

        def on_rich():
            if not self.free_chat_history: return messagebox.showinfo("リッチ表示", "まだ会話がありません。")
            html_builder.open_math_html(f"自由質問：{subj}", [{"heading": "あなた" if h["role"] == "user" else "AiTu", "body": h["parts"][0]} for h in self.free_chat_history], subject=subj)

        def on_clear():
            if messagebox.askyesno("会話クリア", "この画面の会話履歴をすべてクリアしますか？"):
                self.free_chat_history = []; self.free_chat_box.configure(state="normal"); self.free_chat_box.delete("1.0", "end"); self.free_chat_box.configure(state="disabled")

        styled_btn(btn_f, "🌐 リッチ表示",   on_rich,  width=14, bg="#6a1b9a").pack(side="left", padx=4)
        styled_btn(btn_f, "🗑 会話クリア",   on_clear, width=14, bg="#c06000").pack(side="left", padx=4)
        styled_btn(btn_f, "← 学習メニューへ", self._show_menu_screen, width=18, bg="#888").pack(side="left", padx=4)

        free_img_row, self._free_chat_img_var = _add_image_attach_ui(f)
        free_img_row.pack(side="bottom", fill="x", pady=(2, 0))

        input_frame = tk.Frame(f, bg=BG)
        input_frame.pack(side="bottom", fill="x")
        free_inp_frame, self.free_chat_input = create_resizable_text(input_frame, width=70, default_height=3)
        free_inp_frame.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.free_chat_input.bind("<Control-Return>", lambda e: self._free_chat_send())
        styled_btn(input_frame, "送信\n(Ctrl+↵)", self._free_chat_send, width=8).pack(side="left")

        self.free_chat_box = scrolledtext.ScrolledText(f, font=FONT_NORMAL, height=16, state="disabled", relief="solid", wrap="word")
        self.free_chat_box.pack(side="top", fill="both", expand=True, pady=6)

        for h in self.free_chat_history:
            self._append_chat(self.free_chat_box, "あなた" if h["role"] == "user" else "AiTu", h["parts"][0])

    def _free_chat_send(self):
        msg = self.free_chat_input.get("1.0", "end-1c").strip()
        file_paths = list(getattr(self, "_free_chat_img_var", []))
        if not msg and not file_paths: return

        self.free_chat_input.delete("1.0", "end")
        if hasattr(self, "_free_chat_img_var"): self._free_chat_img_var.clear()
        display_msg = (msg + (" " if msg and file_paths else "") + " ".join(f"📎[{os.path.basename(p)}]" for p in file_paths)).strip()
        self._append_chat(self.free_chat_box, "あなた", display_msg)

        def task():
            captured_screen_id = self._screen_id
            try:
                # テキストが空で画像がある場合、AIへの指示を補完する
                ai_msg = msg if msg else "（添付ファイルの内容について確認・回答してください）"
                reply = ai_engine.gemini_chat_multimodal(self._free_chat_system, self.free_chat_history, ai_msg, file_paths, self.cfg_data.get("rag_store_name"), self.cfg_data.get("use_web_search", False)) if file_paths else ai_engine.gemini_chat(self._free_chat_system, self.free_chat_history, msg or "（ファイルを確認してください）", self.cfg_data.get("rag_store_name"), self.cfg_data.get("use_web_search", False))
                self.free_chat_history.extend([{"role": "user", "parts": [display_msg]}, {"role": "model", "parts": [reply]}])
                if self._screen_id == captured_screen_id: self.after(0, lambda: self._append_chat(self.free_chat_box, "AiTu", reply))
            except Exception as e:
                if self._screen_id == captured_screen_id: self.after(0, lambda err=e: self._append_chat(self.free_chat_box, "エラー", str(err)))
        threading.Thread(target=task, daemon=True).start()

    def _clear(self):
        self._screen_id += 1
        for w in self.winfo_children(): w.destroy()

    def _show_friendly_error(self, e: Exception, title: str = "エラー"):
        err_str = str(e).lower()
        if "503 unavailable" in err_str or "high demand" in err_str or "overloaded" in err_str:
            msg = "Geminiのサーバーが現在大変混み合っています。\n数分待ってから、もう一度お試しください。\n(503 Unavailable)"
        elif "429" in err_str or "quota" in err_str or "exhausted" in err_str:
            msg = "APIの利用制限（リクエスト上限）に達しました。\nしばらく時間を置くか、APIの設定を確認してください。\n(429 Too Many Requests)"
        elif "500 internal" in err_str:
            msg = "Geminiのサーバー側で一時的なエラーが発生しました。\n時間をおいて再度お試しください。\n(500 Internal Server Error)"
        elif "network" in err_str or "connection" in err_str or "timeout" in err_str:
            msg = "通信エラーが発生しました。\nインターネット環境を確認して、もう一度お試しください。"
        elif "400" in err_str or "bad request" in err_str:
            msg = "リクエストが不正です（400 Bad Request）。\n画像やファイルの形式が対応していない可能性があります。"
        else:
            msg = f"予期せぬエラーが発生しました:\n{str(e)[:250]}..."
        messagebox.showerror(title, msg)

    def _append_chat(self, box: scrolledtext.ScrolledText, speaker: str, msg: str):
        disp_msg = re.sub(r'(?<!`)\npython\n', '\n```python\n', msg.replace('\\n', '\n'))
        disp_msg = re.sub(r"```python[\s\S]*?```", "\n（📊 図表が含まれています。下の「🌐 リッチ表示」ボタンを押すとブラウザで確認できます）\n", disp_msg)
        disp_msg = re.sub(r"<img[^>]+>", "\n（🖼️ 画像が含まれています。下の「🌐 リッチ表示」ボタンを押すとブラウザで確認できます）\n", disp_msg, flags=re.IGNORECASE)
        box.configure(state="normal")
        box.insert("end", f"【{speaker}】\n{disp_msg}\n\n")
        box.see("end")
        box.configure(state="disabled")

try:
    import plotly          # noqa: F401
    import plotly.graph_objects  # noqa: F401
except ImportError:
    pass
try:
    import markdown        # noqa: F401
except ImportError:
    pass
try:
    from PIL import Image  # noqa: F401
except ImportError:
    pass

if __name__ == "__main__":
    import os
    import json
    import sys

    base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    CONFIG_FILE = os.path.join(base_dir, "app_config.json")
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key and os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                api_key = json.load(f).get("GEMINI_API_KEY")
        except Exception: pass

    if not api_key or api_key == "YOUR_API_KEY_HERE":
        import tkinter.simpledialog as sd
        root = tk.Tk(); root.eval('tk::PlaceWindow . center'); root.attributes("-topmost", True); root.withdraw()
        key = sd.askstring("API キー", "Gemini API キーを入力してください：\n（次回から入力不要になります）", parent=root)
        root.destroy()

        if not key:
            print("APIキーが入力されませんでした。終了します。")
            exit()
        api_key = key
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump({"GEMINI_API_KEY": api_key}, f)
        except Exception as e: print(f"キーの保存に失敗しました: {e}")

    ai_engine.set_api_key(api_key)
    app = TutorApp()
    app.mainloop()