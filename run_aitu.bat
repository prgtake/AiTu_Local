@echo off
echo AiTu Web Edition を起動しています...

:: 1. プロジェクトのフォルダに移動
cd /d "C:\Users\prgta\OneDrive\Documents\GitHub\AiTu_Local"

:: 2. 仮想環境があれば有効化（前の手順で作った場合）
if exist .venv\Scripts\activate (
    call .venv\Scripts\activate
)

:: 3. Streamlit を起動
streamlit run app_streamlit.py

pause