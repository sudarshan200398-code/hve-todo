// Azure App Service (Linux, Python 3.12) for the HVE agentic to-do app.
// Deploy with deploy.ps1, or: az deployment group create -g <rg> -f infra/main.bicep -p appName=<name>

@description('Globally unique app name. The site will be https://<appName>.azurewebsites.net')
param appName string

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('App Service plan size. F1 is free; B1 is the cheapest paid tier and never sleeps.')
@allowed([
  'F1'
  'B1'
])
param sku string = 'F1'

@description('Base URL of the OpenAI-compatible LLM provider (Groq by default).')
param openAiBaseUrl string = 'https://api.groq.com/openai/v1'

@description('LLM model name.')
param openAiModel string = 'openai/gpt-oss-20b'

@secure()
@description('LLM API key. Leave empty to run with the rule-based fallback only.')
param openAiApiKey string = ''

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${appName}-plan'
  location: location
  kind: 'linux'
  sku: {
    name: sku
  }
  properties: {
    reserved: true // required for Linux plans
  }
}

resource site 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  kind: 'app,linux'
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: 'python -m uvicorn main:app --host 0.0.0.0 --port 8000'
      alwaysOn: sku != 'F1' // Always On is not available on the free tier
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true' // Azure runs pip install -r requirements.txt during deployment
        }
        {
          name: 'WEBSITES_PORT'
          value: '8000'
        }
        {
          name: 'TODO_DB_PATH'
          value: '/home/data/tasks.sqlite3' // /home is persistent storage on App Service
        }
        {
          name: 'OPENAI_BASE_URL'
          value: openAiBaseUrl
        }
        {
          name: 'OPENAI_MODEL'
          value: openAiModel
        }
        {
          name: 'OPENAI_API_KEY'
          value: openAiApiKey
        }
      ]
    }
  }
}

output url string = 'https://${site.properties.defaultHostName}'
