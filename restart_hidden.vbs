' Stops any running assistant (tray) and starts a fresh one, with no console window.
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='pythonw.exe'")
For Each p In procs
  If InStr(LCase(p.CommandLine & ""), "ableton-assistant") > 0 Then p.Terminate()
Next
WScript.Sleep 1500
CreateObject("WScript.Shell").Run """" & root & "\.venv\Scripts\pythonw.exe"" """ & root & "\start_tray.pyw""", 0, False
