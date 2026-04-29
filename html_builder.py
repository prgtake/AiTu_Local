# Copyright (c) 2026 Datan (データン)
# Licensed under a Custom Hybrid License (Free for Individuals, Paid for Commercial).
# See README.md for licensing details.
# -*- coding: utf-8 -*-
"""
=======================================================
  html_builder.py
  HTML文字列の組み立てや、ブラウザでのリッチテキスト表示を担当
=======================================================
"""
import tempfile
import webbrowser
import pathlib
import ai_engine

def open_local_html(file_path: str):
    """ローカルのHTMLファイルをデフォルトブラウザで開く"""
    webbrowser.open(pathlib.Path(file_path).as_uri())

def open_math_html(title: str, sections: list, subject: str = None):
    """HTMLを生成してブラウザでリッチ表示する"""
    body_parts = ""
    for sec in sections:
        heading = sec.get("heading", "")
        body    = sec.get("body",    "")
        h_tag   = f"<h2>{heading}</h2>" if heading else ""
        body_parts += f'\n<div class="section">\n  {h_tag}\n  <div class="content">{ai_engine.md_to_html(body, subject=subject)}</div>\n</div>'

    css = """
  body {font-family: "Meiryo","Yu Gothic",sans-serif; background: #f8f9fa; margin: 0; padding: 30px; line-height: 1.8; font-size: 16px; color: #333;}
  h1 {color: #1a73e8; font-size: 1.6em; border-bottom: 3px solid #1a73e8; padding-bottom: 10px; margin-bottom: 25px;}
  h2 {color: #444; font-size: 1.25em; margin: 20px 0 10px 0; border-left: 5px solid #1a73e8; padding-left: 12px; background: #e8f0fe; padding-top: 5px; padding-bottom: 5px; border-radius: 0 4px 4px 0;}
  .section {background: #fff; border-radius: 12px; padding: 25px 35px; margin-bottom: 30px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); border: 1px solid #e0e0e0;}
  .content { overflow-x: auto; }
  table {border-collapse: collapse; width: 100%; margin: 20px 0; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 5px rgba(0,0,0,0.05);}
  th {background: #1a73e8; color: #fff; padding: 12px 15px; border: 1px solid #1557b0; text-align: left;}
  td {padding: 10px 15px; border: 1px solid #ddd; vertical-align: top;}
  tr:nth-child(even) td {background: #f1f3f4;}
  .article {color: #d93025; font-weight: bold; background: #fce8e6; padding: 0 4px; border-radius: 2px;}
  .plotly-chart {margin: 25px 0; background: #fff; border-radius: 8px; padding: 10px; border: 1px solid #eee;}
  .plotly-error {background:#fef7f7; border:1px solid #f8d7da; border-radius:8px; padding:15px; margin:20px 0; color:#721c24;}
  .plotly-error pre {font-size:0.85em; white-space:pre-wrap; overflow-x:auto; background: #fff; padding: 10px; border-radius: 4px;}

  /* 画像表示のスタイル改善 */
  .content img { 
    max-width: 90%; 
    max-height: 500px; 
    height: auto; 
    object-fit: contain; 
    cursor: zoom-in; 
    display: block; 
    margin: 25px auto; 
    border-radius: 8px; 
    box-shadow: 0 4px 15px rgba(0,0,0,0.15);
    border: 1px solid #ddd;
    transition: transform 0.2s;
  }
  .content img:hover { transform: scale(1.01); }

  #lightbox { display: none; position: fixed; z-index: 9999; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.9); align-items: center; justify-content: center; cursor: zoom-out; }
  #lightbox img { max-width: 98vw; max-height: 98vh; object-fit: contain; background: #fff; padding: 5px; border-radius: 4px; }
"""
    try:
        import markdown; icon = "📘"; lib_note = "（markdown ライブラリ使用）"
    except ImportError:
        icon = "📄"; lib_note = "（簡易変換モード）"

    html = (
        '<!DOCTYPE html>\n<html lang="ja">\n<head>\n<meta charset="UTF-8">\n'
        f'<title>{title}</title>\n'
        '<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>\n'
        '<script>MathJax = {tex: {inlineMath:[["$","$"],["\\\\(","\\\\)"]], displayMath:[["$$","$$"],["\\\\[","\\\\]"]], processEscapes:true}, options:{skipHtmlTags:["script","noscript","style","textarea","pre"]}};</script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js" async></script>\n'
        f'<style>{css}</style>\n</head>\n<body>\n'
        f'<h1>{icon} {title} <small style="font-size:0.6em;color:#888">{lib_note}</small></h1>\n{body_parts}\n'
        '<div id="lightbox" onclick="this.style.display=\'none\'"><img id="lightbox-img"></div>\n'
        '<script>\n'
        'document.addEventListener("DOMContentLoaded", function() {\n'
        '  const lb = document.getElementById("lightbox");\n'
        '  const lbImg = document.getElementById("lightbox-img");\n'
        '  document.querySelectorAll(".content img").forEach(img => {\n'
        '    img.onclick = function() { lb.style.display = "flex"; lbImg.src = this.src; };\n'
        '  });\n'
        '});\n'
        '</script>\n'
        '</body>\n</html>'
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8", prefix="tutor_rich_") as tf:
        tf.write(html)
        tmp_path = tf.name
    open_local_html(tmp_path)


def open_dashboard_html(subj: str, radar_html: str, bar_html: str, heat_html: str, ai_comments: dict, with_ai: bool):
    """学習ダッシュボードのHTMLを生成し、ブラウザで開く"""
    def _ai_block(comment_key, advice_key):
        c, a = ai_comments.get(comment_key, ""), ai_comments.get(advice_key, "")
        if not c and not a: return ""
        return f'<div class="ai-box"><div class="ai-comment">🤖 <strong>AI評価：</strong>{c}</div><div class="ai-advice">💡 <strong>アドバイス：</strong>{a}</div></div>'

    oc, oa = ai_comments.get("overall_comment", ""), ai_comments.get("overall_advice", "")
    overall_section = f'<div class="overall-box"><h2>📊 全体 講評・アドバイス</h2><div class="overall-comment">📝 <strong>講評：</strong><br>{oc}</div><div class="overall-advice">💡 <strong>アドバイス：</strong><br>{oa}</div></div>' if with_ai and oc else ""

    # ポップアップで表示する仕様説明のテキスト（JavaScriptのalert内で改行するため \\n を使用）
    # ① レーダーチャートの仕様説明
    radar_info_text = (
        "【レーダーチャートの仕様説明】\\n\\n"
        "◆レーダーチャートの計算\\n"
        "各分野に含まれる全問題の「過去の累積正解率の平均」を表示しています。\\n"
        "※白紙回答は分野ごとの出題では不正解扱いで正解率を下げますが、復習問題ではスキップ扱い(出題されていない扱い)です。\\n\\n"
        "◆学習メニューの「理解度」との違い\\n"
        "学習メニューに表示される「理解度」は、各問題を最後に解いた直近のテストで正解できている問題数をカウントしています。\\n"
        "レーダーチャートは過去の全履歴を含めた長期的な定着度を、理解度は直近の状態を表しています。"
    )

    # ② ヒートマップの仕様説明
    heat_info_text = (
        "【ヒートマップの仕様説明】\\n\\n"
        "◆各指標の定義\\n"
        "・回答数：AIが採点（送信）を行った問題の総数です。\\n"
        "・正解数：AIが「正解」と判定した問題の総数です。\\n"
        "・正解率：(正解数 ÷ 回答数) × 100 で算出されます。\\n\\n"
        "◆白紙回答（未入力）の扱い\\n"
        "・確認テスト：回答数にカウントされ「不正解」となるため、その日の正解率を下げる。\\n"
        "・復習テスト：採点対象から除外され、回答数・正解数ともに影響なし。"
    )


    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><title>{subj} 学習状況</title><script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script><style>
body{{font-family:'Meiryo',sans-serif; background:#f5f5f5; margin:0; padding:20px;}} h1{{color:#3d7ebf; border-bottom:2px solid #3d7ebf; padding-bottom:6px;}}
.section{{background:#fff; border-radius:8px; padding:16px; margin-bottom:24px; box-shadow:0 2px 6px rgba(0,0,0,0.08);}}
.ai-box{{background:#f0f7ff; border-left:4px solid #3d7ebf; padding:12px 16px; margin-top:12px; line-height:1.7;}} .ai-comment{{color:#1a3a5c; margin-bottom:8px;}} .ai-advice{{color:#2e6b2e;}}
.overall-box{{background:#fff9e6; border:2px solid #f0c040; border-radius:8px; padding:20px; margin-bottom:24px;}} .overall-box h2{{color:#7a5800;}} .overall-comment{{color:#3a2800;}} .overall-advice{{color:#1a4a1a;}}
/* 追加：仕様説明のホバーエフェクト */
.info-link {{ font-size: 0.65em; color: #1565c0; cursor: pointer; text-decoration: underline; font-weight: normal; margin-left: 8px; }}
.info-link:hover {{ color: #0d47a1; }}
</style></head><body><h1>📊 {subj} ― 学習状況ダッシュボード</h1>
<div class="section"><h2>① 分野別 弱点レーダーチャート <span class="info-link" onclick="alert('{radar_info_text}')">(仕様説明)</span></h2>{radar_html}{_ai_block("radar_comment", "radar_advice")}</div>
<div class="section"><h2>② 直近7日間の復習予測（赤＝今日）</h2>{bar_html}{_ai_block("forecast_comment", "forecast_advice")}</div>
<div class="section"><h2>③ 学習継続ヒートマップ（過去52週） <span class="info-link" onclick="alert('{heat_info_text}')">(仕様説明)</span></h2>{heat_html}{_ai_block("heatmap_comment", "heatmap_advice")}</div>{overall_section}</body></html>"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as tf:
        tf.write(html)
        tmp_path = tf.name
    open_local_html(tmp_path)

def get_podcast_html(topic_name: str, html_bubbles: list, js_audio_array: str) -> str:
    """音声解説（Podcast）用のHTML文字列を生成する"""
    # 呼び出し側ではなく、生成側で安全にエスケープ処理を行う
    topic_name_safe = topic_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>音声解説 - {topic_name_safe}</title>
<style>
  body {{
    font-family: 'Meiryo', 'Hiragino Sans', sans-serif;
    background-color: #f0f2f5;
    padding: 20px;
    max-width: 800px;
    margin: auto;
  }}
  h1 {{ text-align: center; color: #333; font-size: 20px; }}
  .controls {{
    text-align: center;
    margin-bottom: 30px;
    background: #fff;
    padding: 15px;
    border-radius: 10px;
    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
  }}
  button {{
    font-size: 18px;
    padding: 10px 20px;
    cursor: pointer;
    border: none;
    border-radius: 5px;
    background: #3d7ebf;
    color: white;
  }}
  button:hover {{ background: #2a5f9e; }}
  .chat-container {{
    display: flex;
    flex-direction: column;
    gap: 15px;
    padding-bottom: 60px;
  }}
  .chat-bubble {{
    max-width: 70%;
    padding: 15px;
    border-radius: 15px;
    line-height: 1.6;
    font-size: 16px;
    opacity: 0.45;
    transition: opacity 0.3s, box-shadow 0.3s;
  }}
  .chat-bubble.active {{
    opacity: 1;
    box-shadow: 0 0 12px rgba(61,126,191,0.55);
  }}
  .teacher {{
    align-self: flex-start;
    background-color: #ffffff;
    border: 1px solid #ddd;
    border-top-left-radius: 0;
  }}
  .student {{
    align-self: flex-end;
    background-color: #dcf8c6;
    border-top-right-radius: 0;
  }}
  .name {{ font-weight: bold; font-size: 13px; margin-bottom: 5px; color: #555; }}
</style>
</head>
<body>
  <h1>🎙️ {topic_name_safe} の音声解説</h1>
  <div class="controls">
    <button id="playBtn" onclick="startPodcast()">▶ 再生を開始する</button>
    <p style="font-size:13px; color:#666; margin-top:10px;">
      ※ブラウザの仕様により、最初の再生は手動でボタンを押す必要があります。
    </p>
  </div>
  <div class="chat-container">
    {"".join(html_bubbles)}
  </div>
  <script>
    const audioFiles = {js_audio_array};
    let currentIndex = 0;
    const audioPlayer = new Audio();
    function startPodcast() {{
      document.getElementById("playBtn").style.display = "none";
      playNext();
    }}
    function playNext() {{
      if (currentIndex >= audioFiles.length) {{
        currentIndex = 0;
        document.querySelectorAll('.chat-bubble').forEach(el => el.classList.remove('active'));
        const btn = document.getElementById("playBtn");
        btn.textContent = "↩ もう一度再生する";
        btn.style.display = "";
        return;
      }}
      document.querySelectorAll('.chat-bubble').forEach(el => el.classList.remove('active'));
      const bubble = document.getElementById('bubble_' + currentIndex);
      if (bubble) {{
        bubble.classList.add('active');
        bubble.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      }}
      audioPlayer.src = audioFiles[currentIndex];
      audioPlayer.play().catch(err => console.warn("再生エラー:", err));
      audioPlayer.onended = function() {{
        currentIndex++;
        playNext();
      }};
    }}
  </script>
</body>
</html>"""