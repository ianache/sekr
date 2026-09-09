[CmdletBinding()]
param(
    [string]$Exe,
    [string]$Dataset,
    [string]$Oracle,
    [string]$Expected,
    [Parameter(Mandatory)]
    [string]$OutputDir,
    [switch]$SkipExecution
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Join-Path $PSScriptRoot "..\.."
if ([string]::IsNullOrWhiteSpace($Exe)) {
    $Exe = Join-Path $repositoryRoot "build-standalone-probe-20260908\dist\sekr.exe"
}
if ([string]::IsNullOrWhiteSpace($Dataset)) {
    $Dataset = Join-Path $repositoryRoot "data\coder_activation.json"
}
if ([string]::IsNullOrWhiteSpace($Oracle)) {
    $Oracle = Join-Path $repositoryRoot "data\oracle\coder_activation.json"
}
if ([string]::IsNullOrWhiteSpace($Expected)) {
    $Expected = Join-Path $PSScriptRoot "expected-results.json"
}

function Resolve-InputFile([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Name file does not exist: $Path"
    }
    return (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
}

function ConvertTo-WindowsCommandLineArgument([string]$Value) {
    if ($Value.Length -eq 0) {
        return '""'
    }
    if ($Value -notmatch '[\s"]') {
        return $Value
    }

    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\\"')
    $escaped = [regex]::Replace($escaped, '(\\*)$', '$1$1')
    return '"' + $escaped + '"'
}

function Invoke-Sekr([string]$Executable, [string[]]$Arguments, [string]$CapturePath) {
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Executable
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.Arguments = (@($Arguments | ForEach-Object {
        ConvertTo-WindowsCommandLineArgument ([string]$_)
    }) -join ' ')

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

function Test-ProvenanceRecord([object]$Record, [string[]]$Warnings) {
    if (($null -eq $Record) -or
        ($Record.PSObject.Properties.Match("evidence").Count -ne 1) -or
        ($Record.PSObject.Properties.Match("confidence").Count -ne 1)) {
        return $false
    }

    $confidence = [string]$Record.confidence
    if ($confidence -notin @("VERIFIED", "APPROVED", "INFERRED", "STALE", "CONFLICTED", "UNKNOWN")) {
        return $false
    }

    if (@($Record.evidence).Count -eq 0) {
        return (($confidence -notin @("VERIFIED", "APPROVED")) -and ($Warnings -contains "missing_evidence"))
    }
    return $true
}

function Test-CompileProvenance([object]$Compilation) {
    $items = @($Compilation.items)
    $warnings = @($Compilation.warnings)
    if ($items.Count -eq 0) {
        return $false
    }

    foreach ($item in $items) {
        if (-not (Test-ProvenanceRecord $item $warnings) -or
            ($item.PSObject.Properties.Match("facts").Count -ne 1)) {
            return $false
        }
        foreach ($fact in @($item.facts)) {
            if (-not (Test-ProvenanceRecord $fact $warnings)) {
                return $false
            }
        }
    }
    return $true
}

function Test-CompilerOutputConfidentiality([string]$CompilerOutput, [string[]]$OracleIds) {
    foreach ($fieldName in @("expected_artifact_ids", "critical_artifact_ids")) {
        if ($CompilerOutput.IndexOf($fieldName, [System.StringComparison]::Ordinal) -ge 0) {
            return $false
        }
    }

    try {
        $compilerPayload = $CompilerOutput | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        return $false
    }

    $selectedIds = @($compilerPayload.items | ForEach-Object { [string]$_.id })
    foreach ($oracleId in $OracleIds) {
        if ([string]::IsNullOrEmpty($oracleId) -or $selectedIds -contains $oracleId) {
            continue
        }
        if ($CompilerOutput.IndexOf($oracleId, [System.StringComparison]::Ordinal) -ge 0) {
            return $false
        }
    }
    return $true
}

function Test-OracleDisclosureFreeOutput([string]$Output, [string[]]$OracleIds) {
    foreach ($fieldName in @("expected_artifact_ids", "critical_artifact_ids")) {
        if ($Output.IndexOf($fieldName, [System.StringComparison]::Ordinal) -ge 0) {
            return $false
        }
    }
    foreach ($oracleId in $OracleIds) {
        if (-not [string]::IsNullOrEmpty($oracleId) -and
            $Output.IndexOf($oracleId, [System.StringComparison]::Ordinal) -ge 0) {
            return $false
        }
    }
    return $true
}

if ($SkipExecution) {
    return
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
$compilePath = Join-Path $outputPath "context-compile.json"
$evaluationPath = Join-Path $outputPath "evaluation.json"
$environmentPath = Join-Path $outputPath "environment.json"
$reportPath = Join-Path $outputPath "EXPERIMENT_REPORT.md"

$loadArguments = @("dataset", "load", "--db", $databasePath, "--source", $datasetPath)
$validateArguments = @("dataset", "validate", "--db", $databasePath)
$compileArguments = @("context", "compile", "--db", $databasePath, "--task", "activate coder values", "--budget", "6")
$evaluationArguments = @("context", "evaluate", "--db", $databasePath, "--case", "coder-activation", "--budget", "6", "--oracle-path", $oraclePath)

$null = Invoke-Sekr $exePath $loadArguments $loadPath
$null = Invoke-Sekr $exePath $validateArguments $validatePath
$compileStdout = Invoke-Sekr $exePath $compileArguments $compilePath
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
    $compilation = $compileStdout | ConvertFrom-Json -ErrorAction Stop
    $evaluation = $evaluationStdout | ConvertFrom-Json -ErrorAction Stop
    $expectedResults = Get-Content -LiteralPath $expectedPath -Raw | ConvertFrom-Json -ErrorAction Stop
    $oracleResults = Get-Content -LiteralPath $oraclePath -Raw | ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw "Could not parse compilation, evaluation, or expected results JSON: $($_.Exception.Message)"
}
$oracleIds = @($oracleResults.expected_artifact_ids) + @($oracleResults.critical_artifact_ids)
$compilerDisclosurePassed = (Test-CompilerOutputConfidentiality $compileStdout $oracleIds) -and
    (Test-CompilerOutputConfidentiality (Get-Content -LiteralPath $compilePath -Raw) $oracleIds)
$evaluationDisclosurePassed = Test-OracleDisclosureFreeOutput $evaluationStdout $oracleIds

$acceptance = @(
    [pscustomobject]@{ Rule = "Compiler precisionAtK is at least baseline"; Passed = ($evaluation.compiler.precisionAtK -ge $evaluation.baseline.precisionAtK) }
    [pscustomobject]@{ Rule = "Compiler criticalRecall equals expected threshold"; Passed = (Test-MetricEqual $evaluation.compiler.criticalRecall $expectedResults.acceptance.compilerCriticalRecall) }
    [pscustomobject]@{ Rule = "Compiler falsePositiveRate is at most baseline"; Passed = ($evaluation.compiler.falsePositiveRate -le $evaluation.baseline.falsePositiveRate) }
    [pscustomobject]@{ Rule = "Compiler result is reproducible"; Passed = ([bool]$evaluation.reproducible -eq [bool]$expectedResults.acceptance.reproducible) }
    [pscustomobject]@{ Rule = "Compiler context is within budget"; Passed = ($evaluation.compiler.contextSize -le $expectedResults.acceptance.maxSelectedItems) }
    [pscustomobject]@{ Rule = "Truncation reports omittedCount and budget_truncated"; Passed = (($compilation.omittedCount -gt 0) -and ($compilation.warnings -contains "budget_truncated")) }
    [pscustomobject]@{ Rule = "Selected artifacts and facts retain valid evidence/confidence provenance"; Passed = (Test-CompileProvenance $compilation) }
    [pscustomobject]@{ Rule = "Compiler and evaluation output do not expose oracle data"; Passed = ($compilerDisclosurePassed -and $evaluationDisclosurePassed) }
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
    '```text'
    "$exePath $($loadArguments -join ' ')"
    "$exePath $($validateArguments -join ' ')"
    "$exePath $($compileArguments -join ' ')"
    "$exePath $($evaluationArguments -join ' ')"
    '```'
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
    "## Compilation checks"
    ""
    "- omittedCount: $($compilation.omittedCount)"
    "- warnings: $($compilation.warnings -join ', ')"
    "- selected items: $(@($compilation.items).Count)"
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
