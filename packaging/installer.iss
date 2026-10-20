; Inno Setup 6 스크립트 — 사용자별 설치(관리자 권한 불필요), 시작 메뉴·바탕화면 바로가기
; 빌드: packaging\build.ps1 (ISCC /DAppVersion=x.y.z [/DOffline=1] packaging\installer.iss)
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "Lecture TTS"
#ifdef Offline
  #define Suffix "-offline"
#else
  #define Suffix ""
#endif

[Setup]
AppId={{6C1F4E7A-2B1D-4C5B-9F0E-3A7D2E8B1C40}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Lecture TTS
DefaultDirName={localappdata}\Programs\LectureTTS
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=LectureTTS-{#AppVersion}{#Suffix}-setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayIcon={app}\LectureTTS.exe
LicenseFile=..\dist\LectureTTS\THIRD_PARTY_LICENSES.txt

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면 바로가기 만들기"; GroupDescription: "추가 작업:"

[Files]
Source: "..\dist\LectureTTS\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\LectureTTS.exe"
Name: "{group}\예제 스크립트"; Filename: "{app}\samples"
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\LectureTTS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LectureTTS.exe"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent

[Code]
// 제거 시 사용자 데이터(설정·발음 사전·캐시·모델) 삭제 여부를 묻는다. 업데이트 설치 시에는 유지된다.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var DataDir: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\LectureTTS');
    if DirExists(DataDir) then
      // 무인 제거(/SUPPRESSMSGBOXES)에서는 묻지 않고 '아니요'(데이터 유지)로 처리
      if SuppressibleMsgBox('설정·발음 사전·캐시·모델(' + DataDir + ')도 삭제할까요?', mbConfirmation, MB_YESNO, IDNO) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
