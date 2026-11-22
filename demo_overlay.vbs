Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run """" & root & "\.venv\Scripts\pythonw.exe"" """ & root & "\demo_overlay.py""", 0, False
