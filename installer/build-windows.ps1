param(
    [string]$Python = 'python',
    [string]$Iscc = 'ISCC.exe',
    [string]$Version = '0.1.0',
    [string]$BuildPath,
    [string]$OutputPath,
    [string]$WebViewSdk,
    [string]$WebViewBootstrapper
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
if (!(Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command $Python -ErrorAction Stop).Source
} else {
    $Python = (Resolve-Path -LiteralPath $Python).Path
}
if (!(Test-Path -LiteralPath $Iscc)) {
    $Iscc = (Get-Command $Iscc -ErrorAction Stop).Source
} else {
    $Iscc = (Resolve-Path -LiteralPath $Iscc).Path
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Version must look like 0.1.0.' }
if (!$BuildPath) {
    $BuildPath = Join-Path ([IO.Path]::GetTempPath()) "Melora-build-$([Guid]::NewGuid())"
}
if (!$OutputPath) { $OutputPath = Join-Path $project 'dist' }
$build = (New-Item -ItemType Directory -Force -Path $BuildPath).FullName
$output = (New-Item -ItemType Directory -Force -Path $OutputPath).FullName
$native = Join-Path $build 'native'
$payload = (New-Item -ItemType Directory -Force -Path (Join-Path $build 'app')).FullName
if ((Get-ChildItem -LiteralPath $payload -Force | Measure-Object).Count) {
    throw "Build path already contains an application. Select a new BuildPath."
}
New-Item -ItemType Directory -Force -Path "$native\launcher", "$native\static" | Out-Null
Copy-Item -LiteralPath "$project\launcher\build.ps1", "$project\launcher\MeloraLauncher.cs" -Destination "$native\launcher"
Copy-Item -LiteralPath "$project\static\melora.ico" -Destination "$native\static"
if ($WebViewSdk) { $WebViewSdk = (Resolve-Path -LiteralPath $WebViewSdk).Path }
& "$native\launcher\build.ps1" -Package $WebViewSdk
Copy-Item -LiteralPath "$native\Melora.exe" -Destination $payload
Copy-Item -LiteralPath "$native\launcher" -Destination "$payload\launcher" -Recurse
Remove-Item -LiteralPath "$payload\launcher\build.ps1", "$payload\launcher\MeloraLauncher.cs"

$versionFiles = @(
    "$project\main.py", "$project\desktop.py", "$project\database.py", "$project\music_engine.py",
    "$project\static\index.html", "$project\static\app.js", "$project\static\style.css"
)
$fingerprint = (($versionFiles | Get-FileHash -Algorithm SHA256).Hash -join '')
$sha256 = [Security.Cryptography.SHA256]::Create()
try {
    $hash = [BitConverter]::ToString($sha256.ComputeHash([Text.Encoding]::ASCII.GetBytes($fingerprint)))
    $revision = $hash.Replace('-', '').Substring(0, 12).ToLowerInvariant()
} finally { $sha256.Dispose() }
$revisionPath = Join-Path $build 'app_revision.txt'
[IO.File]::WriteAllText($revisionPath, "$Version-$revision", [Text.Encoding]::ASCII)

$arguments = @('-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed', '--noupx',
    '--name', 'Melora.Server', '--distpath', "$build\frozen", '--workpath', "$build\python",
    '--specpath', $build, '--collect-submodules', 'uvicorn', '--collect-submodules', 'anyio', '--exclude-module', 'pytest',
    '--add-data', "${project}\static:static", '--add-data', "${revisionPath}:.", "$project\desktop.py")
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw "The Melora backend could not be packaged ($LASTEXITCODE)." }
Copy-Item -LiteralPath "$build\frozen\Melora.Server" -Destination "$payload\backend" -Recurse
& $Python -B "$PSScriptRoot\copy-notices.py" "$payload\licenses"
if ($LASTEXITCODE -ne 0) { throw "Could not collect third-party notices." }

if (!$WebViewBootstrapper) {
    $WebViewBootstrapper = Join-Path $build 'MicrosoftEdgeWebview2Setup.exe'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $WebViewBootstrapper
}
$WebViewBootstrapper = (Resolve-Path -LiteralPath $WebViewBootstrapper).Path
$signature = Get-AuthenticodeSignature -LiteralPath $WebViewBootstrapper
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
    throw 'The Microsoft Edge WebView2 bootstrapper signature could not be verified.'
}

$arguments = @("/DMeloraVersion=$Version", "/DPackageDir=$payload", "/DWebViewBootstrapper=$WebViewBootstrapper",
    "/O$output", "$PSScriptRoot\Melora.iss")
& $Iscc @arguments
if ($LASTEXITCODE -ne 0) { throw "The Melora installer could not be compiled ($LASTEXITCODE)." }
Get-Item -LiteralPath "$output\Melora-Setup.exe" | Select-Object FullName, Length
