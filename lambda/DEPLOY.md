# NEXUS Alexa Skill — Guia de Implantação

## Estrutura do Projeto

```
lambda/
├── lambda_function.py       # Handler principal da Skill (AWS Lambda)
├── utils.py                 # Utilidades: validação, HTTP, respostas Alexa
├── requirements.txt         # Dependências Python (ask-sdk-core)
├── backup/                  # Backups dos arquivos originais
├── models/
│   ├── interactionModel.json  # Modelo de interação (intents/slots pt-BR)
│   └── skillManifest.json     # Manifesto da Skill
├── nexus_bridge/
│   ├── nexus_bridge.py      # Ponte local HTTPS (executar no PC autorizado)
│   └── README.md            # Documentação da ponte
└── tests/
    └── test_nexus_skill.py  # 77 testes (sintaxe, handlers, segurança, logs)
```

## Arquitetura

```
Usuário (voz) → Alexa → AWS Lambda (Skill) → Ponte HTTPS → NEXUS Local → Resposta → Alexa
```

## 1. Configurar a AWS Lambda

### Empacotar a Skill

```bash
cd lambda
pip install --target ./package ask-sdk-core==1.19.0
cd package && zip -r ../nexus_skill.zip . && cd ..
zip -g nexus_skill.zip lambda_function.py utils.py
```

### Criar a função Lambda

1. No console AWS, criar função Lambda com runtime Python 3.12+
2. Fazer upload de `nexus_skill.zip`
3. Handler: `lambda_function.lambda_handler`
4. Timeout: 8 segundos
5. Variáveis de ambiente:
   - `NEXUS_BRIDGE_URL`: URL HTTPS da ponte (ex: `https://seu-pc.ddns.net:8443/task`)
   - `NEXUS_BRIDGE_TOKEN`: Token compartilhado com a ponte
   - `NEXUS_AUTHORIZED_USERS`: Alexa user IDs autorizados (vírgula)

## 2. Configurar a Alexa Skill

### Usando ASK CLI

```bash
ask new --url https://developer.amazon.com/alexa/console/ask
# Importar o modelo de interação de lambda/models/interactionModel.json
# Configurar o endpoint para o ARN da função Lambda
```

### Manual (Alexa Developer Console)

1. Criar nova Skill em https://developer.amazon.com/alexa
2. Idioma: Portuguese (BR)
3. Modelo personalizado
4. Importar `lambda/models/interactionModel.json`
5. Endpoint: ARN da função Lambda
6. Nome de invocação: "nexus"

## 3. Configurar a Ponte Local

### No computador autorizado

```bash
# Gerar certificado SSL autoassinado
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes

# Configurar variáveis de ambiente
export NEXUS_BRIDGE_TOKEN="seu-token-seguro-aqui"
export NEXUS_WORKSPACE="/home/usuario/projetos"
export NEXUS_AUTHORIZED_ALEXA_USERS="amzn1.ask.account.SEU_USER_ID"

# Executar a ponte
python3 lambda/nexus_bridge/nexus_bridge.py \
  --host 0.0.0.0 --port 8443 \
  --ssl-cert cert.pem --ssl-key key.pem
```

### Segurança da ponte

- **HTTPS obrigatório**: rejeita conexões HTTP
- **Token Bearer**: autenticação em cada requisição
- **Rate limiting**: 10 req/min por usuário (configurável)
- **Workspace isolado**: apenas caminhos dentro do diretório autorizado
- **Padrões proibidos**: rm -rf /, sudo, mkfs, path traversal, etc.
- **Desativação imediata**: `NEXUS_BRIDGE_DISABLED=true`
- **Sem shell aberto**: nunca executa comandos arbitrários da IA

## 4. Testes

```bash
cd lambda
python3 tests/test_nexus_skill.py
```

Resultado esperado: 77 testes, 0 falhas.

## 5. Grupos de Operação

| Grupo | Descrição | Confirmação | Exemplos |
|-------|-----------|-------------|----------|
| A | Leitura | Não | STATUS, LISTAR, DIAGNOSTICO |
| B | Reversível | Sim | CRIAR, MODIFICAR, TESTAR |
| C | Sensível | Obrigatória | EXECUTAR, INSTALAR, REMOVER |

## 6. Variáveis de Ambiente

### Lambda (AWS)

| Variável | Descrição |
|----------|-----------|
| `NEXUS_BRIDGE_URL` | URL HTTPS da ponte local |
| `NEXUS_BRIDGE_TOKEN` | Token de autenticação |
| `NEXUS_AUTHORIZED_USERS` | Alexa user IDs (vírgula) |

### Ponte Local

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `NEXUS_BRIDGE_TOKEN` | Token (obrigatório) | — |
| `NEXUS_WORKSPACE` | Diretório autorizado | cwd |
| `NEXUS_AUTHORIZED_ALEXA_USERS` | User IDs autorizados | — |
| `NEXUS_BRIDGE_DISABLED` | Desativa se "true" | false |
| `NEXUS_MAX_REQUESTS_PER_MIN` | Rate limit | 10 |

## 7. Deploy Checklist

- [ ] Testes passam localmente (77/77)
- [ ] Skill empacotada com dependências
- [ ] Função Lambda criada e configurada
- [ ] Variáveis de ambiente configuradas na Lambda
- [ ] Ponte local executando com HTTPS
- [ ] Token compartilhado entre Lambda e ponte
- [ ] Modelo de interação importado na Alexa
- [ ] Endpoint configurado na Skill
- [ ] Teste de voz: "Alexa, peça ao nexus verificar o status"
