<#
  Blender 課程 AI 教學助理｜一鍵安裝（Windows）

  用法：雙擊 install.bat
  或在沒有程式的電腦上，於終端機貼上（會自動下載程式）：
    powershell -ExecutionPolicy Bypass -c "[Net.ServicePointManager]::SecurityProtocol='Tls12'; iwr https://raw.githubusercontent.com/YAOAOAO7121/Blender-DC-AI-Bot/main/install.ps1 -UseBasicParsing -OutFile $env:TEMP\bot-install.ps1; & $env:TEMP\bot-install.ps1"

  會做的事：
    1. 沒有 Python / Git 就用 winget 自動安裝
    2. 下載（或更新）機器人程式，建立 .venv 並安裝套件
    3. 確認 Ollama 有在執行，設定模型常駐顯卡
    4. 依顯卡記憶體挑本地模型、下載、確認整個放得進顯卡
    5. 設定 .env（可沿用舊電腦的 .env），並檢查 Token、金鑰、頻道是否正確
    6. 建立「啟動機器人.bat」，可選擇開機自動啟動
  Ollama 與 Blender 不會自動安裝，只會檢查。
  可以重複執行：已經做好的步驟會跳過。
#>

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

# 沒預料到的錯誤：顯示訊息並停住，不要讓視窗一閃就關掉
trap {
    Write-Host ''
    Write-Host "  [錯誤] 安裝中斷：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  （第 $($_.InvocationInfo.ScriptLineNumber) 行）把這個畫面截圖給助理看" -ForegroundColor Red
    Read-Host '按 Enter 結束'
    exit 1
}

$RepoUrl = 'https://github.com/YAOAOAO7121/Blender-DC-AI-Bot.git'
$ZipUrl = 'https://github.com/YAOAOAO7121/Blender-DC-AI-Bot/archive/refs/heads/main.zip'
$OllamaApi = 'http://localhost:11434'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# 本地模型建議表：顯卡記憶體（GB）→ 模型、上下文長度、資料段落比例
# 模型下載失敗（名稱不存在）時會自動往下一級試
$ModelTiers = @(
    @{ MinGB = 80; Model = 'qwen3.5:122b'; Ctx = 32768; Ratio = '0.5' },
    @{ MinGB = 30; Model = 'qwen3.6:35b';  Ctx = 16384; Ratio = '0.5' },
    @{ MinGB = 22; Model = 'qwen3.6:27b';  Ctx = 16384; Ratio = '0.5' },
    @{ MinGB = 11; Model = 'qwen3.5:9b';   Ctx = 8192;  Ratio = '0.7' },
    @{ MinGB = 5;  Model = 'qwen3:4b';     Ctx = 4096;  Ratio = '0.7' },
    @{ MinGB = 0;  Model = 'qwen2.5:3b';   Ctx = 4096;  Ratio = '0.7' }
)

# ───────────── 小工具 ─────────────

function Step($n, $text) { Write-Host ''; Write-Host "=== $n. $text ===" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "  [OK] $text" -ForegroundColor Green }
function Info($text) { Write-Host "  · $text" }
function Warn($text) { Write-Host "  [注意] $text" -ForegroundColor Yellow }
function Fail($text) {
    Write-Host ''
    Write-Host "  [錯誤] $text" -ForegroundColor Red
    Write-Host ''
    Read-Host '按 Enter 結束'
    exit 1
}

function Ask-YesNo($question, $default = $true) {
    $hint = if ($default) { '[Y/n]' } else { '[y/N]' }
    while ($true) {
        $a = (Read-Host "  $question $hint").Trim().ToLower()
        if ($a -eq '') { return $default }
        if ($a -in @('y', 'yes', '是')) { return $true }
        if ($a -in @('n', 'no', '否')) { return $false }
    }
}

# 貼上的金鑰常夾帶引號、空白、換行或「Bot 」字首 → 清掉
function Clean-Secret($v) {
    $v = "$v".Trim().Trim('"').Trim("'").Trim()
    $v = $v -replace '^(Bot|Bearer)\s+', ''
    return ($v -replace '\s', '')
}
function Mask($v) {
    if ($v.Length -le 10) { return "（$($v.Length) 個字）" }
    return "$($v.Substring(0, 4))…$($v.Substring($v.Length - 4))（$($v.Length) 個字）"
}
# 用一般輸入（看得到內容）：隱藏輸入時 Ctrl+V 在某些視窗貼不進去，又看不出貼錯
function Read-Secret($prompt) {
    while ($true) {
        $v = Clean-Secret (Read-Host "  $prompt（在視窗按右鍵或 Ctrl+V 貼上，再按 Enter）")
        if ($v) { Info "收到：$(Mask $v)"; return $v }
        if ($prompt -match '跳過') { return '' }
        Warn '沒有收到內容，請再貼一次'
    }
}
function Looks-Like-Token($v) { return $v -match '^[\w-]{20,}\.[\w-]{4,}\.[\w-]{20,}$' }

function Read-Id($prompt, $optional = $false) {
    while ($true) {
        $v = (Read-Host "  $prompt").Trim()
        if ($optional -and $v -eq '') { return '' }
        if ($v -match '^\d{15,21}$') { return $v }
        Warn '頻道／使用者 ID 是一串 17～20 位的數字（Discord 開發者模式 → 右鍵 → 複製 ID）'
    }
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Has-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

function Winget-Install($id, $name) {
    if (-not (Has-Winget)) { return $false }
    Info "用 winget 安裝 $name（可能會跳出確認視窗，請按「是」）…"
    & winget install --id $id -e --source winget --accept-package-agreements --accept-source-agreements --silent | Out-Host
    Refresh-Path
    return $true
}

# .env 讀寫：保留原本的註解和順序，只改指定的那一行
function Read-EnvLines($path) {
    # 前面的逗號：避免 PowerShell 把清單拆開回傳，變成不能 Add 的陣列
    $list = New-Object System.Collections.ArrayList
    if (Test-Path $path) { foreach ($l in [IO.File]::ReadAllLines($path)) { [void]$list.Add($l) } }
    return ,$list
}
function Get-EnvValue($lines, $key) {
    foreach ($l in $lines) { if ($l -match "^\s*$key\s*=(.*)$") { return $Matches[1].Trim() } }
    return $null
}
function Set-EnvValue($lines, $key, $value) {
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$key\s*=") { $lines[$i] = "$key=$value"; return }
    }
    [void]$lines.Add("$key=$value")
}

# ───────────── 1. Python ─────────────

Step 1 '檢查 Python'

function Test-Python($exe, $pre) {
    try {
        $out = & $exe @pre -c 'import sys; print(sys.version_info[:2] >= (3, 10))' 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True')
    } catch { return $false }
}

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if (Test-Python 'py' @('-3')) { return @{ Exe = 'py'; Pre = @('-3') } }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    # Windows 內建的 python 是「開微軟商店」的假捷徑，Test-Python 會失敗而跳過
    if ($cmd -and (Test-Python $cmd.Source @())) { return @{ Exe = $cmd.Source; Pre = @() } }
    $cands = @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", 'C:\Program Files\Python3*\python.exe' -ErrorAction SilentlyContinue |
               Sort-Object FullName -Descending)
    foreach ($c in $cands) { if (Test-Python $c.FullName @()) { return @{ Exe = $c.FullName; Pre = @() } } }
    return $null
}

$Py = Find-Python
if (-not $Py) {
    Warn '找不到 Python 3.10 以上'
    if (-not (Winget-Install 'Python.Python.3.12' 'Python 3.12')) {
        Fail '這台電腦沒有 winget，請手動安裝 Python：https://www.python.org/downloads/（安裝時勾選 Add Python to PATH），再重新執行這個安裝程式'
    }
    $Py = Find-Python
    if (-not $Py) { Fail 'Python 安裝後還是找不到，請關掉這個視窗、重新執行 install.bat 一次' }
}
$ver = & $Py.Exe @($Py.Pre) --version
Ok "$ver"

# ───────────── 2. 下載程式 ─────────────

Step 2 '下載機器人程式'

$here = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
if (Test-Path (Join-Path $here 'bot.py')) {
    $Root = $here
    Info "使用這個資料夾：$Root"
    if ((Test-Path (Join-Path $Root '.git')) -and (Get-Command git -ErrorAction SilentlyContinue)) {
        if (Ask-YesNo '要更新成 GitHub 上的最新版嗎？' $true) {
            Push-Location $Root
            & git pull --ff-only
            if ($LASTEXITCODE -ne 0) { Warn '更新失敗（可能這台電腦上改過程式），先用現在的版本繼續' }
            Pop-Location
        }
    }
} else {
    $Root = Join-Path $env:USERPROFILE 'Blender-DC-AI-Bot'
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Warn '找不到 Git'
        [void](Winget-Install 'Git.Git' 'Git')
        if (-not (Get-Command git -ErrorAction SilentlyContinue) -and (Test-Path 'C:\Program Files\Git\cmd\git.exe')) {
            $env:Path += ';C:\Program Files\Git\cmd'
        }
        $git = Get-Command git -ErrorAction SilentlyContinue
    }
    if (Test-Path (Join-Path $Root 'bot.py')) {
        Info "程式已經在 $Root"
        if ($git -and (Test-Path (Join-Path $Root '.git'))) {
            Push-Location $Root; & git pull --ff-only; Pop-Location
        }
    } elseif ($git) {
        Info "下載到 $Root …"
        & git clone $RepoUrl $Root
        if ($LASTEXITCODE -ne 0) { Fail '下載程式失敗，請確認網路連線' }
    } else {
        Warn '沒有 Git，改用壓縮檔下載（之後更新程式要重新執行這個安裝程式）'
        $zip = Join-Path $env:TEMP 'Blender-DC-AI-Bot.zip'
        $tmp = Join-Path $env:TEMP 'Blender-DC-AI-Bot-unzip'
        Invoke-WebRequest $ZipUrl -OutFile $zip -UseBasicParsing
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        Expand-Archive $zip $tmp
        New-Item -ItemType Directory -Force $Root | Out-Null
        Copy-Item (Join-Path $tmp 'Blender-DC-AI-Bot-main\*') $Root -Recurse -Force
        Remove-Item $zip, $tmp -Recurse -Force
    }
}
Set-Location $Root
Ok "程式位置：$Root"

# ───────────── 3. Python 套件 ─────────────

Step 3 '安裝 Python 套件（第一次要一兩分鐘）'

$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
    & $Py.Exe @($Py.Pre) -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { Fail '建立 Python 虛擬環境失敗' }
}
& $VenvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
& $VenvPy -m pip install -r (Join-Path $Root 'requirements.txt') --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail '安裝套件失敗，請確認網路連線後重新執行' }
Ok '套件安裝完成'

# ───────────── 4. Ollama ─────────────

Step 4 '檢查 Ollama'

function Find-Ollama {
    $c = Get-Command ollama -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe", 'C:\Program Files\Ollama\ollama.exe')) {
        if (Test-Path $p) { return $p }
    }
    return $null
}
function Ollama-Up {
    try { Invoke-RestMethod "$OllamaApi/api/tags" -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}
function Start-Ollama {
    $app = Join-Path (Split-Path $Ollama) 'ollama app.exe'
    if (Test-Path $app) { Start-Process $app } else { Start-Process $Ollama -ArgumentList 'serve' -WindowStyle Hidden }
    for ($i = 0; $i -lt 30; $i++) { if (Ollama-Up) { return $true }; Start-Sleep 1 }
    return $false
}

$Ollama = Find-Ollama
if (-not $Ollama) { Fail '找不到 Ollama。請先安裝 https://ollama.com/download ，再重新執行這個安裝程式' }

# 讓模型一直留在顯卡（預設閒置 5 分鐘就卸載，大模型重新載入很慢）
$keep = [Environment]::GetEnvironmentVariable('OLLAMA_KEEP_ALIVE', 'User')
$needRestart = $false
if ($keep -ne '-1') {
    [Environment]::SetEnvironmentVariable('OLLAMA_KEEP_ALIVE', '-1', 'User')
    $env:OLLAMA_KEEP_ALIVE = '-1'
    Info '已設定 OLLAMA_KEEP_ALIVE=-1（模型常駐顯卡）'
    $needRestart = $true
}
if ($needRestart -and (Ollama-Up)) {
    if (Ask-YesNo 'Ollama 要重新啟動才會套用這個設定，現在重啟嗎？' $true) {
        Get-Process 'ollama app', 'ollama' -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep 2
    } else {
        Warn '先不重啟；下次重開電腦或重開 Ollama 後才會生效'
    }
}
if (-not (Ollama-Up)) {
    Info '啟動 Ollama …'
    if (-not (Start-Ollama)) { Fail 'Ollama 沒有回應。請從開始選單打開 Ollama，再重新執行這個安裝程式' }
}
Ok "Ollama 執行中（$Ollama）"

# ───────────── 5. 本地模型 ─────────────

Step 5 '挑選並下載本地模型'

$vramGB = 0
$gpuName = ''
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if (-not $smi -and (Test-Path 'C:\Windows\System32\nvidia-smi.exe')) { $smi = Get-Item 'C:\Windows\System32\nvidia-smi.exe' }
if ($smi) {
    try {
        $rows = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null
        foreach ($r in @($rows)) {
            $parts = "$r".Split(',')
            $gb = [math]::Round([double]$parts[1].Trim() / 1024, 1)
            if ($gb -gt $vramGB) { $vramGB = $gb; $gpuName = $parts[0].Trim() }
        }
    } catch {}
}
if ($vramGB -gt 0) {
    Ok "顯卡：$gpuName（$vramGB GB）"
} else {
    Warn '偵測不到 NVIDIA 顯卡（或沒有驅動程式），本地模型會用 CPU 跑，非常慢'
}

$start = 0
for ($i = 0; $i -lt $ModelTiers.Count; $i++) {
    if ($vramGB -ge $ModelTiers[$i].MinGB) { $start = $i; break }
}
$tier = $ModelTiers[$start]

function Installed-Models {
    try { return @((Invoke-RestMethod "$OllamaApi/api/tags").models | ForEach-Object { $_.name }) } catch { return @() }
}
function Same-Model($a, $b) { return ($a -eq $b -or $a -eq "$b`:latest" -or "$a`:latest" -eq $b) }

# 電腦上已經有的模型（拿掉 embedding 這類不能聊天的模型）
$installed = @()
try {
    $installed = @((Invoke-RestMethod "$OllamaApi/api/tags").models |
        Where-Object { $_.name -notmatch 'embed|bge|minilm|rerank' } |
        ForEach-Object { [pscustomobject]@{ Name = $_.name; GB = [math]::Round($_.size / 1GB, 1) } } |
        Sort-Object GB -Descending)
} catch {}

function Is-Thinking($name) { return $name -match 'deepseek-r1|gemma|qwq|thinking|magistral' }
# 已安裝的模型 → 設定值：大模型多看幾段資料（0.5），小模型只看最相關的（0.7）
function Tier-For($name, $gb) { return @{ Model = $name; Ctx = $tier.Ctx; Ratio = $(if ($gb -ge 15) { '0.5' } else { '0.7' }) } }

$candidates = @()
$current = Get-EnvValue (Read-EnvLines (Join-Path $Root '.env')) 'LOCAL_MODEL'
$recommendedHere = $installed | Where-Object { Same-Model $_.Name $tier.Model } | Select-Object -First 1

if ($installed.Count -gt 0) {
    Info '這台電腦已經有的模型（選這些不用重新下載）：'
    $fitLimit = if ($vramGB -gt 0) { $vramGB * 0.9 } else { [double]::MaxValue }
    $default = $null
    for ($i = 0; $i -lt $installed.Count; $i++) {
        $m = $installed[$i]
        $notes = @()
        if ($current -and (Same-Model $m.Name $current)) { $notes += '目前 .env 用的' }
        if (Same-Model $m.Name $tier.Model) { $notes += '建議' }
        if ($vramGB -gt 0 -and $m.GB -gt $fitLimit) { $notes += '可能放不進顯卡' }
        if (Is-Thinking $m.Name) { $notes += '不建議：會思考的模型' }
        $tag = if ($notes) { '  ← ' + ($notes -join '、') } else { '' }
        Write-Host ("    {0}. {1}（{2} GB）{3}" -f ($i + 1), $m.Name, $m.GB, $tag)
    }
    # 預設：建議的模型已經有 → 用它；否則用已安裝、放得進顯卡、不會思考的最大模型
    if ($recommendedHere) { $default = $recommendedHere }
    else { $default = $installed | Where-Object { $_.GB -le $fitLimit -and -not (Is-Thinking $_.Name) } | Select-Object -First 1 }
    if ($default) { Info "直接按 Enter → 使用 $($default.Name)（不用下載）" }
    else { Info "已有的模型都不適合，直接按 Enter → 下載建議的 $($tier.Model)" }
    Info "輸入 d → 下載建議的 $($tier.Model)；也可以輸入編號或其他 Ollama 模型名稱"
    $ans = (Read-Host '  請選擇').Trim()
    if ($ans -eq '' -and $default) {
        $candidates += Tier-For $default.Name $default.GB
    } elseif ($ans -match '^\d+$' -and [int]$ans -ge 1 -and [int]$ans -le $installed.Count) {
        $m = $installed[[int]$ans - 1]
        if (Is-Thinking $m.Name) { Warn "$($m.Name) 會先「思考」，可能把思考過程當成答案（不是 qwen3 的話程式關不掉）" }
        $candidates += Tier-For $m.Name $m.GB
    } elseif ($ans -and $ans -ne 'd') {
        $candidates += @{ Model = $ans; Ctx = $tier.Ctx; Ratio = $tier.Ratio }
    }
} else {
    Info "建議模型：$($tier.Model)"
    $ans = (Read-Host '  直接按 Enter 下載建議的模型，或輸入其他 Ollama 模型名稱').Trim()
    if ($ans) { $candidates += @{ Model = $ans; Ctx = $tier.Ctx; Ratio = $tier.Ratio } }
}
# 選的模型不行（下載失敗、放不進顯卡）時，依序往下試建議表
for ($i = $start; $i -lt $ModelTiers.Count; $i++) { $candidates += $ModelTiers[$i] }

$Chosen = $null
foreach ($c in $candidates) {
    $m = $c.Model
    $ps = $null
    $have = Installed-Models
    if ($have -contains $m -or $have -contains "$m`:latest") {
        Info "$m 已經下載過"
    } else {
        Info "下載 $m（大模型要幾分鐘到幾十分鐘，請耐心等候）…"
        & $Ollama pull $m
        if ($LASTEXITCODE -ne 0) { Warn "$m 下載失敗（名稱可能已經改了），改試下一個"; continue }
    }

    # 實際載入一次，確認整個放得進顯卡
    Info "載入 $m 測試中 …"
    try {
        $body = @{ model = $m; prompt = '你好'; stream = $false; options = @{ num_ctx = $c.Ctx; num_predict = 5 } } | ConvertTo-Json -Depth 4
        Invoke-RestMethod "$OllamaApi/api/generate" -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'application/json' -TimeoutSec 900 | Out-Null
        $ps = (Invoke-RestMethod "$OllamaApi/api/ps").models | Where-Object { $_.name -eq $m -or $_.name -eq "$m`:latest" } | Select-Object -First 1
    } catch {
        Warn "$m 載入失敗：$($_.Exception.Message)"
        continue
    }
    if ($ps -and $vramGB -gt 0 -and $ps.size_vram -lt $ps.size) {
        $pct = [math]::Round(100 * $ps.size_vram / $ps.size)
        Warn "$m 只有 $pct% 放得進顯卡，回答會很慢"
        if ($c -ne $candidates[-1] -and (Ask-YesNo '要改用小一級的模型嗎？（建議）' $true)) { continue }
    } elseif ($vramGB -gt 0) {
        Ok "$m 100% 在顯卡上執行"
    }
    $Chosen = $c
    break
}
if (-not $Chosen) { Fail '沒有任何模型下載成功，請到 https://ollama.com/library 確認模型名稱後重新執行' }
Ok "使用模型：$($Chosen.Model)"

# ───────────── 6. 設定檔 .env ─────────────

Step 6 '設定 .env'

$EnvPath = Join-Path $Root '.env'
$ExamplePath = Join-Path $Root '.env.example'

if (-not (Test-Path $EnvPath)) {
    Info '如果是從舊電腦搬過來，可以直接沿用舊的 .env（裡面有 Token 和金鑰，不用重新申請）'
    $old = (Read-Host '  有舊的 .env 就把檔案「拖曳」到這個視窗再按 Enter；沒有就直接按 Enter').Trim().Trim('"').Trim("'")
    if ($old) {
        if (Test-Path $old -PathType Leaf) { Copy-Item $old $EnvPath; Ok '已複製舊的 .env' }
        else { Warn "找不到檔案 $old，改成重新填寫" }
    }
}
$isNew = -not (Test-Path $EnvPath)
$lines = if ($isNew) { Read-EnvLines $ExamplePath } else { Read-EnvLines $EnvPath }

# 舊的 .env 缺少新版的選項 → 從範本補上（用範本的預設值）
if (-not $isNew) {
    $added = @()
    foreach ($l in (Read-EnvLines $ExamplePath)) {
        if ($l -match '^\s*([A-Z_]+)\s*=(.*)$' -and $null -eq (Get-EnvValue $lines $Matches[1])) {
            [void]$lines.Add($l); $added += $Matches[1]
        }
    }
    if ($added) { Info ('補上新版選項：' + ($added -join '、')) }
}

function Need($key) { $v = Get-EnvValue $lines $key; return (-not $v) }

if (Need 'DISCORD_TOKEN') {
    Info 'Discord Token：Discord Developer Portal → 你的應用程式 → Bot → Reset Token → Copy'
    Set-EnvValue $lines 'DISCORD_TOKEN' (Read-Secret 'Discord Token')
}
if (Need 'GEMINI_API_KEY') {
    Info 'Gemini 金鑰：https://aistudio.google.com/apikey → Create API key'
    Set-EnvValue $lines 'GEMINI_API_KEY' (Read-Secret 'Gemini API 金鑰')
}
if (Need 'ASK_CHANNEL_ID') {
    Info 'Discord「使用者設定 → 進階 → 開發者模式」打開後，對頻道按右鍵 → 複製頻道 ID'
    Set-EnvValue $lines 'ASK_CHANNEL_ID' (Read-Id '學生提問頻道的 ID')
}
if ($isNew) {
    Info '老師審核頻道：AI 從網路整理的新筆記會先貼到這裡，老師按「勾勾」反應才加進知識庫'
    $rv = Read-Id '審核頻道的 ID（不需要就直接按 Enter）' $true
    Set-EnvValue $lines 'REVIEW_CHANNEL_ID' $rv
    if ($rv) {
        $who = Read-Id '誰可以審核：老師的使用者 ID（對頭像右鍵 → 複製使用者 ID；看得到審核頻道的人都能審就直接按 Enter）' $true
        Set-EnvValue $lines 'REVIEWER_IDS' $who
    }
}

Set-EnvValue $lines 'LOCAL_MODEL' $Chosen.Model
Set-EnvValue $lines 'LOCAL_CTX' $Chosen.Ctx
Set-EnvValue $lines 'LOCAL_KEEP_RATIO' $Chosen.Ratio
Set-EnvValue $lines 'USE_LOCAL' '1'
Set-EnvValue $lines 'LOCAL_JUDGE' '1'

# Blender（作業健檢）
function Find-Blender {
    $p = Get-EnvValue $lines 'BLENDER_PATH'
    if ($p) { $p = $p.Trim('"'); if (Test-Path $p) { return $p } }
    $c = Get-Command blender -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $cands = @(Get-ChildItem 'C:\Program Files\Blender Foundation\Blender*\blender.exe' -ErrorAction SilentlyContinue)
    if ($cands) {
        $ver = { try { [version](($_.Directory.Name -replace '[^\d.]', '') + '.0') } catch { [version]'0.0' } }
        return ($cands | Sort-Object $ver -Descending | Select-Object -First 1).FullName
    }
    return $null
}
$blender = Find-Blender
if (-not $blender) {
    Warn '找不到 Blender（作業健檢功能要用）'
    $bp = (Read-Host '  把 blender.exe 拖曳到這個視窗再按 Enter；不使用作業健檢就直接按 Enter').Trim().Trim('"')
    if ($bp -and (Test-Path $bp)) { Set-EnvValue $lines 'BLENDER_PATH' $bp; $blender = $bp }
}
if ($blender) {
    Set-EnvValue $lines 'BLEND_CHECK' '1'
    if ($blender -notlike 'C:\Program Files\Blender Foundation\*') { Set-EnvValue $lines 'BLENDER_PATH' $blender }
    Ok "作業健檢使用：$blender"
} else {
    Set-EnvValue $lines 'BLEND_CHECK' '0'
    Info '已關閉作業健檢（之後裝了 Blender 再重新執行安裝程式即可）'
}

[IO.File]::WriteAllLines($EnvPath, [string[]]$lines, $Utf8NoBom)
Ok '已儲存 .env'

# ───────────── 7. 檢查 Token、金鑰、頻道 ─────────────

Step 7 '檢查 Discord 與 Gemini 設定'

# Discord 回傳的 JSON 沒標編碼，Windows PowerShell 會把中文頻道名稱解成亂碼 → 自己用 UTF-8 解
function Discord-Get($path) {
    $r = Invoke-WebRequest "https://discord.com/api/v10$path" -Headers $headers -UseBasicParsing `
        -UserAgent 'DiscordBot (https://github.com/YAOAOAO7121/Blender-DC-AI-Bot, 1.0)'
    return [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()) | ConvertFrom-Json
}
function Save-Env { [IO.File]::WriteAllLines($EnvPath, [string[]]$lines, $Utf8NoBom) }
$problems = 0

# Token：無效就當場重新輸入（最多 3 次），不用自己開 .env 改
$me = $null
for ($try = 1; $try -le 4; $try++) {
    $token = Clean-Secret (Get-EnvValue $lines 'DISCORD_TOKEN')
    if ($token -ne (Get-EnvValue $lines 'DISCORD_TOKEN')) { Set-EnvValue $lines 'DISCORD_TOKEN' $token; Save-Env }
    $headers = @{ Authorization = "Bot $token" }
    try { $me = Discord-Get '/users/@me'; break } catch {
        $code = try { [int]$_.Exception.Response.StatusCode } catch { 0 }
        if ($code -ne 401) { Warn "連不上 Discord（$($_.Exception.Message)），先跳過檢查"; break }
    }
    Warn "Discord 不接受這個 Token：$(Mask $token)"
    if (-not (Looks-Like-Token $token)) { Warn '  格式也不對：Token 應該是用兩個「.」分成三段的一長串英數字（約 70 字）' }
    Info '  常見原因：① 貼到的是 Application ID 或 Client Secret，不是 Bot Token'
    Info '            ② 之後又按過 Reset Token（舊的會立刻失效，其他電腦上的 .env 也要一起換新）'
    Info '  重新取得：Discord Developer Portal → 你的應用程式 → 左邊「Bot」→ Reset Token → Copy'
    if ($try -eq 4) { break }
    $new = Read-Secret '重新貼上 Discord Token（直接按 Enter 跳過）'
    Set-EnvValue $lines 'DISCORD_TOKEN' $new; Save-Env
}
if ($me) { try {
    Ok "Discord 機器人：$($me.username)"
    $app = Discord-Get '/applications/@me'
    $flags = [int64]$app.flags
    if (-not (($flags -band (1 -shl 18)) -or ($flags -band (1 -shl 19)))) {
        Warn '還沒開啟「Message Content Intent」，機器人會看不到學生打的字！'
        Warn "  請到 https://discord.com/developers/applications/$($app.id)/bot 打開 Message Content Intent 並儲存"
        $problems++
    } else { Ok 'Message Content Intent 已開啟' }
    $invite = "https://discord.com/oauth2/authorize?client_id=$($app.id)&scope=bot+applications.commands&permissions=309237746752"
    foreach ($k in @('ASK_CHANNEL_ID', 'REVIEW_CHANNEL_ID')) {
        $id = Get-EnvValue $lines $k
        if (-not $id) { continue }
        $label = if ($k -eq 'ASK_CHANNEL_ID') { '提問頻道' } else { '審核頻道' }
        try {
            $ch = Discord-Get "/channels/$id"
            Ok "$label：#$($ch.name)"
        } catch {
            Warn "$label（$id）機器人看不到：ID 錯了、機器人還沒加入伺服器，或是私人頻道沒給機器人權限"
            $problems++
        }
    }
    if ($problems) { Info "邀請機器人加入伺服器（權限已設定好）：$invite" }
} catch {
    Warn "檢查 Discord 設定時出錯：$($_.Exception.Message)"
    $problems++
} } else {
    Warn 'Discord Token 還是無效，機器人無法登入。拿到正確的 Token 後再執行一次 install.bat'
    $problems++
}

$gkey = Get-EnvValue $lines 'GEMINI_API_KEY'
$gmodel = Get-EnvValue $lines 'MODEL'
try {
    $res = Invoke-RestMethod "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000&key=$gkey"
    Ok 'Gemini 金鑰可以使用'
    if ($gmodel -and -not ($res.models | Where-Object { $_.name -eq "models/$gmodel" })) {
        $flash = @($res.models | Where-Object { $_.name -match 'gemini-[\d.]+-flash$' } | ForEach-Object { $_.name -replace '^models/', '' } | Sort-Object -Descending)
        Warn "Gemini 模型「$gmodel」不存在"
        if ($flash) {
            Info "可以用的 flash 模型：$($flash -join '、')"
            if (Ask-YesNo "改成 $($flash[0])？" $true) {
                Set-EnvValue $lines 'MODEL' $flash[0]
                [IO.File]::WriteAllLines($EnvPath, [string[]]$lines, $Utf8NoBom)
                Ok "已改成 $($flash[0])"
            } else { $problems++ }
        } else { $problems++ }
    }
} catch {
    Warn 'Gemini 金鑰無效。請打開 .env 修正 GEMINI_API_KEY 後重新執行'
    $problems++
}

# ───────────── 8. 啟動捷徑 ─────────────

Step 8 '建立啟動／停止按鈕'

$StartBat = Join-Path $Root '啟動機器人.bat'
$batLines = @(
    '@echo off',
    'cd /d "%~dp0"',
    'rem Already running? Two copies would answer every question twice.',
    'tasklist /v /fo csv /fi "imagename eq cmd.exe" | find /i "Blender AI Bot" >nul && (',
    '  echo The bot is already running. Use the stop button first if you want to restart it.',
    '  timeout /t 5',
    '  exit /b 0',
    ')',
    'set PYTHONUTF8=1',
    'title Blender AI Bot',
    ':loop',
    '".venv\Scripts\python.exe" bot.py',
    'if errorlevel 3 if not errorlevel 4 (',
    '  echo.',
    '  echo Setup problem - see the message above. Fix it, then run this file again.',
    '  pause',
    '  exit /b 3',
    ')',
    'echo.',
    'echo Bot stopped. Restarting in 10 seconds... (close this window to stop the bot)',
    'timeout /t 10',
    'goto loop'
)
[IO.File]::WriteAllText($StartBat, ($batLines -join "`r`n") + "`r`n", [Text.Encoding]::ASCII)
Ok "已建立：$StartBat"

# 停止：關掉啟動視窗（連自動重啟一起停），再收掉其他還在跑的 bot.py（例如舊的開關按鈕啟動的）
$StopBat = Join-Path $Root '停止機器人.bat'
$stopLines = @(
    '@echo off',
    'taskkill /fi "windowtitle eq Blender AI Bot*" /t /f >nul 2>&1',
    'rem No double quotes inside the PowerShell command: cmd would treat the | after them as its own pipe',
    'powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq ''python.exe'' -and $_.CommandLine -match ''\bbot\.py.?\s*$'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"',
    'echo Bot stopped.',
    'timeout /t 3 >nul'
)
[IO.File]::WriteAllText($StopBat, ($stopLines -join "`r`n") + "`r`n", [Text.Encoding]::ASCII)
Ok "已建立：$StopBat"

function Make-Shortcut($path, $target, $icon) {
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut($path)
    $s.TargetPath = $target
    $s.WorkingDirectory = $Root
    if ($icon -and (Test-Path $icon)) { $s.IconLocation = "$icon,0" }
    $s.Save()
}
$StartIcon = Join-Path $Root 'assets\啟動.ico'
$StopIcon = Join-Path $Root 'assets\停止.ico'

# 桌面按鈕（小樽設計的圖示）
$desktop = [Environment]::GetFolderPath('Desktop')
$buttons = @(
    @{ Name = '使用小樽影分身之術'; Target = $StartBat; Icon = $StartIcon },
    @{ Name = '解除小樽影分身'; Target = $StopBat; Icon = $StopIcon }
)
$existing = @($buttons | Where-Object { Test-Path (Join-Path $desktop "$($_.Name).lnk") })
$makeButtons = $true
if ($existing) {
    Info "桌面已經有：$(($existing | ForEach-Object { $_.Name }) -join '、')"
    Info '新版的「解除」會連自動重啟一起停掉（舊的按鈕只關 python 的話，機器人 10 秒後會自己重開）'
    $makeButtons = Ask-YesNo '要換成新版的按鈕嗎？（圖示一樣）' $true
} elseif (-not (Ask-YesNo '要在桌面建立「使用小樽影分身之術」「解除小樽影分身」按鈕嗎？' $true)) {
    $makeButtons = $false
}
if ($makeButtons) {
    foreach ($b in $buttons) { Make-Shortcut (Join-Path $desktop "$($b.Name).lnk") $b.Target $b.Icon }
    Ok '桌面按鈕已建立：使用小樽影分身之術（啟動）、解除小樽影分身（停止）'
}

$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup 'Blender AI 教學助理.lnk'
if (Test-Path $lnk) {
    Ok '已設定開機自動啟動'
} elseif (Ask-YesNo '要讓電腦開機後自動啟動機器人嗎？' $true) {
    Make-Shortcut $lnk $StartBat $StartIcon
    Ok '已加入開機自動啟動'
}
if (Ask-YesNo '要把電腦設成插電時不睡眠嗎？（睡眠 = 機器人下線）' $true) {
    try { & powercfg /change standby-timeout-ac 0 | Out-Null; $pcOk = ($LASTEXITCODE -eq 0) } catch { $pcOk = $false }
    if ($pcOk) { Ok '已設定插電時不睡眠' } else { Warn '設定失敗，請到「設定 → 系統 → 電源」手動把睡眠改成「永不」' }
}

# ───────────── 完成 ─────────────

Write-Host ''
Write-Host '========================================' -ForegroundColor Cyan
if ($problems) {
    Write-Host "  安裝完成，但有 $problems 個問題要處理（看上面黃色的 [注意]）" -ForegroundColor Yellow
    Write-Host '  修正後可以再執行一次 install.bat，做好的步驟會自動跳過'
} else {
    Write-Host '  安裝完成！' -ForegroundColor Green
}
Write-Host '  之後用桌面的「使用小樽影分身之術」啟動、「解除小樽影分身」停止'
Write-Host "  （沒有桌面按鈕的話：資料夾裡的 啟動機器人.bat／停止機器人.bat）"
Write-Host '  [注意] 同一個機器人只能在一台電腦上線，舊電腦上的機器人記得關掉' -ForegroundColor Yellow
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''
if (-not $problems -and (Ask-YesNo '現在就啟動機器人嗎？' $true)) {
    Start-Process $StartBat -WorkingDirectory $Root
}
Read-Host '按 Enter 關閉這個視窗'
