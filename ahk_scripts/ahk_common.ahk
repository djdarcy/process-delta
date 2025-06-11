; Common functions for AHK scripts

; Function to toggle window state (minimize/restore)
ToggleWindowState(execName) {
  if WinExist("ahk_exe " . execName) {
    WinGet, windowState, MinMax, % "ahk_exe " . execName
    
    ; windowState is 1 for maximized, 0 for normal, -1 for minimized
    if (windowState = -1) {  ; If window is minimized
      WinRestore, % "ahk_exe " . execName
      WinActivate, % "ahk_exe " . execName
      return true
    } else {  ; If window is normal or maximized
      WinMinimize, % "ahk_exe " . execName
      return true
    }
  }
  return false
}

; Function to check if a window exists and activate it if it does
CheckWindowActive(execName) {
  if WinExist("ahk_exe " . execName) {
    WinGet, windowState, MinMax, % "ahk_exe " . execName
    
    ; windowState is 1 for maximized, 0 for normal, -1 for minimized
    if (windowState = -1) {  ; If window is minimized
      WinRestore, % "ahk_exe " . execName
    }
    WinActivate, % "ahk_exe " . execName
    return true
  }
  return false
}

; Function to find application path from a list of possible paths
FindAppPath(paths, minVersion = "") {
  for index, path in paths {
    if FileExist(path) {
      if (minVersion != "") {
        FileGetVersion, appVersion, %path%
        if (appVersion < minVersion) {
          MsgBox, Version %appVersion% is below required version %minVersion%
          return ""
        }
      }
      return path
    }
  }
  MsgBox, Application not found in any of the specified locations.
  return ""
}
