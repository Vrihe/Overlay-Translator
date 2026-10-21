; Inno Setup script for Translator Overlay (Inno Setup 6.3+).
;
; Packs the onedir build in dist\TranslatorOverlay\ into one Setup.exe.
; Built by `python build.py --installer`, which passes the version:
;     ISCC.exe /DAppVersion=1.0.0 installer\TranslatorOverlay.iss
;
; Installs per user by default (%LOCALAPPDATA%\Programs, no admin rights), so the
; app runs unelevated and its global hotkeys work; the first page can switch to an
; all-users install in Program Files. The install dir is never written to at run
; time: settings, history, logs and downloaded models live in
; %APPDATA%\translator-overlay\ and survive updates and uninstall.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define AppName "Translator Overlay"
#define AppExe "TranslatorOverlay.exe"
#define RootDir ".."

[Setup]
; Keep AppId fixed forever: it is how updates find the existing install.
AppId={{0DF3004C-2D3C-431A-8BCA-DC181526B77D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Vrihe
AppPublisherURL=https://github.com/Vrihe/Overlay-Translator
AppSupportURL=https://github.com/Vrihe/Overlay-Translator/issues
AppUpdatesURL=https://github.com/Vrihe/Overlay-Translator/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#RootDir}\dist\installer
OutputBaseFilename=TranslatorOverlay-Setup-{#AppVersion}
SetupIconFile={#RootDir}\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
; The app holds a session mutex (single_instance.py): Setup asks to close it first.
AppMutex=Local\TranslatorOverlay.SingleInstance.Mutex
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
russian.AutoStart=Запускать вместе с Windows
english.AutoStart=Start with Windows
russian.OtherTasks=Дополнительно:
english.OtherTasks=Other:

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "{cm:AutoStart}"; GroupDescription: "{cm:OtherTasks}"; Flags: unchecked

[Files]
Source: "{#RootDir}\dist\TranslatorOverlay\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RootDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RootDir}\MODEL_LICENSE.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[InstallDelete]
; An update replaces the whole bundle: no stale modules left from the previous build.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
; Same AppUserModelID as main.py, so a pinned shortcut and the running app share one taskbar button.
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "Vrihe.TranslatorOverlay"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "Vrihe.TranslatorOverlay"; Tasks: desktopicon

[Registry]
; HKA: the current user for a per-user install, all users for a Program Files one.
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "TranslatorOverlay"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
