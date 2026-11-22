' Stops any running assistant (tray) and starts a fresh one, with no console window.
' Writes what it did to restart.log.
On Error Resume Next
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
Set log = fso.OpenTextFile(root & "\restart.log", 2, True)
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
If Err.Number <> 0 Then log.WriteLine "WMI error: " & Err.Description: Err.Clear
Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='pythonw.exe'")
n = 0
For Each p In procs
  cl = LCase(p.CommandLine & "")
  log.WriteLine "found pythonw pid=" & p.ProcessId & " cmd=" & cl
  If InStr(cl, "ableton-assistant") > 0 Then
    rc = p.Terminate()
    log.WriteLine "terminate rc=" & rc & " err=" & Err.Description
    Err.Clear
    n = n + 1
  End If
Next
log.WriteLine "terminated " & n
WScript.Sleep 1500
CreateObject("WScript.Shell").Run """" & root & "\.venv\Scripts\pythonw.exe"" """ & root & "\start_tray.pyw""", 0, False
log.WriteLine "launched err=" & Err.Description
log.Close
