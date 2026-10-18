import base64
import os
import subprocess
from typing import List

PS_MULTI_FILES = """
Add-Type -AssemblyName System.Windows.Forms
$form = New-Object System.Windows.Forms.Form
$form.TopMost = $true
$form.Opacity = 0
$form.Show()
$form.BringToFront()
$f = New-Object System.Windows.Forms.OpenFileDialog
$f.Multiselect = $true
$f.Title = "Select Files to Share (Hold Ctrl or Shift to select multiple)"
$f.Filter = "All Files (*.*)|*.*"
$f.RestoreDirectory = $true
if ($f.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {
    $f.FileNames | ForEach-Object { [Console]::WriteLine($_) }
}
$form.Dispose()
"""

PS_FOLDER = """
Add-Type -AssemblyName System.Windows.Forms
$form = New-Object System.Windows.Forms.Form
$form.TopMost = $true
$form.Opacity = 0
$form.Show()
$form.BringToFront()
$f = New-Object System.Windows.Forms.FolderBrowserDialog
$f.Description = "Select Entire Folder to Share"
$f.ShowNewFolderButton = $false
if ($f.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::WriteLine($f.SelectedPath)
}
$form.Dispose()
"""

def _run_powershell_dialog(script: str) -> List[str]:
    try:
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        res = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        paths = [p.strip() for p in res.stdout.splitlines() if p.strip()]
        return paths
    except Exception as e:
        print(f"[FilePicker] PowerShell dialog error: {e}")
        return []

def pick_files() -> List[str]:
    """Open native file dialog to select multiple files without thread blocking."""
    if os.name == "nt":
        paths = _run_powershell_dialog(PS_MULTI_FILES)
        if paths:
            return paths

    # Secondary Tkinter fallback
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askopenfilenames(
            title="Select Files to Share (Hold Ctrl or Shift to select multiple)"
        )
        root.destroy()
        return list(selected) if selected else []
    except Exception as e:
        print(f"[FilePicker] Fallback error: {e}")
        return []

def pick_folder() -> List[str]:
    """Open native folder dialog and return all files contained inside."""
    folder_path = None
    if os.name == "nt":
        res = _run_powershell_dialog(PS_FOLDER)
        if res:
            folder_path = res[0]

    if not folder_path:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder_path = filedialog.askdirectory(title="Select Entire Folder to Share")
            root.destroy()
        except Exception:
            pass

    if not folder_path or not os.path.isdir(folder_path):
        return []

    file_list = []
    for root_dir, _, filenames in os.walk(folder_path):
        for filename in filenames:
            file_list.append(os.path.join(root_dir, filename))
    return file_list
