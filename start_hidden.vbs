' Starts the assistant in the system tray with no console window.
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run """" & root & "\.venv\Scripts\pythonw.exe"" """ & root & "\start_tray.pyw""", 0, False
