#NoEnv
SendMode Input
#Include %A_ScriptDir%\ahk_common.ahk

; Function to launch or toggle an application with optional URL
; action: "toggle" (minimize/restore behavior) or "check" (activate only behavior)
LaunchOrToggleApp(execName, launchPath, launchParam = "", action = "check") {
  ; Choose the window function based on action parameter
  if (action = "toggle") {
    ; Try to toggle window state if app is running
    ; if (ToggleWindowState(execName)) {
    if (ToggleWindowState(execName)) {
      ; App was found and toggled
      return
    } else {
      ; App not running, launch it
      if (launchParam != "") {
        Run, "%launchPath%" "%launchParam%"
      } else {
        Run, "%launchPath%"
      }
    }
  } else {
    ; Try to activate window if app is running
    ; if (CheckWindowActive(execName)) {
    if (CheckWindowActive(execName)) {
      ; App was found and activated
      return
    } else {
      ; App not running, launch it
      if (launchParam != "") {
        Run, "%launchPath%" "%launchParam%"
      } else {
        Run, "%launchPath%"
      }
    }
  }
  Return
}

; Function to launch or toggle a browser with a URL
; action: "toggle" (minimize/restore behavior) or "check" (activate only behavior)
LaunchOrToggleBrowser(execName, browserPath, url, action = "check") {
  ; Choose the window function based on action parameter
  if (action = "toggle") {
    ; Try to toggle window state if browser is running
    ; if (ToggleWindowState(execName)) {
    if (ToggleWindowState(execName)) {
      ; Browser was found and toggled
      return
    } else {
      ; Browser not running, launch it with URL
      Run, "%browserPath%" "%url%"
    }
  } else {
    ; Try to activate window if browser is running
    ; if (CheckWindowActive(execName)) {
    if (CheckWindowActive(execName)) {
      ; Browser was found and activated
      return
    } else {
      ; Browser not running, launch it with URL
      Run, "%browserPath%" "%url%"
    }
  }
  Return
}
