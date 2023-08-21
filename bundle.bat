call venv\Scripts\activate.bat
pyinstaller --noconfirm --onefile --console --icon "icon.ico" --name "api-dynalauncher" --add-data "dyna-tools;dyna-tools/"  "server.py"
