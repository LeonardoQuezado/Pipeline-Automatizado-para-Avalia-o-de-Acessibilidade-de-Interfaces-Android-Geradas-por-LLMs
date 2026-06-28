# Roadmap — Accessibility LLM Pipeline

## Até sexta-feira (apresentação ao orientador)

### Bloco 1 — Análise (quarta/quinta manhã)

- [ ] **ATF mais completo** — expandir o teste para scroll + interações com campos e botões; garantir cobertura além do que está visível na abertura da tela
- [ ] **Lint revisado** — auditar checks ativos; elevar `TouchTargetSizeCheck` e outros para ERROR; avaliar `lint.xml` customizado por projeto
- [ ] **Outras formas de verificação** — pesquisar `axe-android`, UIAutomator, contraste em runtime; decidir o que integra agora vs. trabalho futuro

### Bloco 2 — Escopo dos testes (quinta)

- [ ] **Duas LLMs adicionais** — integrar Groq (`llama-3.3-70b`) e DeepSeek (`deepseek-coder-v2`); testar compilação com cada uma antes da bateria
- [ ] **Lista de prompts** — definir 3–5 prompts cobrindo tipos de tela distintos (login, cadastro, feed, configurações, onboarding); salvar em `prompts/`

### Bloco 3 — Execução e resultados (sexta)

- [ ] **Bateria de testes completa** — mínimo 3 execuções por prompt × LLM; coletar todos os JSONs
- [ ] **Gráficos comparatórios** — taxa de build, issues por LLM/tipo (Lint vs ATF), tempo médio por fase; exportar como PNG ou página HTML

---

## Fim de semana (extra)

- [ ] **Painel de gerenciamento de LLMs na interface web** — lista de LLMs conhecidas com toggle de ativação, campo para inserir API key diretamente na UI, campo de modelo para Ollama; salvar configuração em `config.json`; eliminar necessidade de editar `.env` manualmente
