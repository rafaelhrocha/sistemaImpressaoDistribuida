Sistema de Impressão Distribuída (gRPC + Ricart-Agrawala + Lamport)

Este projeto implementa:
- Servidor de impressão “burro” (`PrintingService`), que apenas recebe e imprime mensagens.
- Clientes “inteligentes” com exclusão mútua distribuída via Ricart-Agrawala e relógios lógicos de Lamport (`MutualExclusionService`).

Estrutura de pastas
- `proto/printing.proto`: definição dos serviços/mensagens gRPC.
- `distributed_printing/server.py`: servidor de impressão (porta padrão: 50051).
- `distributed_printing/client.py`: cliente com RA+Lamport que coordena acesso e envia jobs.
- `requirements.txt`: dependências Python.

Pré-requisitos
- Python 3.10+
- Pacotes: `grpcio`, `grpcio-tools`

Instalação
```
python -m pip install -r requirements.txt
```

Gerar stubs gRPC a partir do `.proto`
```
python -m grpc_tools.protoc -I proto --python_out=distributed_printing --grpc_python_out=distributed_printing proto/printing.proto
```
Isso gerará `distributed_printing/printing_pb2.py` e `distributed_printing/printing_pb2_grpc.py`.

Como executar (exemplo com 3 clientes)
1) Terminal 1 — Servidor de impressão:
```
python -m distributed_printing.server --port 50051
```

2) Terminal 2 — Cliente 1:
```
python -m distributed_printing.client --id 1 --server localhost:50051 --port 50052 --clients localhost:50053,localhost:50054 --auto
```

3) Terminal 3 — Cliente 2:
```
python -m distributed_printing.client --id 2 --server localhost:50051 --port 50053 --clients localhost:50052,localhost:50054 --auto
```

4) Terminal 4 — Cliente 3:
```
python -m distributed_printing.client --id 3 --server localhost:50051 --port 50054 --clients localhost:50052,localhost:50053 --auto
```

Notas de implementação
- O servidor de impressão não participa do algoritmo; apenas imprime `[TS: <ts>] CLIENTE <id>: <mensagem>` e simula delay (2s).
- Nos clientes, o handler `RequestAccess` pode bloquear enquanto o processo local estiver em `HELD` (dentro da SC) ou `WANTED` com prioridade (empate por `(timestamp, id)`). Ao sair da SC, o cliente acorda handlers para responder.
- O RPC `ReleaseAccess` é opcional e usado para sinalização/logs; o deferimento ocorre no próprio `RequestAccess`.
- Modo interativo: rode sem `--auto` para digitar mensagens manualmente.

Testes
- Existe no projeto o arquivo test_run.py dedicado para testar a aplicação de forma geral.
