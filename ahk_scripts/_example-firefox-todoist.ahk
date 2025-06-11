#NoEnv
SendMode Input
#Include %A_ScriptDir%\launcher-common.ahk
#Include %A_ScriptDir%\ahk_common.ahk

; Define application-specific variables
appExeName := "firefox.exe"
appPaths := ["C:\app\net\client\browser\Firefox\120.0.1\firefox.exe", "C:\Program Files\Mozilla Firefox\firefox.exe"]
minVersion := "120.0.1" 
appUrl := "https://todoist.com"

^+q::
{
  appPath := FindAppPath(appPaths, minVersion)
  if (appPath != "") {
    LaunchOrToggleBrowser(appExeName, appPath, appUrl, "toggle")
  }
  Return
}
return