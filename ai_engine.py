# Copyright (c) 2026 Datan (データン)
# Licensed under a Custom Hybrid License (Free for Individuals, Paid for Commercial).
# See README.md for licensing details.
# -*- coding: utf-8 -*-
"""
=======================================================
  ai_engine.py (ビジネスロジック層)
  UIに依存しないGemini API通信、 ファイル解析、テキスト処理を担当
=======================================================
"""

import os
import json
import re
import time
from google import genai
from google.genai import types

try:
    from PIL import Image as _PIL_Image
    HAS_PIL = True
except ImportError:
    _PIL_Image = None
    HAS_PIL = False

# =====================================================
#  API キー設定とクライアント管理
# =====================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")
GEMINI_MODEL   = "gemini-3.1-flash-lite-preview"  # デフォルトモデル（必要に応じて変更可能）
GEMINI_EMBEDDING_MODEL = "models/gemini-embedding-001" # デフォルトエンベディングモデル

_client: genai.Client = None

def get_client() -> genai.Client:
    """Geminiクライアントをシングルトンで取得"""
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client

def set_api_key(api_key: str):
    """外部(UI側)からAPIキーを動的に設定するためのヘルパー"""
    global GEMINI_API_KEY, _client
    GEMINI_API_KEY = api_key
    _client = None  # クライアントを再初期化させる

def set_model(model_code: str):
    """外部(UI側)からGeminiモデルコードを動的に変更するためのヘルパー"""
    global GEMINI_MODEL
    if model_code and model_code.strip():
        GEMINI_MODEL = model_code.strip()

def set_embedding_model(model_code: str):
    """外部(UI側)からEmbeddingモデルコードを動的に変更するためのヘルパー"""
    global GEMINI_EMBEDDING_MODEL
    if model_code and model_code.strip():
        GEMINI_EMBEDDING_MODEL = model_code.strip()

def get_model() -> str:
    """現在設定されているGeminiモデルコードを返す"""
    return GEMINI_MODEL

def get_embedding_model() -> str:
    """現在設定されているEmbeddingモデルコードを返す"""
    return GEMINI_EMBEDDING_MODEL

def get_embedding(text: str, max_retries=3) -> list:
    """Gemini APIを使用してテキストのベクトル（Embedding）を生成する"""
    if not text or not text.strip():
        return []
    client = get_client()
    for i in range(max_retries):
        try:
            # 設定されたモデル（デフォルト：gemini-embedding-001）を使用
            result = client.models.embed_content(
                model=GEMINI_EMBEDDING_MODEL,
                contents=text
            )
            return result.embeddings[0].values
        except Exception as e:
            err_str = str(e).upper()
            if "503" in err_str or "UNAVAILABLE" in err_str or "HIGH DEMAND" in err_str:
                if i < max_retries - 1:
                    wait_time = (i + 1) * 2
                    print(f"Embedding生成API混雑のため{wait_time}秒後にリトライします({i+1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
            print(f"Embedding生成エラー: {e}")
            return []
    return []

def find_top_relevant_images(query: str, media_list: list, top_n: int = 10) -> list:
    """クエリベクトルと各画像のベクトルのコサイン類似度を計算し、上位N件を返す"""
    if not query or not media_list:
        return media_list[:top_n]
    
    query_emb = get_embedding(query)
    if not query_emb:
        return media_list[:top_n]
    
    import math
    def cosine_similarity(v1, v2):
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        dot_product = sum(a * b for a, b in zip(v1, v2))
        magnitude1 = math.sqrt(sum(a * a for a in v1))
        magnitude2 = math.sqrt(sum(a * a for a in v2))
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        return dot_product / (magnitude1 * magnitude2)

    # 各画像との類似度を計算
    scored_media = []
    for m in media_list:
        score = cosine_similarity(query_emb, m.get("embedding"))
        scored_media.append({"filename": m["filename"], "summary": m["summary"], "score": score})
    
    # 類似度の降順でソートして上位を返す
    scored_media.sort(key=lambda x: x["score"], reverse=True)
    return scored_media[:top_n]

# =====================================================
#  Gemini API 通信ロジック
# =====================================================
def get_file_search_stores():
    """APIから File Search Store の一覧を取得して返す"""
    client = get_client()
    try:
        stores = client.file_search_stores.list()
        return [{"name": s.name, "display": s.display_name or s.name} for s in stores]
    except Exception as e:
        print(f"Store取得エラー: {e}")
        return []

def _build_config(system_prompt=None, response_mime_type=None, rag_store_name=None, use_web_search: bool = False):
    """GenerateContentConfig を組み立てる共通関数。
    ・use_web_search=True の場合、Google Search ツールをリストに追加する。
    ・RAG(rag_store_name) と tools は共存可能なので両方あればリストに積む。
    ・tools が 1 つでも存在する場合は response_mime_type を外す
      （Gemini API は tools と response_mime_type の同時指定を拒否するため）。
    """
    kwargs = {}
    if system_prompt:
        kwargs["system_instruction"] = system_prompt

    tools = []

    # WEB検索ツールを追加（Google Search grounding）
    if use_web_search:
        tools.append({"google_search": {}})

    # RAG（ファイル検索）ツールを追加
    if rag_store_name:
        tools.append(
            types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=[rag_store_name]
                )
            )
        )

    if tools:
        kwargs["tools"] = tools
        # ※ tools と response_mime_type は競合するため、tools がある場合は mime_type を外す
        #   JSON出力が必要な関数は、プロンプト側で JSON 出力を強く指示することで対応
    elif response_mime_type:
        kwargs["response_mime_type"] = response_mime_type

    return types.GenerateContentConfig(**kwargs)

def _generate_content_with_retry(client, model, contents, config=None, max_retries=3):
    """503エラー(UNAVAILABLE/High Demand)に対してリトライを行うラッパー"""
    for i in range(max_retries):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            err_str = str(e).upper()
            if "503" in err_str or "UNAVAILABLE" in err_str or "HIGH DEMAND" in err_str:
                if i < max_retries - 1:
                    wait_time = (i + 1) * 3
                    print(f"API混雑(503)のため{wait_time}秒後にリトライします({i+1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
            raise e

def gemini_chat(system_prompt: str, history: list, user_msg: str, rag_store_name: str = None, use_web_search: bool = False) -> str:
    """チャット履歴を含めた文章生成（テキストのみ）"""
    client = get_client()
    contents = []
    for h in history:
        role  = h["role"]
        parts = h["parts"]
        contents.append(
            types.Content(role=role, parts=[types.Part(text=p) for p in parts])
        )
    contents.append(
        types.Content(role="user", parts=[types.Part(text=user_msg)])
    )
    config = _build_config(system_prompt=system_prompt, rag_store_name=rag_store_name, use_web_search=use_web_search)
    response = _generate_content_with_retry(
        client=client,
        model=GEMINI_MODEL,
        contents=contents,
        config=config,
    )
    return response.text

def gemini_chat_multimodal(system_prompt: str, history: list, user_msg: str, file_paths: list, rag_store_name: str = None, use_web_search: bool = False) -> str:
    """チャット履歴＋画像等のファイルを含めた文章生成（UI層からの呼び出しをシンプルにするための統合関数）"""
    client = get_client()
    contents = []
    
    # 過去の履歴を構築
    for h in history:
        contents.append(
            types.Content(role=h["role"], parts=[types.Part(text=p) for p in h["parts"]])
        )
        
    # 今回のユーザー入力（テキスト＋ファイル）を構築
    user_parts = [types.Part(text=user_msg)] if user_msg else []
    for fp in file_paths:
        user_parts.extend(file_to_parts(fp))
        
    contents.append(types.Content(role="user", parts=user_parts))
    
    config = _build_config(system_prompt=system_prompt, rag_store_name=rag_store_name, use_web_search=use_web_search)
    response = _generate_content_with_retry(
        client=client,
        model=GEMINI_MODEL,
        contents=contents,
        config=config,
    )
    return response.text

def gemini_once(prompt: str, rag_store_name: str = None, use_web_search: bool = False) -> str:
    """単発の文章生成（テキスト）"""
    client = get_client()
    config = _build_config(rag_store_name=rag_store_name, use_web_search=use_web_search)
    response = _generate_content_with_retry(
        client=client,
        model=GEMINI_MODEL,
        contents=prompt,
        config=config,
    )
    return response.text

def _extract_json(raw: str) -> str:
    """
    APIレスポンスからJSON文字列を安全に抽出する。
    ・内部の ```python などに誤反応しないよう改善。
    ・JSON文字列値内の改行・制御文字を安全にエスケープして
      Extra data / Unterminated string 系エラーを防ぐ。
    """
    raw = raw.strip()

    # 1. まずそのままJSONとして成立しているかチェック
    try:
        json.loads(raw)
        return raw
    except Exception:
        pass

    # 2. ```json ブロックを厳密に探す（```python を無視）
    m = re.search(r"```json\s*([\s\S]*?)```", raw)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass

    # 3. 最初の { または [ から対応する閉じ括弧までを抽出する
    #    （JSON の外側に余分テキストが付いている "Extra data" ケースに対処）
    for start_ch, end_ch in [('{', '}'), ('[', ']')]:
        start = raw.find(start_ch)
        end   = raw.rfind(end_ch)
        if start != -1 and end != -1 and end > start:
            candidate = raw[start:end + 1]
            try:
                json.loads(candidate)
                return candidate
            except Exception:
                pass

    # 4. それでも失敗する場合：JSON文字列値内の生の改行・制御文字を
    #    エスケープして再試行する（コードブロック混入ケース）
    def _sanitize_json_strings(text: str) -> str:
        """JSON文字列値（"..."）内にある生の改行・タブ・制御文字をエスケープする"""
        result = []
        in_string = False
        escape_next = False
        for ch in text:
            if escape_next:
                result.append(ch)
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                result.append(ch)
                continue
            if ch == '"':
                in_string = not in_string
                result.append(ch)
                continue
            if in_string:
                if ch == '\n':
                    result.append('\\n')
                elif ch == '\r':
                    result.append('\\r')
                elif ch == '\t':
                    result.append('\\t')
                else:
                    result.append(ch)
            else:
                result.append(ch)
        return ''.join(result)

    for start_ch, end_ch in [('{', '}'), ('[', ']')]:
        start = raw.find(start_ch)
        end   = raw.rfind(end_ch)
        if start != -1 and end != -1 and end > start:
            candidate = _sanitize_json_strings(raw[start:end + 1])
            try:
                json.loads(candidate)
                return candidate
            except Exception:
                pass

    # どれにも引っかからなければそのまま返す（呼び出し元で例外になる）
    return raw


def gemini_once_json(prompt: str, rag_store_name: str = None, use_web_search: bool = False) -> str:
    """単発の文章生成（JSON出力）。Markdownコードブロックが混入しても安全にJSONを抽出する。
    ・rag_store_name が指定された場合は RAG（ファイル検索）を有効にする。
    ・tools（RAG / WEB検索）が 1 つでも存在する場合は response_mime_type と競合するため、
      プロンプトで JSON 出力を強く指示する方式に切り替える。
    """
    client = get_client()
    has_tools = use_web_search or bool(rag_store_name)
    if has_tools:
        # tools 使用時は response_mime_type が使えないため、プロンプト指示で JSON を強制する
        web_json_instruction = "\n\n【重要】あなたの回答は必ず純粋なJSONのみとし、説明文・Markdownコードブロック・バッククォートは一切含めないでください。"
        config = _build_config(rag_store_name=rag_store_name, use_web_search=use_web_search)
        response = _generate_content_with_retry(
            client=client,
            model=GEMINI_MODEL,
            contents=prompt + web_json_instruction,
            config=config,
        )
    else:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
        )
        response = _generate_content_with_retry(
            client=client,
            model=GEMINI_MODEL,
            contents=prompt,
            config=config,
        )
    return _extract_json(response.text)

def gemini_once_json_multimodal(contents_list: list, use_web_search: bool = False) -> str:
    """テキスト・画像(types.Part)が混在するリストを受け取りJSONを返す（マルチモーダル採点用）
    use_web_search=True の場合は response_mime_type を外してプロンプトで JSON を強制する。
    """
    client = get_client()
    
    # 全ての要素を types.Part に正規化する
    parts = []
    for item in contents_list:
        if isinstance(item, str):
            parts.append(types.Part(text=item))
        elif isinstance(item, types.Part):
            parts.append(item)
        elif isinstance(item, list):
            # リスト（file_to_partsの戻り値など）が含まれる場合のフラット化
            for sub in item:
                if isinstance(sub, str):
                    parts.append(types.Part(text=sub))
                else:
                    parts.append(sub)

    if use_web_search:
        web_json_instruction = "\n\n【重要】あなたの回答は必ず純粋なJSONのみとし、説明文・Markdownコードブロック・バッククォートは一切含めないでください。"
        parts.append(types.Part(text=web_json_instruction))
        config = _build_config(use_web_search=True)
    else:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
        )

    # 単一のユーザーメッセージ(Content)として組み立てて送信
    response = _generate_content_with_retry(
        client=client,
        model=GEMINI_MODEL,
        contents=[types.Content(role="user", parts=parts)],
        config=config,
    )
    return _extract_json(response.text)

def analyze_image_for_summary(file_path: str) -> str:
    """画像をGeminiに読み込ませ、その内容を要約して返す"""
    ext = os.path.splitext(file_path)[1].lower()
    # 解析対象の主要な画像フォーマットを指定
    if ext not in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
        return ""

    # 2. プロンプト準備
    prompt = """この画像を解析し、以下の情報を整理してください。
1. この画像は何を説明しているものか（例：燃焼の三要素の概念図）
2. 画像内に含まれる重要なキーワード
3. どのような学習テーマの時にこの画像を提示すべきか

AIが説明文の中でこの画像を引用しやすくするために、具体的かつ簡潔に記述してください。"""

    parts = file_to_parts(file_path)
    if not parts:
        return ""
    # テキストプロンプトを先頭に追加
    parts.insert(0, types.Part(text=prompt))

    client = get_client()
    try:
        response = _generate_content_with_retry(
            client=client,
            model=GEMINI_MODEL,
            contents=[types.Content(role="user", parts=parts)]
        )
        return response.text.strip()
    except Exception as e:
        print(f"画像要約エラー ({file_path}): {e}")
        return ""

# =====================================================
#  ファイル・画像処理ロジック
# =====================================================
def _pil_to_bytes(pil_img, fmt="JPEG") -> bytes:
    import io
    buf = io.BytesIO()
    if fmt == "JPEG" and pil_img.mode in ("RGBA", "P", "LA"):
        pil_img = pil_img.convert("RGB")
    pil_img.save(buf, format=fmt)
    return buf.getvalue()

_MIME_MAP = {
    ".png":  "image/png", ".jpg":  "image/jpeg", ".jpeg": "image/jpeg", ".gif":  "image/gif",
    ".bmp":  "image/bmp", ".webp": "image/webp", ".pdf":  "application/pdf",
    ".txt":  "text/plain", ".md":   "text/plain", ".csv":  "text/plain", ".py":   "text/plain",
    ".js":   "text/plain", ".ts":   "text/plain", ".html": "text/plain", ".css":  "text/plain",
    ".json": "text/plain", ".xml":  "text/plain", ".yaml": "text/plain", ".yml":  "text/plain",
    ".mp3":  "audio/mpeg", ".wav":  "audio/wav", ".m4a":  "audio/mp4", ".aac":  "audio/aac", ".flac": "audio/flac",
    ".mp4":  "video/mp4", ".mov":  "video/quicktime", ".avi":  "video/avi", ".mkv":  "video/x-matroska", ".webm": "video/webm",
}
_TEXT_EXTS = {".txt", ".md", ".csv", ".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml", ".yml"}

def file_to_parts(file_path: str) -> list:
    """ローカルファイルをGemini API用のPartオブジェクトに変換する"""
    import os, io
    ext = os.path.splitext(file_path)[1].lower()
    mime = _MIME_MAP.get(ext, "application/octet-stream")
    fname = os.path.basename(file_path)

    if ext in _TEXT_EXTS:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as fp:
                text_content = fp.read()
            header  = f"--- 添付ファイル: {fname} ---"
            footer  = "--- ここまで ---"
            return [types.Part(text=header + "\n" + text_content + "\n" + footer)]
        except Exception as e:
            return [types.Part(text=f"（ファイル読み込みエラー: {fname}: {e}）")]

    if mime.startswith("image/"):
        if HAS_PIL and _PIL_Image:
            try:
                pil_img = _PIL_Image.open(file_path)
                data = _pil_to_bytes(pil_img)
                return [types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=data))]
            except Exception as e:
                return [types.Part(text=f"（画像読み込みエラー: {fname}: {e}）")]
        else:
            return [types.Part(text=f"（Pillow未インストールのため画像を添付できませんでした: {fname}）")]

    try:
        with open(file_path, "rb") as fp:
            data = fp.read()
        return [types.Part(inline_data=types.Blob(mime_type=mime, data=data))]
    except Exception as e:
        return [types.Part(text=f"（ファイル読み込みエラー: {fname}: {e}）")]

# =====================================================
#  テキスト整形・パース処理 (UI非依存)
# =====================================================
def fix_plotly_code(code: str) -> str:
    """AIが生成したPlotlyコードのよくあるミスを自動修正する"""
    valid_mode_flags = {"lines", "markers", "text", "none"}
    def fix_mode(m):
        quote = m.group(1)
        mode_val = m.group(2)
        flags = [f.strip() for f in mode_val.split("+")]
        cleaned = [f for f in flags if f in valid_mode_flags]
        new_mode = "+".join(cleaned) if cleaned else "lines"
        return f"mode={quote}{new_mode}{quote}"
    code = re.sub(r'(?<!\w)mode=([\'"])([^\'"]+)\1', fix_mode, code)

    def fix_fill(m):
        quote = m.group(1)
        val = m.group(2)
        typo_map = {"self": "toself", "tonext": "tonexty"}
        fixed = typo_map.get(val, val)
        return f"fill={quote}{fixed}{quote}"
    code = re.sub(r"(?<!\w)fill=(['\"])([^'\"]*)\1", fix_fill, code)

    return code

def extract_plotly_blocks(text: str):
    """テキスト中のPlotlyコードブロックを検出し、HTML断片に変換する"""
    import io, sys, contextlib, traceback as _tb

    plotly_ph = {}
    ctr = [0]

    def replace_plotly(m):
        code = m.group(1)
        if "plotly" not in code and "go.Figure" not in code:
            return m.group(0)
        try:
            patched = re.sub(r"\bfig\.show\(\)", "pass  # fig.show() disabled", code)
            patched = fix_plotly_code(patched)

            # ▼ AIのよくあるタイポを強制的に修正（サニタイズ） ▼
            # constrains= → constrain=
            patched = patched.replace("constrains=", "constrain=")
            patched = patched.replace("constrains='", "constrain='")
            patched = patched.replace('constrains="', 'constrain="')
            # bargaps= → bargap=
            patched = patched.replace("bargaps=", "bargap=")
            # xaxis_titles= → xaxis_title=
            patched = patched.replace("xaxis_titles=", "xaxis_title=")
            # yaxis_titles= → yaxis_title=
            patched = patched.replace("yaxis_titles=", "yaxis_title=")
            # color_discrete_sequences= → color_discrete_sequence=
            patched = patched.replace("color_discrete_sequences=", "color_discrete_sequence=")

            # --- ▼ 修正：安全な実行環境の構築とFigure探索の強化 ▼ ---
            import plotly.graph_objects as go
            import pandas as pd
            try:
                import plotly.express as px
            except ImportError:
                px = None
            try:
                import numpy as np
            except ImportError:
                np = None

            exec_env = {
                "go": go,
                "pd": pd,
                "__builtins__": __builtins__
            }
            if px: exec_env["px"] = px
            if np: exec_env["np"] = np

            ns = {}
            # AIが生成したコードにライブラリ環境を渡して実行
            exec(patched, exec_env, ns)  # noqa: S102
            
            # 変数名が 'fig' 以外の場合（AIの命名ブレ）もPlotlyオブジェクトを探索
            fig = ns.get("fig")
            if fig is None:
                for v in ns.values():
                    if isinstance(v, go.Figure):
                        fig = v
                        break
                        
            if fig is None:
                raise ValueError("Plotly Figure オブジェクトが見つかりませんでした。")
            # --- ▲ ここまで ▲ ---

            chart_html = fig.to_html(full_html=False, include_plotlyjs=False)
            k = f"XPLOTLYPHX{ctr[0]}XENDX"
            plotly_ph[k] = f'<div class="plotly-chart">{chart_html}</div>'
            ctr[0] += 1
            return k
        except Exception as e:
            err_msg = _tb.format_exc(limit=3).replace("<", "&lt;").replace(">", "&gt;")
            k = f"XPLOTLYPHX{ctr[0]}XENDX"
            plotly_ph[k] = (
                f'<details class="plotly-error"><summary>? Plotly 実行エラー</summary>'
                f'<pre>{err_msg}</pre>'
                f'<pre>{code}</pre></details>'
            )
            ctr[0] += 1
            return k

    text = re.sub(r"```(?:python)?\s*\n([\s\S]*?)```", replace_plotly, text)
    return text, plotly_ph


def md_to_html(text: str, subject: str = None) -> str:
    """Markdown + 数式(MathJax) + Plotly コードブロックを HTML に変換する。
    subject を指定すると Anki メディア画像のパスも自動補正する。
    """
    import re

    # ── ① Plotly コードブロックを先に HTML 化 ──
    text, plotly_ph = extract_plotly_blocks(text)

    # ── ② 数式をプレースホルダーで保護 ──
    ph = {}
    ctr = [0]
    def save(m):
        k = f"XMATHPLACEHOLDERX{ctr[0]}XENDX"
        ph[k] = m.group(0)
        ctr[0] += 1
        return k
    text = re.sub(r"\$\$[\s\S]*?\$\$", save, text)
    text = re.sub(r"\$[^\$\n]+?\$",    save, text)

    # ── ③ Markdown → HTML ──
    try:
        import markdown as _markdown
        md = _markdown.Markdown(extensions=["extra", "nl2br", "sane_lists"], extension_configs={"extra": {}})
        html = md.convert(text)
    except ImportError:
        html = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         html)
        html = re.sub(r"^#{1,3}\s+(.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
        html = html.replace("\n", "<br>\n")

    # ── ④ 条文スタイル ──
    html = re.sub(r"(第\s*[０-９0-9一二三四五六七八九十百千]+\s*[条項号])", r'<span class="article">\1</span>', html)

    # ── ⑤ プレースホルダーを元に戻す（Plotly → 数式の順） ──
    for k, v in plotly_ph.items():
        html = html.replace(k, v)
    for k, v in ph.items():
        html = html.replace(k, v)

    # ── ⑥ Ankiメディア画像パスを補正（subject が渡された場合のみ） ──
    if subject:
        try:
            from anki_importer import fix_media_paths
            html = fix_media_paths(html, subject)
        except ImportError:
            pass  # anki_importer が無い環境でも問題なく動作する

    return html


def build_test_set(subject: str, topic_id: str, subj_name: str, topic_name: str,
                   rag_store_name: str = None,
                   question_format: str = "記述式問題",
                   use_web_search: bool = False
                   ) -> tuple:
    """
    テスト問題セットを生成してDBに登録し、出題リストを返す。
    （AI呼び出し + DB操作を両方含むビジネスロジック）
    """
    import json
    import database as _db

    pool      = _db.get_question_pool(subject, topic_id, question_format=question_format)
    pool_size = len(pool)
    total_q   = 5
    if pool_size >= _db.QUESTION_POOL_MAX:
        n_new, n_review = _db.NEW_Q_FULL, total_q - _db.NEW_Q_FULL
    elif pool_size == 0:
        n_new, n_review = total_q, 0
    else:
        n_new, n_review = _db.NEW_Q_NORMAL, total_q - _db.NEW_Q_NORMAL

    review_qs      = pool[:n_review] if pool else []
    existing_texts = [q["question"] for q in pool]
    lesson_text    = _db.load_explane(subject, topic_id) or ""

    # ── ▼ 修正②：テスト生成用の説明文からPlotlyコードを省略する ▼ ──
    # ```python ... ``` で囲まれたブロックを検査し、
    # 「plotly」や「go.Figure」といったPlotly特有のキーワードを含む場合のみ
    # 「【図表の描画コードは省略】」に置き換える。
    # Pandas 等の一般的なコードはそのまま残す。
    def _replace_plotly_blocks_for_test(text: str) -> str:
        def _replacer(m):
            code = m.group(1)
            if "plotly" in code or "go.Figure" in code:
                return "\n【図表の描画コードは省略】\n"
            return m.group(0)  # Plotly以外はそのまま
        return re.sub(r"```python\s*\n([\s\S]*?)```", _replacer, text)

    lesson_text_for_test = _replace_plotly_blocks_for_test(lesson_text)
    # ── ▲ 修正②ここまで ▲ ──

    lesson_scope   = (
        f"\n\n【出題範囲の限定】問題は必ず以下の「説明本文」で説明された内容のみから作成してください。"
        f"\n--- 説明本文 ---\n{lesson_text_for_test}\n--- ここまで ---"
        if lesson_text else ""
    )
    existing_block = (
        "\n\n【重複禁止】以下の問題と同じ、または酷似した内容の問題は絶対に作らないでください：\n"
        + "\n".join(f"- {t}" for t in existing_texts)
        if existing_texts else ""
    )

    # --- ▼ 出題形式に応じたプロンプト条件の動的変更 ▼ ---
    prompt_modifiers = ""
    ans_hint = "模範解答"  # デフォルト

    if question_format == "正誤問題":
        prompt_modifiers += "\n【出題形式：正誤問題】\n問題文は必ず「〇」か「×」で答えられる文章にし、問題文の冒頭に必ず「次の記述の正誤を答えてください。」という一文を入れてください。"
        ans_hint = "〇 または ×"
    elif question_format == "5肢択一問題":
        prompt_modifiers += "\n【出題形式：5肢択一問題】\n問題文(`question`)の中に、必ず1から5までの選択肢の文章を改行して含めてください。解答(`answer`)は正解の番号(1〜5のいずれか一つ)のみを記載してください。"
        ans_hint = "正解の番号のみ（例：3）"
    elif question_format == "穴埋め問題":
        prompt_modifiers += "\n【出題形式：穴埋め問題】\n問題文の重要なキーワード1箇所だけを空欄（[  ]）にし、解答(`answer`)にはその空欄に入るべき語句のみを記載してください。"
        ans_hint = "空欄に入る語句"
    elif question_format == "論証問題":
        prompt_modifiers += "\n【出題形式：論証問題】\n具体的な事例や複雑な状況を設定した長文問題とし、解答(`answer`)は理由や論拠・論証を含めた詳細な長文の記述式にしてください。"
        ans_hint = "理由・論拠を含めた詳細な長文解答"
    elif question_format == "理系用計算問題（途中式あり）":
        prompt_modifiers += "\n【出題形式：計算問題】\n具体的な数値を用いた計算問題を出題してください。解答(`answer`)には、最終的な答えだけでなく、そこに至るまでの途中式や計算過程も必ず詳しく記述してください。"
        ans_hint = "途中式と最終的な答え"
    elif question_format == "理系用証明・導出問題":
        prompt_modifiers += "\n【出題形式：証明・導出問題】\n定理の証明、公式の導出、あるいは物理現象の理由を数式を用いて説明させる問題を出題してください。解答(`answer`)は論理的なステップを踏んだ記述にしてください。"
        ans_hint = "証明または導出のプロセス"
    else:  # 記述式問題（デフォルト）
        prompt_modifiers += "\n【出題形式：記述式問題】\n簡潔な文章または単語で答えられる問いにしてください。"
        ans_hint = "簡潔な模範解答"
    # ===== ▼ ここから追加 ▼ =====
    prompt_modifiers += (
        "\n【図表出力の優先ルール】\n"
        "問題文や解答に図解が必要な場合、まずは提供された画像データの中に適切なものがあれば `<img src=\"ファイル名\">` を優先して使用してください。\n"
        "該当する画像がない場合に限り、Plotlyを用いたPythonコードを作成して図表を自作してください（matplotlib不可）。\n"
        "【重要：エスケープとフォーマット】\n"
        "・数式(LaTeX)のバックスラッシュは必ず2つ重ねてください（例: \\\\frac, \\\\times）。\n"
        "・改行は通常の「\\n」を使用し、絶対に「\\\\n」としないでください。\n"
        "・図表のPythonコードは必ずバッククォート3つ（```python 〜 ```）で囲んでください。"
    )
    # ===== ▲ ここまで追加 ▲ =====
    # --------------------------------------------------
    # ▼ ここから下を新しく追加 ▼
    # --------------------------------------------------
    prompt_modifiers += (
        f"\n【出題内容の除外ルール】\n"
        f"Plotlyのコードに関する問題は絶対に作成しないでください。"
        f"必ず科目「{subj_name}」の本来の学習内容についてのみ出題してください。"
    )
    # --------------------------------------------------
    # --- ▲ ここまで ▲ ---

    # ── メディア要約ブロック（画像の内容をプロンプトに組み込む）──
    # RAG検索を有効化（トピック名をクエリとして使用）
    all_media = _db.get_all_media_with_embeddings(subject)
    if all_media:
        relevant_media = find_top_relevant_images(topic_name, all_media, top_n=10)
        media_block = "\n\n【利用可能な画像データ（最優先ルール：関連上位10件のみ）】\n"
        media_block += "【重要】画像を表示する場合は、必ず以下のリストにある正確なファイル名を用いて `<img src=\"ファイル名\">` の形式で出力してください。リストにない架空のファイル名は絶対に生成・使用しないでください。\n"
        for m in relevant_media:
            media_block += f"- {m['filename']}: {m['summary']}\n"
        prompt_modifiers += media_block
    else:
        # 画像がない場合は明確に禁止する
        prompt_modifiers += "\n\n【画像出力の禁止】\n現在利用可能な画像データはありません。架空の画像ファイル名を作成して `<img src=\"...\">` のようなタグを出力することは絶対にやめてください。\n"

    prompt = (
        f'科目「{subj_name}」の「{topic_name}」について、新規問題を {n_new}問 作成してください。\n'
        '【重複・バラエティに関する絶対ルール】\n'
        f'1. 今回作成する {n_new}問 の中で、問う内容や概念が重複しないように細心の注意を払ってください。\n'
        '2. 各問題は、分野内の異なる側面（定義、計算、理由、例外、応用など）を網羅するようにバラエティ豊かに構成してください。\n'
        '3. 似たような正解になる問題が2つ以上含まれることは「質の低いテスト」とみなされます。\n'
        + prompt_modifiers
        + lesson_scope + existing_block
        + '\n\n【出力形式】以下のJSON構造のみを出力（他テキスト不要）：\n'
        + '[ {"question": "問題文", "answer": "' + ans_hint + '"} ]'
    )
    
    raw     = gemini_once_json(prompt, use_web_search=use_web_search)
    new_gen = json.loads(raw)
    _db.add_questions_to_pool(subject, topic_id, new_gen, question_format=question_format)

    new_rows = _db.get_recent_questions(subject, topic_id, n_new)

    result = []
    q_no   = 1

    for rq in review_qs:
        result.append({"q": q_no, "question": rq["question"], "answer": rq["answer"], "pool_id": rq["id"], "format": rq.get("format", "記述式問題")})
        q_no += 1
    for nr in new_rows:
        result.append({"q": q_no, "question": nr["question"], "answer": nr["answer"], "pool_id": nr["id"], "format": nr.get("format", question_format)})
        q_no += 1

    return result, pool_size
