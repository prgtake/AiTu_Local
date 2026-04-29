# AiTu (アイツ) - Desktop Edition 📚

**「その参考書、1分であなたの血肉（Anki）に変える。」**

AiTu（アイツ）は、PDFをドラッグ＆ドロップするだけで、AIが内容を完全解析し、**AI家庭教師・学習Podcast生成・Ankiカード生成 **をデスクトップ環境で完結させる学習支援ツールです。

「まとめ作業」や「進捗管理」はAIに任せ、あなたは「理解すること」や「覚えること」に集中してください。

---

## 🌟 AiTu (アイツ)の機能
- 🔄 AIによる家庭教師機能 ― AIの持つ幅広く深い知識を活かし、非常に多くの科目（分野）の「体系的な教科書」を生成します。
- 📚 RAG（独自資料）対応 ― 指定の資料を「唯一の正解」として出題・採点。AIの嘘（ハルシネーション）を防ぎます

- 🖼️ 図解の自動取り込み ― 読み込ませたjpgファイルの内容をAIが理解して解説用の画像として利用します。

- 🔄 Ankiからの「逆生成」機能 ― 公開されているAnkiデッキ（.apkg）を読み込ませると、AIがカードを分析し、シラバス（目次）を自動構築。 バラバラの暗記カードから「体系的な教科書」を逆生成します。

✍️ 手書き採点 ― 数式や図は、紙に書いて写真を撮って添付すれば、AIが読み取って採点

🧠 忘却曲線ベースの自動復習 ― 正解率と連続正解数から、最適なタイミングで自動スケジューリングして復習問題を出題

🎙️ NotebookLM風の音声ポッドキャスト解説 ― ボタン一つで、AIが「先生と生徒の対話台本」を作成し、男女の音声（無料の合成音声）でラジオ番組風の解説音声を作ってくれます。退屈しません。

🃏 画像同梱のAnkiデッキ（.apkg）一発出力 ― 弱点問題や新規生成した問題を、図解画像ごとパッケージ化（.apkg形式）して、1クリックでAnkiアプリに出力できます。

## 🌟 AiTu (アイツ)DeskTop版の特徴
- **完全ローカル・プライバシー 🛡️**: ブラウザ経由ではなく、あなたのPC内で動作。アップロードした資料が外部サーバーに保存される心配はありません（※AI処理のためGoogle Gemini APIとの通信は発生）。

- **高速・安定 ⚡**: ブラウザのタイムアウト制限を気にせず、数百ページの巨大なPDFも安定して処理可能。

- **EXE形式で即起動 🚀**: 面倒なPythonのセットアップは不要。配布されたEXEファイルを叩くだけです。

- **マルチモーダル解析 👁️**: 最新のGemini Flash APIを活用し、図表や複雑なレイアウトも正確に読み取ります。

---

## ⚖️ ライセンス / License (Hybrid-Passive License)

本ソフトウェアの著作権は **Datan (データン)** に帰属します。

### 1. 個人・非営利利用 (Individual / Non-commercial Use)
- **費用: 0円**
- 受験生、医学生、資格試験合格を目指す個人の方は、自由にお使いください。
- 「合格した！」という報告をSNSでもらえることが、作者にとって最大の報酬です。

### 2. 商用・法人利用 (Commercial / Corporate Use)
- **塾、予備校、学校法人、または本ツールを商用サービスに組み込む場合は、別途「有料ライセンス契約」が必要です。**
- 企業様向けのカスタマイズ、OEM提供、技術顧問契約等はご相談ください。
- 無断での商用利用は固くお断りいたします。

### 3. 免責事項 (Disclaimer)
- 本ソフトウェアは「現状のまま（As-Is）」提供されます。
- Vibe Codingによる開発であり、機能性を最優先し、コードの美しさよりも「動くこと」を重視しています。
- 利用によって生じた損害（API費用、試験結果等）について、作者は一切の責任を負いません。

---

## 🚀 使い方 (How to Use)

1. [Google AI Studio](https://aistudio.google.com/) でGemini APIキーを取得してください。
2. `AiTu.exe` を起動し、設定画面でAPIキーを入力します。
3. 学習したいPDFをウィンドウに放り込みます。
4. 数分後、生成された 学習計画に基づき、学習を進めます。AiTuが忘却曲線を考慮した復習問題を出題するので、自然と記憶が定着します。
5. Ankiの`.apkg` ファイルからシラバスを逆作成することもできます。またAnki用の`.apkg` ファイルの出力もできます。

---

## 📬 お問い合わせ / Contact

- 不具合報告やご要望は、GitHubのリポジトリまでお願いいたします。
- https://github.com/prgta/AiTu_Local

---

(c) 2026 Datan（データン）. All rights reserved.

---

# English Translation

# AiTu - Desktop Edition 📚

**"Turn any reference book into your knowledge (Anki) in just one minute."**

AiTu is a learning support tool that completely analyzes PDF content with just a drag-and-drop. It handles **AI Tutoring, Study Podcast Generation, and Anki Card Creation** entirely within your desktop environment.

Let the AI handle the "summarizing" and "progress management," so you can focus on "understanding" and "remembering."

---

## 🌟 Features
- 🔄 **AI Tutoring**: Leverages the AI's vast and deep knowledge to generate "systematic textbooks" for a wide variety of subjects.
- 📚 **RAG (Own Material) Support**: Uses your specific materials as the "only source of truth" for questioning and grading, preventing AI hallucinations.
- 🖼️ **Automatic Diagram Import**: AI understands the content of uploaded JPG files and uses them as explanatory images.
- 🔄 **"Reverse Generation" from Anki**: Import public Anki decks (.apkg) to have the AI analyze cards and automatically build a syllabus. It reverse-generates a "systematic textbook" from scattered flashcards.
- ✍️ **Handwritten Grading**: Just take a photo of your handwritten formulas or diagrams and attach them. The AI will read and grade them.
- 🧠 **Forgetting Curve-based Automatic Review**: Automatically schedules review questions at the optimal timing based on your correct answer rate and streak.
- 🎙️ **NotebookLM-style Audio Podcast Commentary**: With one click, the AI creates a dialogue script (Teacher & Student) and generates radio-style audio commentary using free synthetic voices. It never gets boring.
- 🃏 **Instant Anki Deck (.apkg) Export with Images**: Package weak points or newly generated questions into an .apkg file with images and export to Anki in one click.

## 🌟 Desktop Edition Highlights
- **Full Local Privacy 🛡️**: Runs within your PC, not via a browser. Your uploaded materials are never saved on external servers (Communication with Google Gemini API occurs for AI processing).
- **Fast & Stable ⚡**: Processes even massive hundreds-of-pages PDFs stably without browser timeout limits.
- **Instant Launch via EXE 🚀**: No tedious Python setup required. Just run the provided EXE file.
- **Multimodal Analysis 👁️**: Utilizes the latest Gemini Flash API to accurately read diagrams and complex layouts.

---

## ⚖️ License (Hybrid-Passive License)

Copyright for this software belongs to **Datan**.

### 1. Individual / Non-commercial Use
- **Cost: 0 JPY (Free)**
- Students and individuals aiming for exams or certifications are free to use it.
- Receiving reports like "I passed!" on SNS is the greatest reward for the author.

### 2. Commercial / Corporate Use
- **Separate "Paid License Agreement" is required for cram schools, educational corporations, or integrating this tool into commercial services.**
- Please contact us for corporate customization, OEM provision, or technical advisory contracts.
- Unauthorized commercial use is strictly prohibited.

### 3. Disclaimer
- This software is provided "As-Is."
- Developed via "Vibe Coding," prioritizing functionality and "it works" over code aesthetics.
- The author assumes no responsibility for any damages (API costs, exam results, etc.) resulting from its use.

---

## 🚀 How to Use

1. Obtain a Gemini API key at [Google AI Studio](https://aistudio.google.com/).
2. Launch `AiTu.exe` and enter your API key in the settings.
3. Drag and drop the PDF you want to study into the window.
4. After a few minutes, proceed with learning based on the generated study plan. AiTu will issue review questions considering the forgetting curve to naturally fix your memory.
5. You can also reverse-generate a syllabus from Anki `.apkg` files or export newly created questions to Anki.

---

## 📬 Contact

- Please report bugs or requests to the GitHub repository.
- https://github.com/prgta/AiTu_Local

---

(c) 2026 Datan. All rights reserved.
