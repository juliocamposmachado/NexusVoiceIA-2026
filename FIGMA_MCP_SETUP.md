# Figma MCP — Configuração no NEXUS TERMINAL

O NEXUS TERMINAL integra o **Figma MCP Server oficial** como uma capacidade
especializada para tarefas envolvendo design, UI, mockups e conversão
Figma → código. Esta integração é opcional: o NEXUS funciona normalmente
sem o Figma MCP configurado.

## O que é Figma MCP

O [Figma MCP Server](https://developers.figma.com/docs/figma-mcp-server/tools-and-prompts/)
expõe ferramentas para ler designs do Figma, baixar assets, obter variáveis
de design system, e escrever no canvas do Figma — tudo via protocolo MCP
(Model Context Protocol).

## Pré-requisitos

- **Node.js** (para npx/npm) — necessário para o modo CLI local
- **Conta Figma** com acesso aos arquivos que deseja ler
- **Figma API Key** (Personal Access Token) — gere em Figma → Settings → Security → Personal access tokens

## Configuração

### Opção 1: CLI local via npx (recomendado)

```bash
# Defina seu token Figma (não coloque no código)
export FIGMA_API_KEY="fig_xxxxxxxxxxxxxxxxxxxx"

# O NEXUS detecta npx automaticamente; nenhuma instalação permanente necessária.
# Para instalar globalmente (opcional):
npm install -g figma-developer-mcp
```

### Opção 2: Servidor MCP remoto

```bash
# URL do servidor remoto do Figma MCP
export NEXUS_FIGMA_MCP_URL="https://mcp.figma.com/mcp"

# Token ainda é necessário
export FIGMA_API_KEY="fig_xxxxxxxxxxxxxxxxxxxx"
```

### Variáveis de ambiente

| Variável | Obrigatório | Descrição |
|---|---|---|
| `FIGMA_API_KEY` | Sim (modo CLI) | Personal Access Token do Figma |
| `FIGMA_ACCESS_TOKEN` | Alternativa | Mesma função que `FIGMA_API_KEY` |
| `NEXUS_FIGMA_MCP_URL` | Não | URL do servidor MCP remoto |
| `NEXUS_FIGMA_TIMEOUT` | Não | Timeout em segundos (padrão: 30) |

**Segurança:** Nunca coloque tokens diretamente no código. Use variáveis
de ambiente ou arquivos `.env` (adicionados ao `.gitignore`).

## Como verificar

```bash
# No NEXUS TERMINAL:
/figma status    # mostra se está instalado, configurado e disponível
/figma tools     # lista todas as ferramentas suportadas
/figma test      # testa detecção, descoberta e chamada real
/figma context https://www.figma.com/design/XXXXX/MyFile  # obtém contexto
/figma help      # ajuda completa
```

## Ferramentas suportadas (18)

### Leitura (Read)
- `get_design_context` — contexto de design (layout, tipografia, componentes)
- `get_metadata` — estrutura XML esparsa de uma seleção
- `get_screenshot` — captura de tela PNG de um node
- `download_assets` — baixa exports e imagens originais (remote-only)
- `get_variable_defs` — variáveis e estilos (cores, espaçamento, tipografia)
- `get_motion_context` — dados de animação keyframe
- `search_design_system` — busca componentes no design system
- `get_code_connect_map` — mapeamento node ID → componente de código
- `get_code_connect_suggestions` — sugestões de mapeamento Code Connect
- `get_context_for_code_connect` — metadados para templates (remote-only)
- `get_libraries` — lista bibliotecas inscritas (remote-only)
- `get_figjam` — converte diagramas FigJam para XML
- `get_generative_plugin` — lê manifest de plugin generativo (remote-only)

### Escrita (Write — remote-only)
- `use_figma` — cria ou modifica conteúdo no canvas
- `generate_figma_design` — gera design a partir de prompt
- `generate_diagram` — gera diagrama no FigJam
- `generate_image` — gera imagem a partir de prompt
- `create_new_file` — cria novo arquivo Figma

## Como o NEXUS usa o Figma MCP

1. **Detecção automática:** Quando você executa `/code` com uma solicitação
   que menciona Figma, design, UI, mockup ou inclui uma URL do Figma, o
   NEXUS detecta automaticamente a necessidade.

2. **Contexto de design:** O NEXUS executa ferramentas de leitura
   (`get_design_context`, `get_metadata`, `get_variable_defs`, etc.) para
   obter contexto estruturado do design.

3. **Planejamento:** O contexto Figma é injetado no `file_state` enviado
   ao Copilot, permitindo que o cérebro do agente gere código alinhado ao
   design.

4. **Code Connect:** Quando disponível, o NEXUS usa `get_code_connect_map`
   e `search_design_system` para favorecer reutilização de componentes
   em vez de criar duplicados.

5. **Validação:** Respostas do Figma MCP são validadas — placeholders
   (`...`, `TODO`) e respostas vazias são rejeitadas.

## Tratamento de erros

O NEXUS trata estes cenários sem quebrar:
- Figma MCP não instalado → capacidade marcada como indisponível
- Token ausente → chamadas reais são puladas, diagnóstico informado
- Timeout → operação abortada, fluxo continua
- Autenticação expirada → erro reportado, outras tarefas prosseguem
- JSON malformado → erro capturado, resposta rejeitada
- Ferramenta inexistente → erro claro com lista de ferramentas válidas

## Limitações

- Ferramentas de escrita (`use_figma`, `generate_*`) só funcionam no modo
  remoto (`NEXUS_FIGMA_MCP_URL` configurado)
- O NEXUS não executa ferramentas de escrita durante o planejamento —
  apenas leitura
- Operações de escrita no Figma respeitam o sistema de confirmação do NEXUS
