# Como a automação do captcha do MuAwaY foi construída

Este documento explica o raciocínio técnico por trás da solução: o problema, as tentativas que falharam e por que a abordagem final funciona.

## O problema inicial

O `main.py` original usava **Selenium com Chrome**, assumindo que a página `captcha.muaway.net` seria aberta num navegador comum. Essa abordagem tinha dois erros e nunca funcionaria com o fluxo real do jogo.

## Etapa 1 — Analisar a página do captcha

Abrindo `https://captcha.muaway.net` e inspecionando o DOM real, duas descobertas:

**1. Os seletores do script antigo estavam errados.** Ele procurava `g-captcha-response` (ID) e um `#checkbox`, mas a página usa **hCaptcha** — os campos reais são textareas ocultos com `name="h-captcha-response"` e `name="g-recaptcha-response"`, com IDs dinâmicos gerados a cada render. Seletor por ID fixo não funciona; é preciso selecionar pelo atributo `name`.

**2. A descoberta mais importante — o callback do hCaptcha:**

```js
window.chrome.webview.postMessage("hcaptcha=" + response)
```

`window.chrome.webview` é a API de mensagens do **WebView2 do Windows**. Ou seja: a página nunca foi feita para um navegador comum — ela é um componente embutido dentro do executável do jogo. Resolver o captcha num Chrome externo não adiantaria nada, porque o token jamais chegaria ao jogo.

## Etapa 2 — Descobrir quem é o "browser" de verdade

Buscando referências a WebView2/Edge nos arquivos do jogo (`C:\MuAwaY`), no executável real `x64\muaway_v3.exe` encontrei:

- Classe `CNewUIWindowsWebView` e handler `WebMessageReceived` — o jogo incorpora um WebView2 e escuta mensagens com o prefixo `hcaptcha=`;
- Constantes `HCaptchaSiteKeyComputer` / `HCaptchaSiteKeyMobile` e a URL base `webview.muaway.net`.

**Conclusão:** a automação correta não é abrir um navegador — é **se conectar ao WebView2 que o próprio jogo já abriu**.

## Etapa 3 — Como se conectar a um WebView2 já em execução

O WebView2 é baseado em Chromium, então fala o protocolo **CDP (Chrome DevTools Protocol)**. Se o processo filho `msedgewebview2.exe` iniciar com a flag `--remote-debugging-port=9222`, qualquer cliente CDP (Playwright, neste caso) pode se conectar e controlar a página.

### Tentativas que falharam

A forma documentada de passar flags ao WebView2 é a variável de ambiente `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`. Testei dois caminhos:

1. **`Start-Process -Verb RunAs` com a variável definida** — falhou: o shell do Windows não propaga variáveis de ambiente ao lançar aplicativos elevados pelo explorer.

2. **Persistir a variável no registro HKCU e lançar o jogo por um `.bat` elevado** — confirmei com teste que a variável **chegava** ao contexto elevado, mas o `msedgewebview2.exe` filho do jogo **nunca** recebia a flag, e a porta 9222 nunca abria.

### A virada

Consultando a documentação oficial da Microsoft, descobri a causa raiz: **processos WebView2 que rodam elevados ignoram todas as variáveis de ambiente `WEBVIEW2_*` e chaves em HKCU** — eles só honram políticas de grupo em **HKLM**. Era exatamente o nosso caso: o jogo roda como administrador.

## A solução final

Criar a política no registro (arquivo `set_webview_debug.reg`):

```
HKLM\SOFTWARE\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments
  "muaway_v3.exe" = "--remote-debugging-port=9222"
```

O escopo é só para o executável do jogo — não afeta mais nada no sistema. Com isso, ao abrir o jogo, o WebView2 sobe com a porta 9222 aberta.

### O que o `main_2.py` faz

1. Conecta via `connect_over_cdp("http://localhost:9222")` com Playwright;
2. Localiza a aba do `captcha.muaway.net` e extrai o sitekey do parâmetro `?sitekey=` da própria URL;
3. Envia para resolução no anti-captcha (`hCaptchaProxyless`);
4. Injeta o token nos textareas `h-captcha-response`/`g-recaptcha-response` e chama `window.chrome.webview.postMessage("hcaptcha=" + token)` — exatamente a mensagem que o `WebMessageReceived` do jogo espera;
5. O jogo valida o token e fecha a janela do captcha automaticamente.

## Resumo em uma frase

Em vez de simular um usuário num navegador externo, descobrimos que a página do captcha é um componente WebView2 embutido no jogo, abrimos sua porta de depuração via política de registro (única forma que funciona com app elevado) e injetamos o token resolvido pelo canal de mensagens que o próprio jogo escuta.

## Adendo — versão mobile (emulador)

A solução foi estendida para o MuAwaY mobile rodando no BlueStacks. As diferenças em relação ao desktop:

1. **Acesso ao WebView:** o app Android habilita `setWebContentsDebuggingEnabled(true)`, expondo um socket local `chrome_devtools_remote_<pid>` (visível em `/proc/net/unix`). O acesso é feito via ADB: `adb forward tcp:9223 localabstract:chrome_devtools_remote_<pid>`. Como o app cria múltiplos processos WebView e o PID pode mudar, o script varre todos os sockets e refaz o forward periodicamente.

2. **Ponte de retorno diferente:** no Android não existe `window.chrome.webview`. A página do captcha chama `NativeBridge.sendMessage("hcaptcha=" + token)` — uma ponte Java exposta pelo app. A injeção usa essa chamada.

3. **Armadilha encontrada:** no **MSI App Player** a ponte aceita a mensagem, mas o app responde `Captcha token validation failed` para qualquer token válido. Com o **BlueStacks 5 oficial** o mesmo token passa (`Captcha token validation success`). Conclusão: a automação estava correta; o emulador MSI tinha alguma divergência no ambiente de validação. Requisito firme: usar BlueStacks oficial.

Os scripts mobile são `main_mobile.py` (sentinela), `resolver_uma_vez.py` (one-shot) e `debug_mobile.py` (diagnóstico).
