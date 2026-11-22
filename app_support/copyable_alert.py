from __future__ import annotations

import base64
import hashlib
import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

TITLE, MESSAGE, ICON = "HAGLIO_ALERT_TITLE", "HAGLIO_ALERT_MESSAGE", "HAGLIO_ALERT_ICON"
APP_ICON, APP_ID = "HAGLIO_ALERT_APP_ICON", "HAGLIO_ALERT_APP_ID"
ERROR, WARNING, INFORMATION = 16, 48, 64
COPY = "Copy error message"
COPIED = "Copied"
COPY_TIP = "Copies this window's title and message, ready to paste"
COPIED_SHOWN_MS = 2000


def said(title: str, message: str) -> str:
    return f"{title}\n\n{message}"


def taskbar_identity(app: str) -> str:
    """The AppUserModelID an error window of *app* claims where its process has none: unclaimed, Windows draws the taskbar button with the icon of the program running it, Python's or PowerShell's."""
    return f"Haglio.Alert.{hashlib.sha256(app.encode('utf-8')).hexdigest()[:16]}"


_CLAIMS_A_TASKBAR_IDENTITY = f"""\
$appIcon = $env:{APP_ICON}
$wearsTheAppsIcon = $appIcon -and (Test-Path -LiteralPath $appIcon -PathType Leaf)
if ($wearsTheAppsIcon) {{
  Add-Type -Namespace Haglio -Name Taskbar -MemberDefinition '[DllImport("shell32.dll", CharSet = CharSet.Unicode)] public static extern int SetCurrentProcessExplicitAppUserModelID(string id);'
  if ([Haglio.Taskbar]::SetCurrentProcessExplicitAppUserModelID($env:{APP_ID}) -lt 0) {{ $wearsTheAppsIcon = $false }}
}}
"""
_WEARS_THE_APPS_ICON = """\
$form.ShowIcon = $wearsTheAppsIcon
if ($wearsTheAppsIcon) { $form.Icon = New-Object System.Drawing.Icon $appIcon }
"""
_WEARS_NO_ICON = "$form.ShowIcon = $false\n"
_THE_APPS_ICON, _THE_WINDOWS_ICON = "#the-apps-icon\n", "#the-windows-icon\n"

_SCRIPT = f"""\
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
{_THE_APPS_ICON}$title = $env:{TITLE}
$message = $env:{MESSAGE}
$icon = switch ($env:{ICON}) {{
  '{WARNING}' {{ [System.Drawing.SystemIcons]::Warning }}
  '{INFORMATION}' {{ [System.Drawing.SystemIcons]::Information }}
  default {{ [System.Drawing.SystemIcons]::Error }}
}}
$form = New-Object System.Windows.Forms.Form
$form.Text = $title
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
{_THE_WINDOWS_ICON}$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$form.AutoSize = $true
$form.AutoSizeMode = 'GrowAndShrink'
$form.Padding = New-Object System.Windows.Forms.Padding 12
$rows = New-Object System.Windows.Forms.TableLayoutPanel
$rows.AutoSize = $true
$rows.ColumnCount = 2
$rows.RowCount = 2
$picture = New-Object System.Windows.Forms.PictureBox
$picture.Image = $icon.ToBitmap()
$picture.SizeMode = 'AutoSize'
$picture.Margin = New-Object System.Windows.Forms.Padding 0, 0, 12, 12
$said = New-Object System.Windows.Forms.Label
$said.Text = $message
$said.AutoSize = $true
$said.MaximumSize = New-Object System.Drawing.Size 480, 0
$said.Margin = New-Object System.Windows.Forms.Padding 0, 0, 0, 12
$buttons = New-Object System.Windows.Forms.FlowLayoutPanel
$buttons.AutoSize = $true
$buttons.FlowDirection = 'RightToLeft'
$buttons.Dock = 'Fill'
$ok = New-Object System.Windows.Forms.Button
$ok.Text = 'OK'
$ok.DialogResult = 'OK'
$copy = New-Object System.Windows.Forms.Button
$copy.AutoSize = $true
$copy.Text = '{COPY}'
$copy.MinimumSize = $copy.GetPreferredSize([System.Drawing.Size]::Empty)
(New-Object System.Windows.Forms.ToolTip).SetToolTip($copy, "{COPY_TIP}")
$back = New-Object System.Windows.Forms.Timer
$back.Interval = {COPIED_SHOWN_MS}
$back.Add_Tick({{
  $back.Stop()
  $copy.Text = '{COPY}'
}})
$copy.Add_Click({{
  [System.Windows.Forms.Clipboard]::SetText($title + "`r`n`r`n" + $message)
  $copy.Text = '{COPIED}'
  $back.Stop()
  $back.Start()
}})
$buttons.Controls.Add($ok)
$buttons.Controls.Add($copy)
$rows.Controls.Add($picture, 0, 0)
$rows.Controls.Add($said, 1, 0)
$rows.Controls.Add($buttons, 0, 1)
$rows.SetColumnSpan($buttons, 2)
$form.Controls.Add($rows)
$form.AcceptButton = $ok
$form.Add_Shown({{ $form.Activate() }})
$form.Opacity = 0
$form.Show()
$form.Hide()
$form.Opacity = 1
[void]$form.ShowDialog()
"""

SCRIPT = _SCRIPT.replace(_THE_APPS_ICON, _CLAIMS_A_TASKBAR_IDENTITY).replace(_THE_WINDOWS_ICON, _WEARS_THE_APPS_ICON)
SCRIPT_BEFORE_THE_APPS_ICON = _SCRIPT.replace(_THE_APPS_ICON, "").replace(_THE_WINDOWS_ICON, _WEARS_NO_ICON)


def _command(script: str) -> tuple[str, ...]:
    return ("powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode("ascii"))


COMMAND = _command(SCRIPT)
COMMAND_BEFORE_THE_APPS_ICON = _command(SCRIPT_BEFORE_THE_APPS_ICON)


def environment(title: str, message: str, icon: int, *, app_icon: Path | None = None,
                inherited: Mapping[str, str] = os.environ) -> dict[str, str]:
    told = {**inherited, TITLE: title, MESSAGE: message, ICON: str(icon)}
    if app_icon is not None:
        told |= {APP_ICON: str(app_icon), APP_ID: taskbar_identity(str(app_icon))}
    return told


def show(title: str, message: str, icon: int = ERROR, *, app_icon: Path | None = None,
         run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bool:
    try:
        shown = run(COMMAND, env=environment(title, message, icon, app_icon=app_icon),
                    creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    except OSError:
        return False
    return shown.returncode == 0
