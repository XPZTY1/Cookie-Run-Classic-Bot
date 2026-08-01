Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\run_hidden.bat"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c """ & batPath & """", 0, False