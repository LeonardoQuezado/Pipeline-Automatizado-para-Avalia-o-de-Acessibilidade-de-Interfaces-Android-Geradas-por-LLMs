# Pipeline Automatizado para Avaliação de Acessibilidade de Interfaces Android Geradas por LLMs

Pipeline automatizado para geração e avaliação de acessibilidade de interfaces
Android Jetpack Compose produzidas por LLMs. Desenvolvido como artefato de
pesquisa para o artigo submetido ao WebMedia 2026.

---

## O que é o projeto

O **Pipeline Automatizado** é uma ferramenta de pesquisa que propõe um pipeline
de ponta a ponta para avaliar a acessibilidade de interfaces Android Jetpack
Compose geradas por LLMs. O pipeline integra extração de código, regras de
correção determinísticas, compilação Android, análise estática com Lint
customizado e execução dinâmica do Accessibility Test Framework (ATF) em
dispositivo físico, com mínima intervenção humana.

O objetivo é demonstrar que a automação de ponta a ponta pode viabilizar uma
avaliação de acessibilidade viável, reprodutível e escalável de código Compose
gerado por LLMs, reduzindo substancialmente o esforço manual necessário para
avaliar modelos em rápida evolução.

---

## Pipeline — 5 estágios

```
[Prompt] → [LLM] → [Extração + Correção] → [Compilação] → [Lint] → [ATF] → [Relatório]
```

| Estágio | O que acontece |
|---------|----------------|
| **1. Geração** | O prompt é enviado ao LLM via API; a resposta contém o código Kotlin/Compose |
| **2. Extração + Auto-correção** | Blocos de código são extraídos; 55 regras determinísticas corrigem erros de compilação (imports, namespaces, recursos ausentes); 128 testes de regressão garantem que correções novas não quebrem casos anteriores |
| **3. Compilação** | Gradle compila o projeto e gera um APK real (`assembleDebug`) — Kotlin 1.9.22, AGP 8.2.2, Compose BOM 2024.02.00, compileSdk/targetSdk 36 |
| **4. Lint estático** | Regras customizadas via UAST detectam problemas de acessibilidade em tempo de compilação |
| **5. ATF dinâmico** | O app é instalado em dispositivo físico via ADB; o ATF executa verificações com rolagem da tela (3 varreduras ascendentes e 3 descendentes) |

---

## LLMs suportadas

| LLM | Modelo | Tipo |
|-----|--------|------|
| Google Gemini | `gemini-2.5-pro` | API — free tier |
| OpenAI ChatGPT | `gpt-4.5` | API — pago |
| Anthropic Claude | `claude-sonnet-4-6` | API — pago |
| Groq | `llama-3.3-70b-versatile` | API — free tier |
| DeepSeek | `deepseek-coder` | API — pago |
| xAI Grok | `grok-3-mini` | API — pago |
| Ollama | configurável | Local (offline) |

Gemini, Groq e Ollama funcionam sem custo. Os demais são opcionais e ativados
automaticamente quando suas API keys estão presentes no `.env`.

> Sem nenhuma API key? Use a rota `/teste` da interface web para simular
> execuções com respostas mockadas e explorar o pipeline sem custo.

---

## Verificações de acessibilidade

### Lint estático — regras customizadas (UAST)

| Check | O que detecta |
|-------|---------------|
| `ComposeIconNullContentDescription` | `Icon()` com `contentDescription = null` em componentes interativos ou como única indicação semântica de uma ação |
| `ComposeTextFieldMissingLabel` | `TextField`/`OutlinedTextField` sem parâmetro `label` (heurística estática que sinaliza ausência de nome acessível em runtime) |

### ATF dinâmico — dispositivo físico via ADB

| Check | O que detecta |
|-------|---------------|
| `SpeakableTextPresentCheck` | Views focáveis sem conteúdo legível por TalkBack |
| `TouchTargetSizeCheck` | Elementos interativos com área de toque inferior a 48 × 48 dp |
| `TextContrastCheck` | Contraste insuficiente de texto (razão WCAG AA: 4,5:1) medido via `UiAutomation.takeScreenshot()` na região central da tela |

O ATF realiza rolagem da tela (3 varreduras ascendentes e 3 descendentes) para
capturar elementos fora da viewport inicial.

### Modo escuro

O pipeline suporta avaliação em modo escuro. A alternância é feita manualmente
via ADB antes de cada ciclo:

```bash
adb shell cmd uimode night yes   # ativa modo escuro
adb shell cmd uimode night no    # volta ao modo claro
```

O `MaterialTheme` é automaticamente atualizado para incluir suporte a
`isSystemInDarkTheme()` durante o estágio de auto-correção.

---

## Pré-requisitos

- [Docker](https://www.docker.com/) e Docker Compose
- API Key do Google Gemini — gratuita em [aistudio.google.com](https://aistudio.google.com)
- *(Opcional)* Ollama instalado localmente com um modelo configurado
- *(Opcional)* API Keys de OpenAI, Anthropic, Groq, DeepSeek ou xAI
- *(Opcional, para ATF real)* Dispositivo Android com **Depuração USB** ativada e conectado ao computador host

> Sem dispositivo Android, os estágios de Lint estático continuam funcionando
> normalmente. O ATF é ignorado com aviso no relatório.

---

## Configuração

### 1. Clone o repositório

```bash
git clone https://github.com/LeonardoQuezado/Pipeline-Automatizado-para-Avalia-o-de-Acessibilidade-de-Interfaces-Android-Geradas-por-LLMs.git
cd Pipeline-Automatizado-para-Avalia-o-de-Acessibilidade-de-Interfaces-Android-Geradas-por-LLMs
```

### 2. Configure as variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env` com suas chaves:

```env
GEMINI_API_KEY=sua_chave_aqui

# Opcionais — cada LLM é ativado automaticamente quando a key está presente
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GROQ_API_KEY=
DEEPSEEK_API_KEY=
XAI_API_KEY=

# Ollama (local — não precisa de key)
OLLAMA_MODEL=llama3.2

# ATF em dispositivo real
EMULATOR_HOST=host.docker.internal
ADB_KEYS_DIR=C:/Users/seu_usuario/.android
```

### 3. Suba o ambiente

```bash
docker-compose up --build
```

Na primeira execução o Docker baixa o Android SDK e as dependências do Gradle.
Builds subsequentes usam cache persistente e são significativamente mais rápidos.

### 4. Acesse a interface web

```
http://localhost:8000
```

Selecione os LLMs desejados, escolha o tipo de tela e clique em **Run Pipeline**.
A saída é exibida em tempo real via streaming.

> Sem API keys? Acesse `http://localhost:8000/teste` para explorar o pipeline
> com respostas mockadas, sem necessidade de nenhuma chave.

---

## Estrutura do projeto

```
accessibility-llm-pipeline/
├── src/
│   ├── pipeline.py          # Orquestração principal dos 5 estágios
│   ├── llm_client.py        # Integração com os 7 LLMs (API + Ollama local)
│   ├── code_extractor.py    # Extrai blocos Kotlin das respostas LLM
│   ├── autocorrect.py       # 55 regras de correção + 128 testes de regressão
│   ├── report_generator.py  # Consolida resultados Lint e ATF em JSON
│   └── web_server.py        # Servidor FastAPI com streaming SSE
├── lint-rules/              # Módulo Gradle com regras UAST customizadas
├── templates/
│   └── android-project/     # Template base do projeto Jetpack Compose
├── article/
│   └── main.tex             # Artigo submetido ao WebMedia 2026
├── outputs/                 # APKs, relatórios e JSONs (gerado em execução)
├── dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Contexto de pesquisa

Este pipeline foi utilizado para avaliar 3 LLMs (Claude Sonnet 4.6, ChatGPT 5.5
e Gemini 3.1 Pro) em 8 tipos de interface móvel, nos modos claro e escuro,
totalizando 48 execuções. O pipeline alcançou 100% de sucesso na compilação e
reportou 409 ocorrências de acessibilidade distribuídas entre análise estática
e dinâmica. Os resultados completos estão descritos no artigo em `article/main.tex`.
