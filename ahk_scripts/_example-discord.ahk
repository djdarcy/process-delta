#NoEnv
SendMode Input
#Include %A_ScriptDir%\discord-common.ahk

^+j::
{
  OpenDiscordChannel("ExampleChannel")
  Return
}
return