' Installs/updates Python packages silently; output goes to update.log.
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = "cmd /c cd /d """ & root & """ && "".venv\Scripts\python.exe"" -m pip install -r requirements.txt > update.log 2>&1"
CreateObject("WScript.Shell").Run cmd, 0, True
