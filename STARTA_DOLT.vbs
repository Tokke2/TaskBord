' Ledgebord - startar utan svart konsollfonster.
' Kor FORSTA_START.bat /snabb i ett dolt fonster (hittar systemets Python och startar pythonw).
' Gar det fel (t.ex. Python saknas) oppnar FORSTA_START.bat ett synligt installationsfonster.
Dim sh, fso, dir
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
' Markerar for FORSTA_START.bat att det redan ar dolt (annars startar den om sig via denna fil igen).
sh.Environment("PROCESS")("LEDGEBORD_DOLD") = "1"
sh.Run "cmd /c """"" & dir & "\FORSTA_START.bat"" /snabb""", 0, False
