# MuAwaY Captcha Solver

Resolve automaticamente o captcha (hCaptcha) do MuAwaY conectando direto no WebView2 do jogo, sem abrir navegador externo.

## Como funciona

1. O jogo (`muaway_v3.exe`) abre a janela de captcha dentro de um WebView2 interno.
2. Uma política de registro (HKLM) liga a depuração remota (`--remote-debugging-port=9222`) só para esse executável.
3. O `main_2.py` conecta nessa porta (CDP), lê o sitekey da própria URL da página, resolve o hCaptcha via anti-captcha e injeta o token, disparando o `window.chrome.webview.postMessage("hcaptcha=...")` que o jogo espera.

## Arquivos

| Arquivo | Função |
|---|---|
| `main.py` | Script principal desktop (usar este) — fica vigiando e resolve quantos captchas aparecerem |
| `set_webview_debug.reg` | Chave de registro que habilita a porta CDP 9222 |
| `SOLUCAO.md` | Explicação técnica de como a solução foi desenvolvida |
| `.env` | Sua chave da API anti-captcha (não comitar) |
| `.gitignore` | Ignora `.env` e `.venv` |

## Setup em uma máquina nova

### 1. Aplicar o registro (Administrador, uma vez só)

Powershell, CMD como administrador ou dois cliques no executavel no explorer
```
reg import set_webview_debug.reg
```

Isso cria `HKLM\SOFTWARE\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments` com o valor `muaway_v3.exe` = `--remote-debugging-port=9222`.

> Por que registro? O jogo roda **elevado** e processos elevados do WebView2 ignoram variáveis de ambiente `WEBVIEW2_*` — apenas políticas HKLM funcionam.

### 2. Criar o ambiente Python

Requisito: Python 3.10+

```
python -m venv .venv
.venv\Scripts\python -m pip install playwright anticaptchaofficial python-dotenv
```

Não é necessário `playwright install` (não baixamos navegador; conectamos no WebView2 que o jogo já abriu).

### 3. Configurar a chave da API

Crie uma conta em [anti-captcha.com](https://anti-captcha.com), adicione créditos e crie o arquivo `.env` na pasta do projeto (modelo em `.env.example`):

```
CAPTCHA_API_KEY=sua_chave_aqui
```

### Fallback 2captcha (opcional)

Se o anti-captcha ficar sem créditos, o script tenta resolver pelo [2captcha](https://2captcha.com) automaticamente. Basta adicionar no `.env`:

```
CAPTCHA_2CAPTCHA_API_KEY=sua_chave_2captcha_aqui
```

O token resolvido pelo 2captcha é injetado no jogo da mesma forma.

## Build do executável (sem repo/Python)

Para gerar um `.exe` standalone (cliente não precisa de Python nem do repositório):

```
.\build-exe.ps1
```

Isso gera `dist/mu-captcha-resolver.exe`. Para distribuir, copie o `.exe` junto com um arquivo `.env` (modelo em `.env.example`) na mesma pasta — o executável lê o `.env` do diretório de onde ele é executado. Uso idêntico: abra o jogo com a janela de captcha e rode o `.exe`.

## Uso diário

1. Abra o jogo e faça login **até a janela do captcha aparecer** (deixe ela aberta).
2. Rode:

```
.venv\Scripts\python main_2.py
```

3. Em ~30–60 segundos o captcha é resolvido e a janela fecha sozinha.

## Solução de problemas

| Problema | Causa provável |
|---|---|
| `Nenhuma pagina do captcha encontrada` | A janela do captcha não está aberta no jogo |
| Timeout ao conectar na porta 9222 | Registro não aplicado, ou jogo aberto **antes** de aplicar o registro (reabra o jogo) |
| `ERROR_ZERO_BALANCE` | Sem créditos na conta anti-captcha |
| `CAPTCHA_API_KEY nao definida` | Falta o arquivo `.env` na pasta |

## Desinstalando

Para remover a configuração do registro (opcional):

```
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments" /v muaway_v3.exe
```

Depois é só apagar a pasta do projeto.
