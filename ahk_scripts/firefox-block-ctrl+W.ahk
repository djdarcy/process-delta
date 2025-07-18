#NoEnv
SendMode Input
SetWorkingDir %A_ScriptDir%

; ── Only in Firefox ──
#IfWinActive ahk_class MozillaWindowClass
^w::
    ; Build the PS command in pieces so we don’t have to wrestle with quoting in one giant literal
    psCmd := "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > `$null; "
    psCmd .= "$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent('ToastText01'); "
    psCmd .= "$xml.GetElementsByTagName('text')[0].AppendChild($xml.CreateTextNode('Ctrl+W blocked in Firefox')); "
    psCmd .= "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
    psCmd .= "$toast.SuppressPopup = `$true; "
    psCmd .= "$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AHK CtrlW Blocker'); "
    psCmd .= "$notifier.Show($toast)"

    ; Run it hidden via cmd → PowerShell
    Run, %ComSpec% /c powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command "%psCmd%",, Hide
Return
#IfWinActive
