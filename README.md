# Melora

![Логотип Melora](static/melora-logo.png)

Melora — музыкальный плеер для Windows. Он ищет песни и артистов, хранит любимые треки и плейлисты локально и подбирает похожие записи в «Моей волне».

## Запуск из исходников

Нужны Windows x64, Python 3.11 или новее, Microsoft Edge WebView2 Runtime и доступ к интернету для поиска и воспроизведения.

В корне проекта выполните в PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\launcher\build.ps1
```

Откройте созданный `Melora.exe`. Чтобы запускать плеер с рабочего стола, создайте ярлык на этот файл в Проводнике. Все компоненты приложения должны оставаться в папке проекта.

Сборка загружает SDK WebView2 из NuGet. Если на компьютере нет среды выполнения, её можно установить с сайта Microsoft. [Скачать WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)

Музыкальная библиотека создаётся при первом запуске в локальном файле `music_data.db`. Для поиска и рекомендаций Melora обращается к внешним музыкальным каталогам. Доступность конкретных записей зависит от источников.
