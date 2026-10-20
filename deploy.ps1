<#
  Deploys the HVE to-do app to Azure App Service.

  Needs: Azure CLI (https://aka.ms/installazurecli) and an Azure subscription.
  Run from the hve-todo folder:
      .\deploy.ps1 -AppName hve-todo-sudarshan
  Optional: -Location centralindia -Sku B1 -ResourceGroup my-rg
#>
param(
    [Parameter(Mandatory = $true)][string]$AppName,
    [string]$ResourceGroup = "hve-todo-rg",
    [string]$Location = "centralindia",
    [ValidateSet("F1", "B1")][string]$Sku = "F1"
)
$ErrorActionPreference = "Stop"

Write-Host "1/5 Checking Azure login..."
az account show --output none 2>$null
if ($LASTEXITCODE -ne 0) { az login --output none }

Write-Host "2/5 Creating resource group $ResourceGroup in $Location..."
az group create --name $ResourceGroup --location $Location --output none

$apiKey = Read-Host "Paste your LLM (Groq) API key, or press Enter to skip" -AsSecureString
$apiKeyPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($apiKey))

Write-Host "3/5 Creating App Service plan and web app from infra/main.bicep..."
$url = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file infra/main.bicep `
    --parameters appName=$AppName sku=$Sku openAiApiKey=$apiKeyPlain `
    --query properties.outputs.url.value --output tsv
if ($LASTEXITCODE -ne 0) { throw "Infrastructure deployment failed." }

Write-Host "4/5 Packaging the code (committed files only)..."
git archive --format=zip --output app.zip HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive failed. Commit your changes first." }

Write-Host "5/5 Uploading the code (Azure installs requirements.txt; takes 2-5 minutes)..."
az webapp deploy --resource-group $ResourceGroup --name $AppName --src-path app.zip --type zip --output none
if ($LASTEXITCODE -ne 0) { throw "Code deployment failed." }
Remove-Item app.zip

Write-Host ""
Write-Host "Done. Your app: $url"
Write-Host "Logs: az webapp log tail -g $ResourceGroup -n $AppName"
