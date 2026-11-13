param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)
python "$PSScriptRoot\agy_hist.py" @Args
