#ifndef MeloraVersion
  #define MeloraVersion "0.1.0"
#endif

[Setup]
AppId={{AB3C0BA3-6070-483F-A4B8-3C7567239FCB}
AppName=Melora
AppVersion={#MeloraVersion}
AppPublisher=Melora
AppPublisherURL=https://github.com/Adiran03/Melora
DefaultDirName={localappdata}\Programs\Melora
DefaultGroupName=Melora
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppMutex=Local\Melora.Desktop
OutputBaseFilename=Melora-Setup
SetupIconFile=..\static\melora.ico
UninstallDisplayIcon={app}\Melora.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#WebViewBootstrapper}"; DestName: "MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy noencryption
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Melora"; Filename: "{app}\Melora.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Melora"; Filename: "{app}\Melora.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Melora.exe"; Description: "{cm:LaunchProgram,Melora}"; Flags: nowait postinstall skipifsilent

[Code]
function HasWebView2(RootKey: Integer): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey,
    'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)
    and (Version <> '') and (Version <> '0.0.0.0');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if HasWebView2(HKLM32) or HasWebView2(HKCU) then
    Exit;
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'),
    '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
  begin
    if ActiveLanguage = 'russian' then
      Result := 'Не удалось установить Microsoft Edge WebView2 Runtime. Проверьте интернет-соединение и повторите установку.'
    else
      Result := 'Microsoft Edge WebView2 Runtime could not be installed. Check your internet connection and try again.';
  end;
end;
