[CmdletBinding()]
param(
    [string]$Exe = (Join-Path $PSScriptRoot "..\..\build-standalone-probe-20260908\dist\sekr.exe"),
    [string]$Dataset = (Join-Path $PSScriptRoot "..\..\data\coder_activation.json"),
    [string]$Oracle = (Join-Path $PSScriptRoot "..\..\data\oracle\coder_activation.json"),
    [string]$Expected = (Join-Path $PSScriptRoot "expected-results.json"),
    [Parameter(Mandatory)]
    [string]$OutputDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-InputFile([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Name file does not exist: $Path"
    }
    return (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
}

function Invoke-Sekr([string]$Executable, [string[]]$Arguments, [string]$CapturePath) {
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Executable
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $Arguments) {
        [void]$startInfo.ArgumentList.Add($argument)
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    [System.IO.File]::WriteAllText($CapturePath, $stdout, [System.Text.UTF8Encoding]::new($false))

    if ($process.ExitCode -ne 0) {
        throw "SEKR command failed ($($process.ExitCode)): $($Arguments -join ' '); stderr: $stderr"
    }
    return $stdout
}

function Test-MetricEqual([double]$Actual, [double]$ExpectedValue) {
    return [Math]::Abs($Actual - $ExpectedValue) -lt 0.000000000001
}

$exePath = Resolve-InputFile $Exe "Executable"
$datasetPath = Resolve-InputFile $Dataset "Dataset"
$oraclePath = Resolve-InputFile $Oracle "Oracle"
$expectedPath = Resolve-InputFile $Expected "Expected results"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$outputPath = (Resolve-Path -LiteralPath $OutputDir -ErrorAction Stop).Path
$databasePath = [System.IO.Path]::GetFullPath((Join-Path $outputPath "knowledge.sqlite"))
$outputRoot = $outputPath.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $databasePath.StartsWith($outputRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Database path must be contained by OutputDir"
}
if (Test-Path -LiteralPath $databasePath) {
    Remove-Item -LiteralPath $databasePath -Force
}

$loadPath = Join-Path $outputPath "dataset-load.json"
$validatePath = Join-Path $outputPath "dataset-validate.json"
$evaluationPath = Join-Path $outputPath "evaluation.json"
$environmentPath = Join-Path $outputPath "environment.json"
$reportPath = Join-Path $outputPath "EXPERIMENT_REPORT.md"

$loadArguments = @("dataset", "load", "--db", $databasePath, "--source", $datasetPath)
$validateArguments = @("dataset", "validate", "--db", $databasePath)
$evaluationArguments = @("context", "evaluate", "--db", $databasePath, "--case", "coder-activation", "--budget", "6", "--oracle-path", $oraclePath)

$null = Invoke-Sekr $exePath $loadArguments $loadPath
$null = Invoke-Sekr $exePath $validateArguments $validatePath
$evaluationStdout = Invoke-Sekr $exePath $evaluationArguments $evaluationPath

$environment = [ordered]@{
    executionTimestampUtc = [DateTime]::UtcNow.ToString("o")
    powershellVersion = $PSVersionTable.PSVersion.ToString()
    os = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
    executableSha256 = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash
    datasetSha256 = (Get-FileHash -LiteralPath $datasetPath -Algorithm SHA256).Hash
    oracleSha256 = (Get-FileHash -LiteralPath $oraclePath -Algorithm SHA256).Hash
}
[System.IO.File]::WriteAllText(
    $environmentPath,
    ($environment | ConvertTo-Json -Depth 5),
    [System.Text.UTF8Encoding]::new($false)
)

try {
    $evaluation = $evaluationStdout | ConvertFrom-Json -ErrorAction Stop
    $expectedResults = Get-Content -LiteralPath $expectedPath -Raw | ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw "Could not parse evaluation or expected results JSON: $($_.Exception.Message)"
}

$acceptance = @(
    [pscustomobject]@{ Rule = "Compiler precisionAtK is at least baseline"; Passed = ($evaluation.compiler.precisionAtK -ge $evaluation.baseline.precisionAtK) }
    [pscustomobject]@{ Rule = "Compiler criticalRecall equals expected threshold"; Passed = (Test-MetricEqual $evaluation.compiler.criticalRecall $expectedResults.acceptance.compilerCriticalRecall) }
    [pscustomobject]@{ Rule = "Compiler falsePositiveRate is at most baseline"; Passed = ($evaluation.compiler.falsePositiveRate -le $evaluation.baseline.falsePositiveRate) }
    [pscustomobject]@{ Rule = "Compiler result is reproducible"; Passed = ([bool]$evaluation.reproducible -eq [bool]$expectedResults.acceptance.reproducible) }
    [pscustomobject]@{ Rule = "Compiler context is within budget"; Passed = ($evaluation.compiler.contextSize -le $expectedResults.acceptance.maxSelectedItems) }
    [pscustomobject]@{ Rule = "Truncation is represented when candidates exceed budget"; Passed = (($evaluation.compiler.candidateCount -le $expectedResults.budget) -or ($evaluation.compiler.contextSize -lt $evaluation.compiler.candidateCount)) }
    [pscustomobject]@{ Rule = "Evaluation output does not expose oracle IDs"; Passed = (($evaluationStdout -notmatch "expected_artifact_ids") -and ($evaluationStdout -notmatch "critical_artifact_ids")) }
    [pscustomobject]@{ Rule = "Compiler fixture metrics match expected results"; Passed = ((Test-MetricEqual $evaluation.compiler.precisionAtK $expectedResults.expectedFixture.compiler.precisionAtK) -and (Test-MetricEqual $evaluation.compiler.criticalRecall $expectedResults.expectedFixture.compiler.criticalRecall) -and (Test-MetricEqual $evaluation.compiler.falsePositiveRate $expectedResults.expectedFixture.compiler.falsePositiveRate)) }
    [pscustomobject]@{ Rule = "Baseline fixture metrics match expected results"; Passed = ((Test-MetricEqual $evaluation.baseline.precisionAtK $expectedResults.expectedFixture.baseline.precisionAtK) -and (Test-MetricEqual $evaluation.baseline.criticalRecall $expectedResults.expectedFixture.baseline.criticalRecall) -and (Test-MetricEqual $evaluation.baseline.falsePositiveRate $expectedResults.expectedFixture.baseline.falsePositiveRate)) }
)
$allPassed = @($acceptance | Where-Object { -not $_.Passed }).Count -eq 0

$report = @(
    "# SEKR Experiment Report"
    ""
    "## Inputs"
    ""
    "- Executable: ``$exePath``"
    "- Dataset: ``$datasetPath``"
    "- Oracle: ``$oraclePath``"
    "- Expected results: ``$expectedPath``"
    "- Output directory: ``$outputPath``"
    ""
    "## Commands"
    ""
    "```text"
    "$exePath $($loadArguments -join ' ')"
    "$exePath $($validateArguments -join ' ')"
    "$exePath $($evaluationArguments -join ' ')"
    "```"
    ""
    "## Baseline metrics"
    ""
    "- precisionAtK: $($evaluation.baseline.precisionAtK)"
    "- criticalRecall: $($evaluation.baseline.criticalRecall)"
    "- falsePositiveRate: $($evaluation.baseline.falsePositiveRate)"
    ""
    "## Compiler metrics"
    ""
    "- precisionAtK: $($evaluation.compiler.precisionAtK)"
    "- criticalRecall: $($evaluation.compiler.criticalRecall)"
    "- falsePositiveRate: $($evaluation.compiler.falsePositiveRate)"
    "- contextSize: $($evaluation.compiler.contextSize)"
    "- candidateCount: $($evaluation.compiler.candidateCount)"
    ""
    "## Reproducibility"
    ""
    "- Deterministic repeated compiler output: $($evaluation.reproducible)"
    ""
    "## Acceptance results"
    ""
)
foreach ($check in $acceptance) {
    $status = if ($check.Passed) { "PASS" } else { "FAIL" }
    $report += "- ${status}: $($check.Rule)"
}
$report += ""
if ($allPassed) {
    $report += "## Decision"
    $report += ""
    $report += "GO"
}
[System.IO.File]::WriteAllLines($reportPath, $report, [System.Text.UTF8Encoding]::new($false))

if (-not $allPassed) {
    exit 1
}
