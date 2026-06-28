# Accessibility LLM Pipeline

Pipeline automatizado que usa modelos de linguagem (LLMs) para gerar código Android e avaliar sua acessibilidade via análise estática (Android Lint) e dinâmica (Accessibility Test Framework — ATF) em dispositivo real.

---

## O que é o projeto

O **Accessibility LLM Pipeline** é uma ferramenta de pesquisa que automatiza o ciclo completo: recebe um prompt descrevendo uma tela Android, envia esse prompt para um ou mais LLMs, gera o código Kotlin e XML correspondente, compila um APK real, executa verificações de acessibilidade estáticas e — se um dispositivo Android estiver conectado — instala e testa o app em execução real.

O objetivo é investigar se — e em que medida — os LLMs atuais geram código Android acessível por padrão, sem intervenção humana.

---

## O que ele faz

O pipeline executa **7 fases em sequência**:

```
[Prompt] → [LLM] → [Extração] → [Compilação] → [Lint] → [ATF] → [Relatório]
```

| Fase | O que acontece |
|------|----------------|
| **1. Geração de código** | O prompt é enviado ao LLM, que retorna `MainActivity.kt` e os layouts XML necessários |
| **2. Extração** | Blocos de código são extraídos da resposta markdown do LLM; imports ausentes são injetados automaticamente |
| **3. Injeção no template** | O código é injetado em um projeto Android base; recursos ausentes (`@string`, `@dimen`, `@color`, `@drawable`) são criados automaticamente |
| **4. Compilação** | Gradle compila o projeto e gera um APK real (`assembleDebug`) com SDK 34 |
| **5. Lint estático** | Android Lint analisa o código com regras de acessibilidade endurecidas |
| **6. ATF dinâmico** | Se um dispositivo estiver conectado via ADB, o app é instalado e testado em execução real pelo Accessibility Test Framework (Espresso + AccessibilityChecks) |
| **7. Relatório** | Issues estáticas e dinâmicas são consolidadas; relatório comparativo por LLM é exibido com métricas de efetividade, reprodutibilidade e eficiência |

### LLMs suportadas

| LLM | Tipo | Modelo |
|-----|------|--------|
| Google Gemini | API — free tier | `gemini-2.5-flash` |
| OpenAI GPT | API — pago | `gpt-4` |
| Anthropic Claude | API — pago | `claude-3-5-sonnet-20241022` |
| Ollama | Local (offline) | configurável (ex: `qwen2.5-coder:7b`) |

Gemini e Ollama funcionam sem custo. OpenAI e Anthropic são opcionais e ativados quando suas API keys estão no `.env`.

### Verificações de acessibilidade rastreadas

#### Lint estático (análise de código)

| Check | Severidade | O que detecta |
|-------|-----------|---------------|
| `ContentDescription` | Erro ❌ | `ImageView`/`ImageButton` sem descrição para leitores de tela |
| `ClickableViewAccessibility` | Erro ❌ | Elementos clicáveis inacessíveis via teclado |
| `LabelFor` | Erro ❌ | Campos de entrada sem rótulo associado |
| `KeyboardInaccessibleWidget` | Erro ❌ | Widgets que não podem ser operados por teclado |
| `TextContrastAttr` | Aviso ⚠️ | Contraste de texto insuficiente (atributos XML) |
| `ImageContrastAttr` | Aviso ⚠️ | Contraste de imagem insuficiente |
| `SmallSp` | Aviso ⚠️ | Tamanho de fonte abaixo de 12sp |
| `DuplicateSpeakableText` | Aviso ⚠️ | Texto duplicado para leitores de tela |
| `SpeakableTextPresentCheck` | Aviso ⚠️ | Elementos interativos sem texto legível |

#### ATF dinâmico (análise em execução real)

| Check | O que detecta |
|-------|---------------|
| `TouchTargetSizeCheck` | Elementos interativos com área de toque inferior a 48dp × 48dp |
| `TextContrastCheck` | Contraste de texto insuficiente medido na tela renderizada |
| `SpeakableTextPresentCheck` | Views focáveis sem conteúdo legível por TalkBack |
| `DuplicateSpeakableTextCheck` | Dois elementos com o mesmo texto anunciado pelo leitor de tela |
| `EditableContentDescCheck` | Campos de edição com `contentDescription` em vez de `hint` |

> O ATF mede elementos **após a renderização real** na tela do dispositivo. Isso detecta problemas que o Lint não consegue ver, como tamanhos calculados em código ou cores definidas em runtime.

---

## Forças

- **APK real compilado** — O projeto é compilado com Android SDK 34, Gradle 8.4 e JDK 21; não é simulação
- **Análise dinâmica em dispositivo real** — ATF roda via Espresso no celular conectado por ADB; detecta o que o Lint não vê
- **Auto-correção de código** — Imports ausentes, recursos `@string`/`@dimen`/`@color`/`@drawable` inexistentes e namespaces XML são injetados automaticamente antes da compilação
- **Totalmente automatizado** — Do prompt ao relatório, sem intervenção manual
- **Multi-LLM com execução paralela** — Gemini, OpenAI, Anthropic e Ollama rodam em paralelo no mesmo prompt
- **Relatório comparativo estruturado** — Três dimensões de avaliação: efetividade, reprodutibilidade e eficiência; exportação em JSON para análise posterior
- **Controlado por prompt** — O que é gerado é definido pelo `prompt.txt`; não é necessário alterar código
- **Interface web com saída em tempo real** — Dashboard com streaming via Server-Sent Events
- **Cache de build persistente** — Volume Docker dedicado ao cache do Gradle/Robolectric; builds subsequentes são significativamente mais rápidos
- **Isolamento total por Docker** — Ambiente reproduzível; sem dependências locais além de Docker e (opcionalmente) ADB

## Fraquezas

- **Qualidade do código gerado varia por modelo** — Modelos menores (ex: `qwen2.5-coder:7b`) geram erros de compilação com frequência em telas complexas; o pipeline tenta corrigir automaticamente mas nem sempre é possível
- **Template fixo** — Suporta apenas uma `MainActivity` com ViewBinding; apps multi-Activity, Navigation Component ou Jetpack Compose não são suportados
- **Lint não detecta problemas dinâmicos** — Cores calculadas em código, views criadas programaticamente e tamanhos dependentes do layout não são detectados pelo Lint
- **ATF requer dispositivo físico ou emulador** — Sem um dispositivo conectado, o pipeline usa Robolectric como fallback (cobertura limitada)
- **Limite de quota do Gemini free tier** — 20 requisições por dia no plano gratuito; exceder retorna erro 429
- **Sem histórico entre sessões** — Os JSON exportados permitem comparação manual, mas não há dashboard histórico automático

---

## Pré-requisitos

- [Docker](https://www.docker.com/) e Docker Compose instalados
- API Key do Google Gemini — gratuita em [aistudio.google.com](https://aistudio.google.com)
- *(Opcional)* Ollama instalado localmente com um modelo configurado
- *(Opcional)* API Keys de OpenAI e/ou Anthropic
- *(Opcional, para ATF real)* Celular Android com **Depuração USB** ativada, conectado ao computador host

---

## Tutorial de uso

### 1. Clone o repositório

```bash
git clone https://github.com/LeonardoQuezado/accessibility-llm-pipeline.git
cd accessibility-llm-pipeline
```

### 2. Configure as variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env`:

```env
GEMINI_API_KEY=sua_chave_aqui

# Ollama (local — não precisa de key)
OLLAMA_MODEL=qwen2.5-coder:7b

# ATF em dispositivo real (opcional)
EMULATOR_HOST=host.docker.internal
ADB_KEYS_DIR=C:/Users/seu_usuario/.android
```

### 3. Personalize o prompt *(opcional)*

Edite `prompts/prompt.txt` para definir qual tela Android será gerada:

```
Generate a complete Android registration screen in Kotlin.

Requirements:
- Name, email, and password fields
- A "Register" button that validates empty fields
- Show a confirmation Snackbar on success
```

> **Importante:** Não inclua requisitos técnicos como nome do pacote ou estrutura de ViewBinding — eles são adicionados automaticamente pelo pipeline.

### 4. Suba o ambiente

```bash
docker-compose up --build
```

Na primeira execução, o Docker baixa o Android SDK e as dependências do Gradle. Aguarde (pode levar alguns minutos).

### 5. Acesse a interface web

```
http://localhost:8000
```

### 6. Execute o pipeline e acompanhe o resultado

Clique em **Run Pipeline** e acompanhe a saída em tempo real. Ao final, o relatório exibe:

- Status de compilação por LLM
- Issues de acessibilidade estáticas (Lint) com arquivo e número de linha
- Issues de acessibilidade dinâmicas (ATF) com check e mensagem detalhada
- Tabela de timings por fase
- Caminho para o relatório HTML completo do Lint

### 7. Acesse os artefatos gerados

```
outputs/
├── projects/
│   ├── gemini/
│   │   ├── app/build/outputs/apk/debug/app-debug.apk
│   │   └── app/build/reports/lint-results.html
│   └── ollama/
│       ├── app/build/outputs/apk/debug/app-debug.apk
│       └── app/build/reports/lint-results.html
├── codes/
│   ├── gemini_MainActivity.kt
│   ├── gemini_activity_main.xml
│   ├── ollama_MainActivity.kt
│   └── ollama_activity_main.xml
└── reports/
    └── report_YYYYMMDD_HHMMSS.json
```

---

## Estrutura do projeto

```
accessibility-llm-pipeline/
├── src/
│   ├── pipeline.py          # Orquestração principal
│   ├── llm_client.py        # Integração com Gemini, OpenAI, Anthropic e Ollama
│   ├── code_extractor.py    # Extrai blocos Kotlin/XML das respostas LLM
│   ├── report_generator.py  # Parseia Lint XML e resultados ATF (JUnit XML)
│   └── web_server.py        # Servidor FastAPI com streaming SSE
├── templates/
│   ├── android-project/     # Template base do projeto Android
│   └── index.html           # Interface web
├── prompts/
│   └── prompt.txt           # Prompt customizável
├── outputs/                 # APKs, relatórios e JSON (gerado em execução)
├── adb-keys-placeholder/    # Placeholder quando ADB_KEYS_DIR não está configurado
├── dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```
#   P i p e l i n e - A u t o m a t i z a d o - p a r a - A v a l i a - o - d e - A c e s s i b i l i d a d e - d e - I n t e r f a c e s - A n d r o i d - G e r a d a s - p o r - L L M s  
 