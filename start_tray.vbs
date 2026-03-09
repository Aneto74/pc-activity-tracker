Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
strDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
' Window style 0 = hidden, False = don't wait
objShell.Run "python """ & strDir & "\run.py""", 0, False
