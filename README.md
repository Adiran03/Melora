# Melora

![Логотип Melora](static/melora-logo.png)

Melora — музыкальный плеер для Windows. Он ищет песни и артистов, хранит любимые треки и плейлисты локально и подбирает похожие записи в «Моей волне».

## Установка на Windows

Скачайте файл `Melora-Setup.exe` на странице релизов и запустите его. После установки Melora появится в меню «Пуск». Ярлык на рабочем столе можно добавить в установщике. [Релизы Melora](https://github.com/Adiran03/Melora/releases)

Установщик включает всё для запуска Python-кода и при необходимости установит Microsoft Edge WebView2 Runtime. Для поиска и воспроизведения требуется интернет. Лайки и плейлисты установленной версии сохраняются в `%LOCALAPPDATA%\Melora\music_data.db` и сохраняются при переустановке.

## Сборка установщика

Нужны Windows x64, Python 3.11 или новее и Inno Setup 6.7 или новее. Откройте PowerShell в корне репозитория.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\installer\build-windows.ps1 -Python .\.venv\Scripts\python.exe -Iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

Готовый установщик появится в `dist\Melora-Setup.exe`.

Для запуска из исходников установите `requirements.txt` в окружение `.venv` и соберите `Melora.exe` через `.\launcher\build.ps1`. Версия из исходников хранит музыкальную базу рядом с кодом.
