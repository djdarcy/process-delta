#NoEnv
SendMode Input
#Include %A_ScriptDir%\ahk_common.ahk

; Function to open Discord and navigate to a specific channel
; action: "toggle" (minimize/restore behavior) or "check" (activate only behavior)
OpenDiscordChannel(channelName, action = "check") {
  appExeName := "discord.exe"
  launchCommand := A_LocalAppData "\Discord\Update.exe --processStart Discord.exe"
  
  ; Choose the window function based on action parameter
  windowFound := false
  if (action = "toggle") {
    ; Try to toggle window state if app is running
    ; if (ToggleWindowState(appExeName)) {
    windowFound := ToggleWindowState(appExeName)
  } else {
    ; Try to activate window if app is running
    ; if (CheckWindowActive(appExeName)) {
    windowFound := CheckWindowActive(appExeName)
  }
  
  if (windowFound) {
    ; If the window was found and is now active, navigate to channel
    if WinActive("ahk_exe " . appExeName) {
      Sleep, 25
      Send, ^k  ; Open Quick Switcher
      Sleep, 200
      Send, % channelName  ; Type the channel name
      Sleep, 500
      Send, {Enter}  ; Select the channel
    }
  } else {
    ; If app is not running, launch it
    Run, %launchCommand%
    ; Could add Sleep and auto-navigation after launch if desired
  }
  Return
}
