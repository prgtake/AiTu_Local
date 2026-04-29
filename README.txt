AiTu - Geminiによる自律型AI学習サポーター (AiTu_Local)
===========================================================

AiTu は、Googleの最新AI「Gemini」を活用して、あらゆる分野の学習を
サポートするデスクトップアプリです。

noteに使用マニュアルも公開していますので、そちらも参考にしてください。
https://note.com/datan/n/n3ef010c80d8d


-----------------------------------------------------------
1. AiTu (アイツ) の主な機能
-----------------------------------------------------------
- AIによる家庭教師機能 ― 体系的な教科書を自動生成します。
- RAG（独自資料）対応 ― お手持ちの資料を元に出題・採点を行います。
- 図解の自動取り込み ― 画像資料をAIが理解し、解説に使用します。
- Ankiからの逆生成 ― Ankiデッキから体系的な学習計画を再構築します。
- 手書き採点 ― ノートをカメラで撮って送るだけで、AIが採点します。
- 忘却曲線ベースの自動復習 ― 最適なタイミングで復習を促します。
- 音声ポッドキャスト解説 ― 学習内容をラジオ番組風に音声で聴けます。
- Ankiデッキ一発出力 ― 弱点や新規問題を画像付きでAnkiに出力可能です。

-----------------------------------------------------------
2. 起動方法
-----------------------------------------------------------
- 「AiTu_Local.exe」をダブルクリックして起動してください。
- 起動時、環境によっては「Windowsによって PC が保護されました」という
  メッセージが出ることがあります。その場合は「詳細情報」をクリックし、
  「実行」を選択してください。

-----------------------------------------------------------
3. 準備するもの
-----------------------------------------------------------
- インターネット接続環境（Gemini APIを使用するため必須です）
- Google Gemini API キー
  - お持ちでない場合は、Google AI Studio (https://aistudio.google.com/) 
    にて無料で取得できます。
  - PCのユーザー環境変数（GEMINI_API_KEY）に設定するか、あるいは、
　　アプリ内の設定画面で入力して使用してください。

-----------------------------------------------------------
4. ファイルとデータの管理（バックアップについて）
-----------------------------------------------------------
本アプリを実行すると、以下のファイル・フォルダが生成されます。
これらは個人の学習データですので、ローカル（自分のPC内）で
管理・バックアップしてください。

- [分野名].db : 学習履歴、弱点、学習計画を保存する重要なデータです。
- [分野名]_media/ : 取り込んだ図解やカメラ画像が保存されます。

※PCを買い替える際は、これらのデータを新しいPCの同じ場所にコピーしてください。

-----------------------------------------------------------
5. ライセンス (Hybrid-Passive License)
-----------------------------------------------------------
本ソフトウェアの著作権は Datan (データン) に帰属します。

■ 個人・非営利利用 (個人利用、学生、受験生など)
   - 費用: 0円（無料）
   - 個人学習の目的であれば、自由にご利用いただけます。

■ 商用・法人利用 (塾、学校法人、商用サービスへの組み込みなど)
   - 別途「有料ライセンス契約」が必要です。無断での商用利用は固くお断りします。

■ 免責事項
   - 本ソフトウェアは「現状のまま」提供されます。利用によって生じた損害
     （API費用、試験結果等）について、作者は一切の責任を負いません。

-----------------------------------------------------------
6. 注意事項
-----------------------------------------------------------
- 本アプリはAI（Gemini Flash API）による回答を生成します。
- AIは稀に誤った情報を提示することがあります（ハルシネーション）。
- API(無料枠)の使用量によっては、制限が発生する場合があります。

-----------------------------------------------------------
7. お問い合わせ
-----------------------------------------------------------
不具合報告やご要望は、GitHubのリポジトリまでお願いいたします。 
https://github.com/prgta/AiTu_Local   

学習の効率化を心より応援しています。
===========================================================
(c) 2026 Datan (データン). All rights reserved.


---

# English Translation

AiTu - Autonomous AI Learning Supporter via Gemini (AiTu_Local)
===========================================================

AiTu is a desktop application that supports learning in any field using 
Google's latest AI, "Gemini."

You can also find the user manual at the following link on note:
https://note.com/datan/n/n3ef010c80d8d

-----------------------------------------------------------
1. Key Features of AiTu
-----------------------------------------------------------
- AI Tutoring: Automatically generates systematic textbooks.
- RAG (Own Material) Support: Grades and questions based on your provided materials.
- Automatic Diagram Import: AI understands image materials and uses them in explanations.
- Reverse Generation from Anki: Rebuilds a systematic study plan from Anki decks.
- Handwritten Grading: AI grades handwritten notes sent via camera photos.
- Forgetting Curve-based Automatic Review: Prompts review at the optimal timing.
- Audio Podcast Commentary: Listen to study content in a radio-style audio format.
- Instant Anki Deck Export: Export weak points or new questions to Anki with images.

-----------------------------------------------------------
2. How to Start
-----------------------------------------------------------
- Double-click "AiTu_Local.exe" to launch.
- Depending on your environment, you may see a "Windows protected your PC" message. 
  In that case, click "More info" and select "Run anyway."

-----------------------------------------------------------
3. Requirements
-----------------------------------------------------------
- Internet connection (Required for Gemini API).
- Google Gemini API Key:
  - If you don't have one, get it for free at Google AI Studio 
    (https://aistudio.google.com/).
  - Set it in your PC's user environment variable (GEMINI_API_KEY) 
    or enter it in the app's settings screen.

-----------------------------------------------------------
4. File and Data Management (About Backup)
-----------------------------------------------------------
The following files and folders are generated when you run this app. 
Since these are personal learning data, please manage and back them up locally.

- [Subject].db: Database for learning history, weak points, and study plans.
- [Subject]_media/: Folder for imported diagrams and camera images.

*When moving to a new PC, copy these data to the same location on the new PC.

-----------------------------------------------------------
5. License (Hybrid-Passive License)
-----------------------------------------------------------
The copyright for this software belongs to Datan.

- Individual / Non-commercial Use:
  - Cost: 0 JPY (Free)
  - Feel free to use for personal learning.

- Commercial / Corporate Use:
  - A separate "Paid License Agreement" is required. 
    Unauthorized commercial use is strictly prohibited.

- Disclaimer:
  - This software is provided "As-Is." The author is not responsible 
    for any damages resulting from its use.

-----------------------------------------------------------
6. Precautions
-----------------------------------------------------------
- This app generates responses using AI (Gemini Flash API).
- AI may occasionally provide incorrect information (hallucinations).
- Limitations may occur on the Google side depending on API (free tier) usage.

-----------------------------------------------------------
7. Contact
-----------------------------------------------------------
Please report bugs or requests to the GitHub repository:
https://github.com/prgta/AiTu_Local

We sincerely support your learning efficiency.
===========================================================
(c) 2026 Datan. All rights reserved.
