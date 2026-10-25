"""Monitora e resolve hCaptcha do MuAwaY usando diretamente a API v2 do 2Captcha."""

import json
import logging
import os
import sys
import time
import traceback
from importlib.metadata import PackageNotFoundError, version
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


NOME_LOGGER = "mu_captcha_resolver_2captcha"
TAMANHO_MAXIMO_LOG = 5 * 1024 * 1024
QUANTIDADE_BACKUPS_LOG = 5


def configurar_logging():
    """Configura logs no console e em arquivo rotativo persistente."""
    logger = logging.getLogger(NOME_LOGGER)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        return logger, getattr(logger, "caminho_arquivo", None)

    console_stream = sys.stdout or sys.stderr
    if console_stream is not None:
        console = logging.StreamHandler(console_stream)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(console)

    if getattr(sys, "frozen", False):
        diretorio_aplicacao = Path(sys.executable).resolve().parent
    else:
        diretorio_aplicacao = Path(__file__).resolve().parent

    candidatos = [diretorio_aplicacao / "logs" / "main_2captcha.log"]
    diretorio_local = os.getenv("LOCALAPPDATA")
    if diretorio_local:
        candidatos.append(
            Path(diretorio_local) / "MuCaptchaResolver" / "logs" / "main_2captcha.log"
        )
    else:
        candidatos.append(
            Path.home() / ".mu-captcha-resolver" / "logs" / "main_2captcha.log"
        )

    erros_criacao = []
    caminho_arquivo = None
    for candidato in candidatos:
        try:
            candidato.parent.mkdir(parents=True, exist_ok=True)
            arquivo = RotatingFileHandler(
                candidato,
                maxBytes=TAMANHO_MAXIMO_LOG,
                backupCount=QUANTIDADE_BACKUPS_LOG,
                encoding="utf-8",
            )
            arquivo.setLevel(logging.DEBUG)
            arquivo.setFormatter(logging.Formatter(
                "%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] "
                "[%(funcName)s:%(lineno)d] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            logger.addHandler(arquivo)
            caminho_arquivo = candidato
            break
        except OSError as erro:
            erros_criacao.append(f"{candidato}: {type(erro).__name__}: {erro}")

    logger.caminho_arquivo = caminho_arquivo
    if caminho_arquivo:
        logger.info("Log persistente em: %s", caminho_arquivo)
        logger.info(
            "Rotação de logs habilitada (máximo de %d MB por arquivo, %d backups).",
            TAMANHO_MAXIMO_LOG // (1024 * 1024),
            QUANTIDADE_BACKUPS_LOG,
        )
    else:
        logger.error(
            "Não foi possível criar arquivo de log; detalhes apenas no console. Erros: %s",
            " | ".join(erros_criacao),
        )

    return logger, caminho_arquivo


LOGGER, CAMINHO_LOG = configurar_logging()


def sanitizar_texto(texto, *segredos):
    """Redige credenciais, sitekey e token antes de gravar mensagens de erro."""
    texto = str(texto)
    for segredo in segredos:
        if segredo:
            texto = texto.replace(str(segredo), "[REDACTED]")
    return texto


def registrar_excecao(mensagem, erro, *segredos, nivel=logging.ERROR):
    """Registra o traceback sem imprimir valores sensíveis ou linhas-fonte."""
    quadros = traceback.extract_tb(erro.__traceback__)
    frames = "".join(
        f'  File "{quadro.filename}", line {quadro.lineno}, in {quadro.name}\n'
        for quadro in quadros
    )
    erro_texto = sanitizar_texto(f"{type(erro).__name__}: {erro}", *segredos)
    LOGGER.log(
        nivel,
        "%s\nTraceback (most recent call last):\n%s%s",
        mensagem,
        frames,
        erro_texto,
    )


def url_sem_parametros(url):
    """Retorna esquema, host e caminho, omitindo query string e sitekey."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "host-desconhecido"
        return f"{parsed.scheme}://{host}{parsed.path}"
    except Exception:
        return "<URL indisponível>"


try:
    from dotenv import load_dotenv
    from playwright.sync_api import sync_playwright

    DOTENV_CARREGADO = load_dotenv()
    LOGGER.info("load_dotenv() retornou: %s", DOTENV_CARREGADO)
except Exception as erro:
    registrar_excecao("Falha ao importar dependências ou carregar .env", erro)
    raise


CDP_URL = "http://localhost:9222"
CAPTCHA_DOMAIN = "captcha.muaway.net"

API_BASE_URL = "https://api.2captcha.com"
TIMEOUT_RESOLUCAO_SEGUNDOS = 300
TIMEOUT_REQUISICAO_SEGUNDOS = 15
INTERVALO_POLL_SEGUNDOS = 5
INTERVALO_LOG_PROGRESSO = max(1, 30 // INTERVALO_POLL_SEGUNDOS)

INTERVALO_SEGUNDOS = 3
INTERVALO_RETRY_INICIAL_SEGUNDOS = 15
INTERVALO_RETRY_MAX_SEGUNDOS = 120

JS_INJETAR_TOKEN = """
(token) => {
    document.querySelectorAll(
        'textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]'
    ).forEach((campo) => {
        campo.value = token;
        campo.innerHTML = token;
        campo.dispatchEvent(new Event('change', { bubbles: true }));
    });
    window.chrome.webview.postMessage("hcaptcha=" + token);
}
"""


def buscar_pagina_captcha(playwright):
    """Retorna navegador e página hCaptcha se estiverem abertos no WebView2."""
    inicio = time.perf_counter()
    try:
        navegador = playwright.chromium.connect_over_cdp(CDP_URL)
    except Exception as erro:
        LOGGER.debug(
            "Conexão CDP indisponível após %.3fs (%s): %s",
            time.perf_counter() - inicio,
            type(erro).__name__,
            sanitizar_texto(erro),
        )
        return None, None

    total_paginas = 0
    for contexto in navegador.contexts:
        for pagina in contexto.pages:
            total_paginas += 1
            url = pagina.url
            LOGGER.debug("Página detectada no WebView2: %s", url_sem_parametros(url))
            if CAPTCHA_DOMAIN in url:
                LOGGER.info(
                    "Página de captcha localizada após %.3fs: %s",
                    time.perf_counter() - inicio,
                    url_sem_parametros(url),
                )
                return navegador, pagina

    LOGGER.debug(
        "CDP conectado após %.3fs; contextos=%d, páginas=%d, captcha não encontrado.",
        time.perf_counter() - inicio,
        len(navegador.contexts),
        total_paginas,
    )
    return navegador, None


def criar_payload_hcaptcha(api_key, url, sitekey):
    """Cria payload REST v2 para hCaptcha proxyless."""
    return {
        "clientKey": api_key,
        "task": {
            "type": "HCaptchaTaskProxyless",
            "websiteURL": url,
            "websiteKey": sitekey,
        },
    }


def _timeout_requisicao(deadline):
    restante = deadline - time.monotonic()
    if restante <= 0:
        raise TimeoutError(
            f"O prazo de resolução de {TIMEOUT_RESOLUCAO_SEGUNDOS} segundos terminou."
        )
    return min(TIMEOUT_REQUISICAO_SEGUNDOS, restante)


def postar_json(metodo, payload, deadline, *segredos):
    """Envia uma requisição JSON à API v2, limitada pelo prazo da tentativa."""
    requisicao = Request(
        f"{API_BASE_URL}/{metodo}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(requisicao, timeout=_timeout_requisicao(deadline)) as resposta:
            conteudo = resposta.read().decode("utf-8")
    except HTTPError as erro_http:
        detalhe = erro_http.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{metodo} retornou HTTP {erro_http.code}: "
            f"{sanitizar_texto(detalhe, *segredos)}"
        ) from None
    except URLError as erro_url:
        raise RuntimeError(
            f"Falha de rede em {metodo}: {sanitizar_texto(erro_url, *segredos)}"
        ) from None

    try:
        dados = json.loads(conteudo)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"{metodo} retornou JSON inválido: "
            f"{sanitizar_texto(conteudo[:500], *segredos)}"
        ) from None
    if not isinstance(dados, dict):
        raise RuntimeError(f"{metodo} retornou JSON em formato inesperado.")
    return dados


def verificar_erro_api(resposta, metodo, *segredos):
    """Converte erros da API v2 em uma mensagem diagnóstica sanitizada."""
    error_id = resposta.get("errorId", 0)
    if error_id not in (0, "0", None):
        codigo = resposta.get("errorCode", "código não informado")
        descricao = sanitizar_texto(
            resposta.get("errorDescription", "sem detalhes"), *segredos
        )
        raise RuntimeError(f"{metodo}: errorId={error_id}, {codigo}: {descricao}")


def extrair_token(resposta):
    """Extrai o token hCaptcha do objeto solution devolvido pela API v2."""
    solucao = resposta.get("solution")
    if not isinstance(solucao, dict):
        raise RuntimeError("A resposta pronta não contém o objeto 'solution'.")
    for campo in ("gRecaptchaResponse", "hCaptchaResponse", "token"):
        token = solucao.get(campo)
        if isinstance(token, str) and token:
            return token
    campos = ", ".join(sorted(str(campo) for campo in solucao)) or "nenhum"
    raise RuntimeError(
        "A resposta pronta não contém um token reconhecido; "
        f"campos recebidos em solution: {campos}."
    )


def resolver_via_2captcha(url, sitekey, api_key):
    """Cria uma tarefa hCaptcha v2 e consulta seu resultado por até cinco minutos."""
    inicio = time.monotonic()
    deadline = inicio + TIMEOUT_RESOLUCAO_SEGUNDOS
    task_id = None
    resposta_create_task_recebida = False
    segredos = (api_key, sitekey)
    LOGGER.info(
        "Iniciando resolução hCaptcha pela API v2 do 2Captcha (%s).",
        url_sem_parametros(url),
    )

    try:
        resposta = postar_json(
            "createTask",
            criar_payload_hcaptcha(api_key, url, sitekey),
            deadline,
            *segredos,
        )
        resposta_create_task_recebida = True
        verificar_erro_api(resposta, "createTask", *segredos)
        task_id = resposta.get("taskId")
        if task_id is None:
            raise RuntimeError("createTask não retornou taskId.")

        LOGGER.info("Tarefa hCaptcha criada no 2Captcha (task_id=%s).", task_id)
        numero_poll = 0
        while True:
            restante = deadline - time.monotonic()
            if restante <= 0:
                raise TimeoutError(
                    f"A tarefa hCaptcha {task_id} não ficou pronta em "
                    f"{TIMEOUT_RESOLUCAO_SEGUNDOS} segundos."
                )

            resultado = postar_json(
                "getTaskResult",
                {"clientKey": api_key, "taskId": task_id},
                deadline,
                *segredos,
            )
            verificar_erro_api(resultado, "getTaskResult", *segredos)
            numero_poll += 1
            status = resultado.get("status")

            LOGGER.debug(
                "Consulta %d da tarefa %s: status=%s.",
                numero_poll,
                task_id,
                status,
            )
            agora = time.monotonic()
            if (
                status != "processing"
                or numero_poll == 1
                or numero_poll % INTERVALO_LOG_PROGRESSO == 0
            ):
                LOGGER.info(
                    "Progresso da tarefa %s: status=%s, consulta=%d, "
                    "decorrido=%.0fs, restante=%.0fs.",
                    task_id,
                    status,
                    numero_poll,
                    agora - inicio,
                    max(0, deadline - agora),
                )

            if status == "ready":
                token = extrair_token(resultado)
                LOGGER.info(
                    "2Captcha resolveu o desafio em %.2fs; tamanho do token=%d "
                    "(valor omitido).",
                    time.monotonic() - inicio,
                    len(token),
                )
                return token
            if status != "processing":
                raise RuntimeError(
                    "getTaskResult retornou status inesperado: "
                    f"{sanitizar_texto(status, *segredos)}"
                )

            restante = deadline - time.monotonic()
            if restante <= 0:
                raise TimeoutError(
                    f"A tarefa hCaptcha {task_id} não ficou pronta em "
                    f"{TIMEOUT_RESOLUCAO_SEGUNDOS} segundos."
                )
            time.sleep(min(INTERVALO_POLL_SEGUNDOS, restante))

    except TimeoutError as erro:
        LOGGER.error("Timeout da API 2Captcha após %.2fs: %s", time.monotonic() - inicio, erro)
        if task_id is not None:
            LOGGER.warning(
                "A tarefa %s pode continuar ativa no 2Captcha; uma nova tentativa "
                "pode criar outra tarefa e gerar nova cobrança.",
                task_id,
            )
        return None
    except Exception as erro:
        registrar_excecao(
            f"Falha na resolução via API v2 após {time.monotonic() - inicio:.2f}s",
            erro,
            *segredos,
        )
        if task_id is not None:
            LOGGER.warning(
                "A tarefa %s pode continuar ativa no 2Captcha; uma nova tentativa "
                "pode criar outra tarefa e gerar nova cobrança.",
                task_id,
            )
        elif not resposta_create_task_recebida:
            LOGGER.warning(
                "Não foi possível confirmar se createTask foi aceito pelo serviço; "
                "uma nova tentativa pode gerar uma tarefa cobrável."
            )
        return None


def resolver_captcha(pagina, api_key):
    """Resolve o hCaptcha da página atual e envia o token ao WebView2."""
    url = pagina.url
    sitekey = parse_qs(urlparse(url).query).get("sitekey", [None])[0]
    if not sitekey:
        LOGGER.error(
            "Captcha detectado, mas a URL não contém o parâmetro sitekey: %s",
            url_sem_parametros(url),
        )
        return False

    LOGGER.info(
        "Captcha detectado; sitekey presente (valor omitido). URL: %s",
        url_sem_parametros(url),
    )
    token = resolver_via_2captcha(url, sitekey, api_key)
    if token is None:
        LOGGER.warning("Nenhum token foi obtido para este desafio.")
        return False

    try:
        pagina.evaluate(JS_INJETAR_TOKEN, token)
    except Exception as erro:
        registrar_excecao(
            "Falha ao injetar/enviar o token ao WebView2",
            erro,
            api_key,
            sitekey,
            token,
        )
        return False

    LOGGER.info("Token injetado no WebView2 e postMessage retornou sem erro.")
    return True


def proximo_intervalo_retry(intervalo_atual):
    """Aumenta o intervalo entre falhas sem interromper o monitor."""
    proximo = min(
        max(INTERVALO_RETRY_INICIAL_SEGUNDOS, intervalo_atual * 2),
        INTERVALO_RETRY_MAX_SEGUNDOS,
    )
    LOGGER.debug("Backoff de retry: intervalo %ds -> %ds.", intervalo_atual, proximo)
    return proximo


def main():
    inicio_sessao = time.perf_counter()
    LOGGER.info("=" * 72)
    LOGGER.info("Iniciando sessão do resolvedor hCaptcha via 2Captcha API v2.")
    LOGGER.info(
        "Ambiente: Python %s, plataforma=%s, executável=%s",
        sys.version.split()[0],
        sys.platform,
        sys.executable,
    )
    LOGGER.info("Diretório de trabalho: %s", os.getcwd())
    LOGGER.info("Arquivo de log: %s", CAMINHO_LOG or "indisponível; apenas console")
    for pacote in ("python-dotenv", "playwright"):
        try:
            versao = version(pacote)
        except PackageNotFoundError:
            versao = "não encontrada nos metadados"
        except Exception as erro:
            versao = f"erro ao consultar versão ({type(erro).__name__})"
        LOGGER.info("Dependência: %s=%s", pacote, versao)
    LOGGER.info("Provedor: API REST v2 do 2Captcha (sem SDK e sem fallback).")

    api_key = os.getenv("CAPTCHA_2CAPTCHA_API_KEY")
    if not api_key:
        LOGGER.critical(
            "CAPTCHA_2CAPTCHA_API_KEY não definida; encerrando antes de iniciar o monitoramento."
        )
        return 1

    LOGGER.info("Configuração carregada: 2Captcha configurado=%s.", bool(api_key))
    LOGGER.info(
        "Monitorando CDP em %s a cada %ds; prazo por tarefa=%ds; "
        "retry inicial=%ds, máximo=%ds.",
        CDP_URL,
        INTERVALO_SEGUNDOS,
        TIMEOUT_RESOLUCAO_SEGUNDOS,
        INTERVALO_RETRY_INICIAL_SEGUNDOS,
        INTERVALO_RETRY_MAX_SEGUNDOS,
    )
    LOGGER.info("Deixe o script rodando enquanto joga. Ctrl+C para sair.")

    resolucoes = 0
    intervalo_atual = INTERVALO_SEGUNDOS
    numero_ciclo = 0
    estado_anterior = None

    try:
        with sync_playwright() as playwright:
            LOGGER.info("Playwright iniciado; começando ciclos de monitoramento.")
            while True:
                numero_ciclo += 1
                inicio_ciclo = time.perf_counter()
                resultado_ciclo = "não concluído"
                try:
                    LOGGER.debug(
                        "Ciclo #%d iniciado; intervalo atual=%ds.",
                        numero_ciclo,
                        intervalo_atual,
                    )
                    navegador, pagina = buscar_pagina_captcha(playwright)

                    if navegador is None:
                        estado = "cdp_indisponível"
                        resultado_ciclo = "CDP indisponível"
                        intervalo_atual = INTERVALO_SEGUNDOS
                    elif pagina is None:
                        estado = "conectado_sem_captcha"
                        resultado_ciclo = "conectado, sem captcha"
                        intervalo_atual = INTERVALO_SEGUNDOS
                    else:
                        estado = "captcha_detectado"

                    if estado != estado_anterior:
                        LOGGER.info("Estado do monitoramento alterado: %s.", estado)
                        estado_anterior = estado

                    if pagina is not None and resolver_captcha(pagina, api_key):
                        resolucoes += 1
                        intervalo_atual = INTERVALO_SEGUNDOS
                        resultado_ciclo = "captcha resolvido e token enviado"
                        LOGGER.info(
                            "Total resolvido nesta sessão: %d; aguardando próximo captcha.",
                            resolucoes,
                        )
                    elif pagina is not None:
                        resultado_ciclo = "captcha não resolvido"
                        intervalo_atual = proximo_intervalo_retry(intervalo_atual)
                        LOGGER.warning("Nova tentativa em %ds.", intervalo_atual)
                except Exception as erro:
                    resultado_ciclo = f"erro: {type(erro).__name__}"
                    registrar_excecao(
                        f"Erro inesperado no ciclo #{numero_ciclo}",
                        erro,
                        api_key,
                    )
                    intervalo_atual = proximo_intervalo_retry(intervalo_atual)
                    LOGGER.warning("Nova tentativa após erro em %ds.", intervalo_atual)

                LOGGER.debug(
                    "Ciclo #%d concluído: resultado=%s, duração=%.3fs, próximo intervalo=%ds.",
                    numero_ciclo,
                    resultado_ciclo,
                    time.perf_counter() - inicio_ciclo,
                    intervalo_atual,
                )
                time.sleep(intervalo_atual)
    except KeyboardInterrupt:
        LOGGER.info(
            "Encerrado pelo usuário. Total resolvido=%d; duração da sessão=%.2fs.",
            resolucoes,
            time.perf_counter() - inicio_sessao,
        )
        return 0
    except Exception as erro:
        registrar_excecao(
            "Falha fatal fora do ciclo de monitoramento",
            erro,
            api_key,
        )
        LOGGER.error(
            "Sessão encerrada por erro fatal após %.2fs; total resolvido=%d.",
            time.perf_counter() - inicio_sessao,
            resolucoes,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
