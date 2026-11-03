Option Explicit

Dim shell, files, projectPath, pythonPath, entryPath, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
projectPath = files.GetParentFolderName(WScript.ScriptFullName)
pythonPath = files.BuildPath(projectPath, ".venv\Scripts\pythonw.exe")
entryPath = files.BuildPath(projectPath, "desktop.py")

If Not files.FileExists(pythonPath) Then
    MsgBox "Virtual environment missing. Run: uv sync --extra desktop", 16, "MMPFP"
    WScript.Quit 1
End If

shell.CurrentDirectory = projectPath
command = Chr(34) & pythonPath & Chr(34) & " " & Chr(34) & entryPath & Chr(34)
' uv's pythonw.exe may be a console trampoline. Hide it from process creation.
shell.Run command, 0, False
