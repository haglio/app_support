from __future__ import annotations

import base64
import os
import subprocess
from collections.abc import Callable, Mapping

TITLE, MESSAGE, ICON = "HAGLIO_ALERT_TITLE", "HAGLIO_ALERT_MESSAGE", "HAGLIO_ALERT_ICON"
ERROR, WARNING, INFORMATION = 16, 48, 64
COPY = "Copy error message"
COPIED = "Copied"
COPY_TIP = "Copies this window's title and message, ready to paste"
COPIED_SHOWN_MS = 2000


def said(title: str, message: str) -> str:
    return f"{title}\n\n{message}"


SCRIPT = f"""\
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$title = $env:{TITLE}
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
$form.ShowIcon = $false
$form.StartPosition = 'CenterScreen'
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

ENCODED = base64.b64encode(SCRIPT.encode("utf-16-le")).decode("ascii")
COMMAND = ("powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-EncodedCommand", ENCODED)


def environment(title: str, message: str, icon: int, *,
                inherited: Mapping[str, str] = os.environ) -> dict[str, str]:
    return {**inherited, TITLE: title, MESSAGE: message, ICON: str(icon)}


def show(title: str, message: str, icon: int = ERROR, *,
         run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bool:
    try:
        shown = run(COMMAND, env=environment(title, message, icon),
                    creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    except OSError:
        return False
    return shown.returncode == 0
