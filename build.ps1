Add-Type -AssemblyName System.Drawing

# 1. 用 Python 无损封装 PNG 为 ICO（保持原图各种透明度与色彩）
& ".\runtime\python.exe" make_ico.py

# 2. Find csc.exe
$csc = (Get-ChildItem "C:\Windows\Microsoft.NET\Framework64" -Recurse -Filter "csc.exe" |
        Sort-Object FullName | Select-Object -Last 1).FullName
if (-not $csc) {
    $csc = (Get-ChildItem "C:\Windows\Microsoft.NET\Framework" -Recurse -Filter "csc.exe" |
            Sort-Object FullName | Select-Object -Last 1).FullName
}
Write-Host "CSC: $csc"

# 3. Compile
Set-Location $PSScriptRoot
& $csc /target:winexe /out:OpenHam.exe /win32icon:logo.ico `
       /reference:System.Windows.Forms.dll `
       /reference:System.Drawing.dll `
       /optimize+ launcher.cs

if ($LASTEXITCODE -eq 0) {
    Write-Host "SUCCESS: OpenHam.exe"
} else {
    Write-Host "FAILED"
    exit 1
}
