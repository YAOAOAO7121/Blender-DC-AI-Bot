<#
  開機自動啟動機器人：開／關
  雙擊 autostart.bat：目前開著就關掉，關著就打開
  install.ps1 也用它：autostart.ps1 -On / -Off（加 -Quiet 不顯示訊息、不等按鍵）
#>
param([switch]$On, [switch]$Off, [switch]$Quiet)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$Root = $PSScriptRoot
$StartBat = Join-Path $Root 'start-bot.bat'
$Icon = Join-Path $Root 'assets\start.ico'
$Lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Blender AI 教學助理.lnk'

function Done($text, $color = 'Green') {
    if ($Quiet) { return }
    Write-Host ''
    Write-Host "  $text" -ForegroundColor $color
    Write-Host ''
    Read-Host '按 Enter 關閉'
}

# 建捷徑：先在英文路徑建好再搬過去（建捷徑的 Windows 元件遇到系統語系以外的字會出錯）
function Make-Shortcut($path, $target, $icon) {
    $tmpDir = if ($env:PUBLIC -and (Test-Path $env:PUBLIC)) { $env:PUBLIC } else { $env:TEMP }
    $tmpName = "bot-shortcut-$([guid]::NewGuid().ToString('N')).lnk"
    $tmp = Join-Path $tmpDir $tmpName
    $hasIcon = $icon -and (Test-Path $icon)
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($tmp)
    try {
        $s.TargetPath = $target
        $s.WorkingDirectory = $Root
        if ($hasIcon) { $s.IconLocation = "$icon,0" }
        $s.Save()
    } catch {
        # 資料夾路徑有系統語系以外的字 → 先存空捷徑，再用支援 Unicode 的 Shell.Application 填內容
        $s = (New-Object -ComObject WScript.Shell).CreateShortcut($tmp)
        $s.TargetPath = "$env:WINDIR\System32\cmd.exe"
        $s.Save()
        $link = (New-Object -ComObject Shell.Application).NameSpace($tmpDir).ParseName($tmpName).GetLink
        $link.Path = $target
        $link.WorkingDirectory = $Root
        if ($hasIcon) { $link.SetIconLocation($icon, 0) }
        $link.Save()
    }
    Move-Item -LiteralPath $tmp -Destination $path -Force
}

$enabled = Test-Path -LiteralPath $Lnk
$want = if ($On) { $true } elseif ($Off) { $false } else { -not $enabled }

if (-not $want) {
    Remove-Item -LiteralPath $Lnk -ErrorAction SilentlyContinue
    Done '已關閉：開機後不會自動啟動機器人（要用時按桌面的「使用小樽影分身之術」）' 'Yellow'
} elseif (-not (Test-Path $StartBat)) {
    Done '找不到 start-bot.bat，請先執行 install.bat' 'Red'
    exit 1
} else {
    Make-Shortcut $Lnk $StartBat $Icon   # 每次重建，確保指到這個資料夾
    Done '已開啟：電腦開機後會自動啟動機器人（再雙擊一次 autostart.bat 就會關掉）'
}
