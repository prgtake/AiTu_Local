# 📚 AiTu (Ai Tutor) - Streamlit版 セットアップガイド

この度は AiTu (Streamlit版) をご利用いただきありがとうございます。
本ソフトウェアは、Gemini APIを活用した対話型学習支援ツールです。
以下の手順に従ってセットアップを行ってください。

---

## 1. 同封されているファイル内容
以下のファイルが同じフォルダにあることを確認してください。
- `app_streamlit.py` （メインプログラム）
- `ai_engine.py` （AI通信・解析エンジン）
- `database.py` （学習データ保存用）
- `anki_exporter.py` （Anki出力機能）
- `anki_importer.py` （Anki読込機能）
- `run_aitu.bat` （起動用）

## 2. Pythonのインストール
プログラムを動かすために **Python** が必要です。
1. [公式サイト](https://www.python.org/) から最新版をダウンロードしてインストールしてください。
2. インストール時、必ず **「Add Python to PATH」** にチェックを入れてください。

## 3. 必要なライブラリのインストール
Windowsのコマンドプロンプト（またはPowerShell）を開き、以下のコマンドを実行してください。

```bash
pip install streamlit google-genai pandas plotly pillow edge-tts genanki numpy beautifulsoup4 markdown
```

## 4. `run_aitu.bat` ファイルの編集
同封されている `run_aitu.bat` ファイルをエディタで開き、「プロジェクトのフォルダに移動」の移動先を、同封ファイルを格納したフォルダのフルパスに書き換えて保存します。
> **注意**: 必ず **UTF-8N** で保存してください。（SHIFT-JISで保存すると動きません。）

## 5. アプリの起動方法
フォルダ内の `run_aitu.bat` ファイルをダブルクリックします。
自動的にブラウザが立ち上がり、アプリ画面が表示されます。

## 6. Gemini API キーの設定
本ソフトの利用には **Google Gemini API** のキーが必要です（[Google AI Studio](https://aistudio.google.com/) で無料で取得できます）。

- 事前にユーザーごとの環境変数（`GEMINI_API_KEY`）に設定することをお勧めします。
- 環境変数に設定が無い場合は初回起動時に、PCのデスクトップに入力ダイアログが表示されます。
- 一度入力すれば `app_config.json` に保存されるため、次回からの入力は不要です。
- ※環境変数を設定済みの方は、ダイアログは表示されません。

## 7. 注意事項
- 学習データは `db` フォルダ、画像データは `media` フォルダに自動保存されます。
- APIキーを他人に教えないようご注意ください。
- スマホで利用する場合は、PCと同じWi-Fiに接続し、PCのIPアドレスを指定してブラウザでアクセスしてください。
- スマホでアクセスする場合は、サーバーとなるPCのIPアドレスを固定にしてください。
- **スマホのカメラを有効にする設定**:
  1. スマホのChromeで `chrome://flags` にアクセス。
  2. `Insecure origins treated as secure` を検索。
  3. 固定したPCのアドレス（例: `http://192.168.11.46:8502`）を入力して「Enabled（有効）」に設定。

## 8. ⚖️ ライセンス (Hybrid-Passive License)
本ソフトウェアの著作権は **Datan (データン)** に帰属します。

### 個人・非営利利用 (Individual / Non-commercial Use)
- **費用: 0円**
- 受験生、医学生、資格試験合格を目指す個人の方は、自由にお使いください。

### 商用・法人利用 (Commercial / Corporate Use)
- 塾、予備校、学校法人、または本ツールを商用サービスに組み込む場合は、別途 **「有料ライセンス契約」** が必要です。
- 無断での商用利用は固くお断りいたします。

### 免責事項 (Disclaimer)
- 本ソフトウェアは「現状のまま（As-Is）」提供されます。
- 利用によって生じた損害（API費用、試験結果等）について、作者は一切の責任を負いません。

---

Copyright (c) 2026 Datan (データン)

<br>

# English Translation

# 📚 AiTu (Ai Tutor) - Streamlit Edition Setup Guide

Thank you for using AiTu (Streamlit Edition).
This software is a learning support tool utilizing the Gemini API.
Please follow the steps below for setup.

---

## 1. Included Files
Ensure the following files are in the same folder:
- `app_streamlit.py` (Main program)
- `ai_engine.py` (AI communication & analysis engine)
- `database.py` (Learning data storage)
- `anki_exporter.py` (Anki export functionality)
- `anki_importer.py` (Anki import functionality)
- `run_aitu.bat` (Launcher)

## 2. Python Installation
**Python** is required to run this program.
1. Download and install the latest version from the [official site](https://www.python.org/).
2. During installation, make sure to check **"Add Python to PATH"**.

## 3. Required Library Installation
Open Windows Command Prompt (or PowerShell) and run the following command:

```bash
pip install streamlit google-genai pandas plotly pillow edge-tts genanki numpy beautifulsoup4 markdown
```

## 4. Editing `run_aitu.bat`
Open `run_aitu.bat` in a text editor and update the path in the "Move to project folder" section to the full path of your project folder.
> **Important**: Save the file with **UTF-8** encoding. (It will not work if saved as SHIFT-JIS.)

## 5. How to Launch
Double-click `run_aitu.bat` in the folder.
Your web browser will launch automatically, and the app screen will appear.

## 6. Gemini API Key Setting
A **Google Gemini API key** is required (obtainable for free at [Google AI Studio](https://aistudio.google.com/)).

- We recommend setting it as a user environment variable (`GEMINI_API_KEY`).
- If the environment variable is not set, an input dialog will pop up on your desktop upon the first launch.
- Once entered, the key will be saved in `app_config.json`, so you won't need to enter it again.
- *The dialog will not appear if the environment variable is already set.*

## 7. Precautions
- Learning data is saved in the `db` folder, and images in the `media` folder.
- Keep your API key private.
- To use it on a smartphone, connect to the same Wi-Fi as your PC and access via the PC's IP address in your browser.
- When accessing from a smartphone, please set a static IP for the host PC.
- **Enabling Camera on Mobile Chrome**:
  1. Open `chrome://flags` on mobile Chrome.
  2. Search for `Insecure origins treated as secure`.
  3. Enter your PC's IP (e.g., `http://192.168.11.46:8502`) and set it to **"Enabled"**.

## 8. ⚖️ License (Hybrid-Passive License)
Copyright for this software belongs to **Datan**.

### Individual / Non-commercial Use
- **Cost: 0 JPY (Free)**
- Students and individuals aiming for exams or certifications are free to use it.

### Commercial / Corporate Use
- A separate **"Paid License Agreement"** is required for schools, cram schools, or commercial service integration.
- Unauthorized commercial use is strictly prohibited.

### Disclaimer
- This software is provided **"As-Is."**
- The author assumes no responsibility for any damages (API costs, exam results, etc.) resulting from its use.

---

Copyright (c) 2026 Datan. All rights reserved.
