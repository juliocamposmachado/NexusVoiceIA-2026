# NEXUS Bridge — Ponte Local

Componente executado no computador autorizado para receber solicitações
da Skill da Alexa (AWS Lambda) e encaminhá-las ao NEXUS local.

## Arquitetura

```
Alexa → AWS Lambda → [esta ponte HTTPS] → NEXUS local → resultado → Alexa
```

## Segurança

1. **Autenticação obrigatória**: token Bearer compartilhado com a Lambda
2. **Ações permitidas**: apenas operações pré-aprovadas são executadas
3. **Proibição de padrões perigosos**: rm -rf, sudo, mkfs, path traversal, etc.
4. **Rate limiting**: máximo de requisições por minuto por usuário
5. **Confirmação para Grupo C**: operações sensíveis exigem confirmação no app
6. **Workspace isolado**: apenas caminhos dentro do diretório autorizado
7. **Sem shell aberto**: nunca executa comandos arbitrários recebidos por voz
8. **Desativação imediata**: variável `NEXUS_BRIDGE_DISABLED=true`

## Configuração

### Variáveis de ambiente

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `NEXUS_BRIDGE_TOKEN` | Token de autenticação (obrigatório) | — |
| `NEXUS_WORKSPACE` | Diretório base autorizado | cwd atual |
| `NEXUS_AUTHORIZED_ALEXA_USERS` | Alexa user IDs autorizados (vírgula) | — |
| `NEXUS_BRIDGE_DISABLED` | Desativa a ponte se "true" | false |
| `NEXUS_MAX_REQUESTS_PER_MIN` | Limite de req/min por usuário | 10 |

### Execução

```bash
# Gerar certificado SSL autoassinado (para teste)
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=nexus-bridge"

# Definir variáveis
export NEXUS_BRIDGE_TOKEN="seu-token-seguro-aqui"
export NEXUS_WORKSPACE="/home/usuario/projetos"
export NEXUS_AUTHORIZED_ALEXA_USERS="amzn1.ask.account.XXX"

# Executar
python3 nexus_bridge.py --host 0.0.0.0 --port 8443 --ssl-cert cert.pem --ssl-key key.pem
```

### Grupos de operação

| Grupo | Descrição | Confirmação |
|-------|-----------|-------------|
| A | Leitura (status, listar, diagnosticar) | Não |
| B | Alterações reversíveis (criar, testar) | Recomendada |
| C | Operações sensíveis (executar, instalar) | Obrigatória |
