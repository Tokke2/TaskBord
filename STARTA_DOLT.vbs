' Ledgebord - startar utan svart konsollfonster.
' Kor FORSTA_START.bat /snabb i ett dolt fonster (hittar nyaste Python och startar pythonw).
' Gar det fel (t.ex. Python saknas) oppnar FORSTA_START.bat ett synligt installationsfonster.
Dim sh, fso, dir
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run "cmd /c """"" & dir & "\FORSTA_START.bat"" /snabb""", 0, False
