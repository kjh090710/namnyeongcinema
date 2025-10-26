
```bash



Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -r requirements.txt
pip install flask python-dotenv
python app.py
```








## 데이터
- SQLite 파일: `cinema.db`
- CSV 내보내기: `/admin/export/<movie_id>.csv`

