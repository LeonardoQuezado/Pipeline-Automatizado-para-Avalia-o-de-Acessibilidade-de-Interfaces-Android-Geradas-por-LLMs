# Ficha de Teste Manual de Acessibilidade
**Objetivo:** Comparar resultados do teste manual (humano) com o pipeline automatizado.  
**Telas:** Login · Post Feed · Music Player  
**Data:** ___________  
**Dispositivo:** ___________ (ex: Pixel 6, Android 14)  
**Modelo LLM que gerou o código:** ___________

---

## Como cronometrar

- **Início** = quando você abre o código da tela no dispositivo pela primeira vez  
- **Fim** = quando você termeu de anotar todos os problemas encontrados  
- Cronometre cada ferramenta separado (Scanner e TalkBack)

---

## Tipos de violação (mesmas categorias do pipeline)

| Código | Nome | O que é |
|--------|------|---------|
| **IN** | Icon Null Description | `Icon(contentDescription = null)` — ícone sem descrição |
| **TF** | TextField Missing Label | `TextField` sem parâmetro `label` |
| **TT** | Touch Target | Elemento clicável menor que 48×48 dp |
| **ST** | Speakable Text Present | Elemento clicável sem nenhum texto acessível |

---

## Tela 1 — Login

### Accessibility Scanner
| Início | Fim | Tempo total |
|--------|-----|-------------|
| ___:___ | ___:___ | _______ min |

| Tipo | Qtd. encontrada | Elementos afetados (descreva) |
|------|----------------|-------------------------------|
| IN   | | |
| TF   | | |
| TT   | | |
| ST   | | |
| Outros (contraste, etc.) | | |
| **TOTAL** | | |

### TalkBack — O que foi anunciado (anotações qualitativas)
```
Campo de e-mail:   ___________________________________________
Campo de senha:    ___________________________________________
Botão Login:       ___________________________________________
Botão Esq. senha:  ___________________________________________
Outros:            ___________________________________________
```

### Resultado Pipeline (preencher depois de rodar)
| LINT | ATF | Tempo pipeline |
|------|-----|----------------|
| | | min |

---

## Tela 2 — Post Feed

### Accessibility Scanner
| Início | Fim | Tempo total |
|--------|-----|-------------|
| ___:___ | ___:___ | _______ min |

| Tipo | Qtd. encontrada | Elementos afetados (descreva) |
|------|----------------|-------------------------------|
| IN   | | |
| TF   | | |
| TT   | | |
| ST   | | |
| Outros (contraste, etc.) | | |
| **TOTAL** | | |

### TalkBack — O que foi anunciado (anotações qualitativas)
```
Imagem do post:        ___________________________________________
Botão curtir:          ___________________________________________
Botão comentar:        ___________________________________________
Botão compartilhar:    ___________________________________________
Nome do usuário:       ___________________________________________
Outros:                ___________________________________________
```

### Resultado Pipeline (preencher depois de rodar)
| LINT | ATF | Tempo pipeline |
|------|-----|----------------|
| | | min |

---

## Tela 3 — Music Player (já feita)

### Accessibility Scanner
| Início | Fim | Tempo total |
|--------|-----|-------------|
| ___:___ | ___:___ | _______ min |

| Tipo | Qtd. encontrada | Elementos afetados (descreva) |
|------|----------------|-------------------------------|
| IN   | | |
| TF   | | |
| TT   | | |
| ST   | | |
| Outros | | |
| **TOTAL** | | |

### TalkBack — O que foi anunciado
```
Botão play/pause:      ___________________________________________
Botão próxima:         ___________________________________________
Botão anterior:        ___________________________________________
Slider de progresso:   ___________________________________________
Outros:                ___________________________________________
```

### Resultado Pipeline
| LINT | ATF | Tempo pipeline |
|------|-----|----------------|
| | | min |

---

## Resumo Comparativo (preencher ao final)

| Tela | Manual: tempo | Manual: violações | Pipeline: tempo | Pipeline: violações | Δ violações |
|------|:---:|:---:|:---:|:---:|:---:|
| Login | min | | min | | |
| Post Feed | min | | min | | |
| Music Player | min | | min | | |
| **Média** | | | | | |

**Fator de aceleração (pipeline / manual):** _______ ×

> Exemplo de cálculo: manual médio = 18 min, pipeline médio = 5 min → fator = 3,6×

---

## Notas gerais

```
______________________________________________________________
______________________________________________________________
______________________________________________________________
```
