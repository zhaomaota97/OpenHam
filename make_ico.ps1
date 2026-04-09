Add-Type -AssemblyName System.Drawing
$pngPath = "logo.png"
$icoPath = "logo.ico"

$bmp = New-Object System.Drawing.Bitmap($pngPath)

# 为了兼容性和无损，我们生成一个 64x64 的标准未压缩 32位 ICO
$size = 64
$resized = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($resized)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
$g.DrawImage($bmp, 0, 0, $size, $size)
$g.Dispose()
$bmp.Dispose()

$rect = New-Object System.Drawing.Rectangle(0, 0, $size, $size)
$bmpData = $resized.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, $resized.PixelFormat)

$stride = $bmpData.Stride
$ptr = $bmpData.Scan0
$bytes = $stride * $size
$pixels = New-Object byte[] $bytes
[System.Runtime.InteropServices.Marshal]::Copy($ptr, $pixels, 0, $bytes)
$resized.UnlockBits($bmpData)
$resized.Dispose()

# 在 BMP 中，图像行是倒序的 (bottom-up)
# 我们需要把 pixels 数组倒序排列（每行作为单位）
$bottomUpPixels = New-Object byte[] $bytes
for ($y = 0; $y -lt $size; $y++) {
    $srcRow = $y * $stride
    $dstRow = ($size - 1 - $y) * $stride
    [Array]::Copy($pixels, $srcRow, $bottomUpPixels, $dstRow, $stride)
}

# 构造完整的标准 32-bit ICO（不再依赖 Windows API 的画质阉割，也不使用 PNG 压缩以防不兼容）
$fs = [System.IO.File]::Create($icoPath)
$bw = New-Object System.IO.BinaryWriter($fs)

# 1. ICONDIR
$bw.Write([UInt16]0) # Reserved
$bw.Write([UInt16]1) # Type=1 (ICO)
$bw.Write([UInt16]1) # Count=1

# 2. ICONDIRENTRY
$bw.Write([Byte]$size) # width
$bw.Write([Byte]$size) # height
$bw.Write([Byte]0)     # colors
$bw.Write([Byte]0)     # reserved
$bw.Write([UInt16]1)   # color planes
$bw.Write([UInt16]32)  # bpp
$andMaskSize = ($size / 8) * $size
$bytesInRes = 40 + $bytes + $andMaskSize
$bw.Write([UInt32]$bytesInRes)
$bw.Write([UInt32]22)  # offset

# 3. BITMAPINFOHEADER
$bw.Write([UInt32]40)      # header size
$bw.Write([UInt32]$size)   # width
$bw.Write([UInt32]($size * 2)) # height (xor + and)
$bw.Write([UInt16]1)       # planes
$bw.Write([UInt16]32)      # bpp
$bw.Write([UInt32]0)       # compression (BI_RGB)
$bw.Write([UInt32]$bytes)  # image size
$bw.Write([UInt32]0)       # x res
$bw.Write([UInt32]0)       # y res
$bw.Write([UInt32]0)       # colors used
$bw.Write([UInt32]0)       # important colors

# 4. XOR Mask (Raw pixels BGRA)
$bw.Write( [byte[]]$bottomUpPixels )

# 5. AND Mask (1bpp monochrome transparency, all 0s for fully driven by alpha channel)
$andMask = New-Object byte[] $andMaskSize
$bw.Write( [byte[]]$andMask )

$bw.Close()
$fs.Close()

Write-Host "Real Uncompressed 32-bit ICO generated!"
