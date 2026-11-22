param([string]$Package)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$version = '1.0.3912.50'
$runtime = Join-Path $PSScriptRoot 'runtime'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$downloaded = !$Package

if ($downloaded) {
    $Package = Join-Path ([IO.Path]::GetTempPath()) "Melora-WebView2-$([guid]::NewGuid()).nupkg"
}

try {
    if ($downloaded) {
        $url = "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$version/microsoft.web.webview2.$version.nupkg"
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $Package
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $archive = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $Package).Path)
    try {
        foreach ($file in @(
            'lib/net462/Microsoft.Web.WebView2.Core.dll',
            'lib/net462/Microsoft.Web.WebView2.WinForms.dll',
            'runtimes/win-x64/native/WebView2Loader.dll', 'LICENSE.txt', 'NOTICE.txt'
        )) {
            $entry = $archive.GetEntry($file)
            if (!$entry) { throw "WebView2 SDK package is missing $file" }
            $target = Join-Path $runtime ([IO.Path]::GetFileName($file))
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
        }
    } finally {
        $archive.Dispose()
    }

    $appIcon = Join-Path $project 'static\melora.ico'
    $source = Join-Path $PSScriptRoot 'MeloraLauncher.cs'
    $appExe = Join-Path $project 'Melora.exe'
    $core = Join-Path $runtime 'Microsoft.Web.WebView2.Core.dll'
    $forms = Join-Path $runtime 'Microsoft.Web.WebView2.WinForms.dll'
    $arguments = @('/nologo', '/platform:x64', '/target:winexe', '/optimize+', "/win32icon:$appIcon",
        "/out:$appExe", '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
        "/reference:$core", "/reference:$forms", $source)
    & $compiler @arguments
    if ($LASTEXITCODE -ne 0) { throw "Unable to compile Melora.exe ($LASTEXITCODE)" }
    Write-Host "Built $appExe"
} finally {
    if ($downloaded -and (Test-Path -LiteralPath $Package)) {
        Remove-Item -LiteralPath $Package
    }
}
