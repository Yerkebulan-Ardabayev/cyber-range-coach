param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Paths)

# Parses every script with the PowerShell parser and rejects syntax that only
# PowerShell 7 understands: the owner's laptop runs Windows PowerShell 5.1.
# Scripts that users run on Windows must also stay ASCII (5.1 reads BOM-less
# files in the ANSI code page).

$failed = $false
$ps7Only = @(
    [System.Management.Automation.Language.PipelineChainAst],
    [System.Management.Automation.Language.TernaryExpressionAst]
)
foreach ($path in $Paths) {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $path), [ref]$tokens, [ref]$errors)
    foreach ($parseError in $errors) {
        Write-Output "$path`:$($parseError.Extent.StartLineNumber): parse error: $($parseError.Message)"
        $failed = $true
    }
    foreach ($type in $ps7Only) {
        foreach ($node in $ast.FindAll({ param($n) $n -is $type }, $true)) {
            Write-Output "$path`:$($node.Extent.StartLineNumber): PowerShell 7 only: $($type.Name)"
            $failed = $true
        }
    }
    foreach ($node in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.BinaryExpressionAst] -and "$($n.Operator)" -eq "QuestionQuestion" }, $true)) {
        Write-Output "$path`:$($node.Extent.StartLineNumber): PowerShell 7 only: ??"
        $failed = $true
    }
    $bytes = [System.IO.File]::ReadAllBytes((Resolve-Path $path))
    if ($bytes | Where-Object { $_ -gt 127 } | Select-Object -First 1) {
        Write-Output "$path`: non-ASCII bytes"
        $failed = $true
    }
}
if ($failed) { exit 1 }
Write-Output "POWERSHELL CHECK PASSED: $($Paths.Count) files"
