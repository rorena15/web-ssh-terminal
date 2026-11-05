' Web SSH Terminal - run without a console window (pythonw)
' Already running -> only opens the window. Errors: message box + data\server.log
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run "pythonw.exe """ & dir & "\server.py"" --open --trust --auto-exit", 0, False
