# Atualiza o servidor Mangalate no Windows sem depender do "bake" do Docker Compose.
# Uso, dentro da pasta server:   powershell -ExecutionPolicy Bypass -File .\atualizar.ps1
# Para placa NVIDIA:            powershell -ExecutionPolicy Bypass -File .\atualizar.ps1 -Perfil gpu
# Suas chaves (secrets\), configuração (.env) e modelos baixados não são apagados.
param(
    [ValidateSet("cpu", "gpu")]
    [string]$Perfil = "cpu",
    [string]$Branch = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Passo($texto) { Write-Host "`n== $texto" -ForegroundColor Cyan }
function Falhou($texto) { Write-Host "`nERRO: $texto" -ForegroundColor Red; exit 1 }

Passo "Baixando a versão nova do código"
if ($Branch -eq "") { $Branch = (git rev-parse --abbrev-ref HEAD).Trim() }
git pull origin $Branch
if ($LASTEXITCODE -ne 0) { Falhou "git pull não terminou. Copie a mensagem acima e mande para o suporte." }
$versao = (git log --oneline -1).Trim()
Write-Host "Versão: $versao"

Passo "Construindo as imagens (pode levar alguns minutos)"
$alvo = if ($Perfil -eq "gpu") { "gpu" } else { "cpu" }
docker build -f Dockerfile.worker --target $alvo -t "mangalate-translator-${alvo}:local" .
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tentando de novo com o construtor clássico do Docker..." -ForegroundColor Yellow
    $env:DOCKER_BUILDKIT = "0"
    docker build -f Dockerfile.worker --target $alvo -t "mangalate-translator-${alvo}:local" .
    if ($LASTEXITCODE -ne 0) { Falhou "A imagem do tradutor não foi construída. Confira se o Docker Desktop está aberto e se há espaço em disco." }
}
docker build -f Dockerfile.gateway -t mangalate-gateway:local .
if ($LASTEXITCODE -ne 0) { Falhou "A imagem do gateway não foi construída." }

Passo "Reiniciando o servidor com as imagens novas"
docker compose --profile $Perfil up -d --no-build --force-recreate
if ($LASTEXITCODE -ne 0) { Falhou "O servidor não reiniciou. Rode: docker compose --profile $Perfil logs --tail 60" }

Passo "Conferindo a versão dentro do servidor"
Start-Sleep -Seconds 5
$servico = "translator-$alvo"
$ok = docker compose --profile $Perfil exec -T $servico python -c "import pathlib; print('seams' in pathlib.Path('/mangalate/batch.py').read_text())"
if ("$ok".Trim() -ne "True") { Falhou "O servidor ainda está com a versão antiga." }
Write-Host "`nPronto: servidor atualizado ($versao)." -ForegroundColor Green
Write-Host "No celular, limpe o cache em Mais > Tradução (Mangalate) > Ajustes avançados para ver o resultado novo."
