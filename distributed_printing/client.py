import argparse
import random
import threading
import time
from concurrent import futures
from typing import List

import grpc

from distributed_printing import printing_pb2
from distributed_printing import printing_pb2_grpc


class LamportClock:
    def __init__(self, initial: int = 0):
        self.ts = initial

    def tick(self) -> int:
        self.ts += 1
        return self.ts

    def update_from(self, other_ts: int) -> int:
        self.ts = max(self.ts, other_ts) + 1
        return self.ts


class NodeState:
    RELEASED = "RELEASED"
    WANTED = "WANTED"
    HELD = "HELD"


class MutualExclusionService(printing_pb2_grpc.MutualExclusionServiceServicer):
    def __init__(self, node: "ClientNode"):
        self.node = node

    def RequestAccess(self, request, context):
        return self.node.handle_request_access(request)

    def ReleaseAccess(self, request, context):
        with self.node.lock:
            self.node.clock.update_from(request.lamport_timestamp)
            self.node.cv.notify_all()
        # retorna Empty (definido no .proto)
        from google.protobuf import empty_pb2

        return empty_pb2.Empty()


class ClientNode:
    def __init__(self, client_id: int, host: str, port: int, printer_addr: str, peer_addrs: List[str]):
        self.id = client_id
        self.host = host
        self.port = port
        self.addr = f"{host}:{port}"
        self.printer_addr = printer_addr
        self.peer_addrs = [addr for addr in peer_addrs if addr and addr != self.addr]

        self.clock = LamportClock(0)
        self.state = NodeState.RELEASED
        self.request_ts = -1

        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)

        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
        printing_pb2_grpc.add_MutualExclusionServiceServicer_to_server(MutualExclusionService(self), self.server)
        self.server.add_insecure_port(self.addr)

        self.peer_channels = {addr: grpc.insecure_channel(addr) for addr in self.peer_addrs}
        self.peer_stubs = {addr: printing_pb2_grpc.MutualExclusionServiceStub(ch) for addr, ch in self.peer_channels.items()}
        self.printer_channel = grpc.insecure_channel(self.printer_addr)
        self.printer_stub = printing_pb2_grpc.PrintingServiceStub(self.printer_channel)

    def handle_request_access(self, request: printing_pb2.AccessRequest) -> printing_pb2.AccessResponse:
        with self.lock:
            self.clock.update_from(request.lamport_timestamp)
            while True:
                should_defer = (
                    self.state == NodeState.HELD
                    or (
                        self.state == NodeState.WANTED
                        and (self.request_ts, self.id) < (request.lamport_timestamp, request.client_id)
                    )
                )
                if should_defer:
                    self.cv.wait()
                else:
                    self.clock.tick()
                    reply = printing_pb2.AccessResponse(
                        access_granted=True,
                        lamport_timestamp=self.clock.ts,
                    )
                    return reply

    def start(self):
        self.server.start()
        print(f"[CLIENT {self.id}] Servidor ME em {self.addr}; printer={self.printer_addr}; peers={self.peer_addrs}")

    def stop(self):
        self.server.stop(grace=None)

    def _broadcast_request(self) -> None:
        req = printing_pb2.AccessRequest(
            client_id=self.id,
            lamport_timestamp=self.request_ts,
            request_number=0,
        )

        def call_peer(addr: str):
            stub = self.peer_stubs[addr]
            try:
                resp = stub.RequestAccess(req, timeout=60.0)
                with self.lock:
                    self.clock.update_from(resp.lamport_timestamp)
                return bool(resp.access_granted)
            except grpc.RpcError as e:
                print(f"[CLIENT {self.id}] Falha ao requisitar acesso a {addr}: {e}")
                return False

        oks = 0
        for addr in self.peer_addrs:
            if call_peer(addr):
                oks += 1
        if oks != len(self.peer_addrs):
            print(f"[CLIENT {self.id}] Aviso: nem todos peers responderam ({oks}/{len(self.peer_addrs)})")

    def _send_release(self) -> None:
        req = printing_pb2.AccessRelease(
            client_id=self.id,
            lamport_timestamp=self.clock.tick(),
            request_number=0,
        )
        for addr, stub in self.peer_stubs.items():
            try:
                stub.ReleaseAccess(req, timeout=10.0)
            except grpc.RpcError:
                pass

    def enter_critical_section(self, message: str):
        with self.lock:
            self.state = NodeState.WANTED
            self.request_ts = self.clock.tick()
            my_ts = self.request_ts
            print(f"[CLIENT {self.id}] WANT SC ts={my_ts}")

        self._broadcast_request()

        with self.lock:
            self.state = NodeState.HELD
            print(f"[CLIENT {self.id}] ENTER SC ts={self.clock.ts}")

        try:
            job = printing_pb2.PrintRequest(
                client_id=self.id,
                message_content=message,
                lamport_timestamp=self.clock.tick(),
                request_number=0,
            )
            reply = self.printer_stub.SendToPrinter(job, timeout=30.0)
            with self.lock:
                self.clock.update_from(reply.lamport_timestamp)
            if not reply.success:
                print(f"[CLIENT {self.id}] Impressão falhou: {reply.confirmation_message}")
        except grpc.RpcError as e:
            print(f"[CLIENT {self.id}] Erro ao imprimir: {e}")

        with self.lock:
            self.state = NodeState.RELEASED
            self.request_ts = -1
            print(f"[CLIENT {self.id}] EXIT SC ts={self.clock.tick()}")
            self.cv.notify_all()

        self._send_release()

    def auto_job_loop(self, min_delay=3, max_delay=7):
        while True:
            time.sleep(random.uniform(min_delay, max_delay))
            msg = f"Hello from {self.id} @ {int(time.time())}"
            self.enter_critical_section(msg)


def main():
    parser = argparse.ArgumentParser(description="Cliente com Ricart-Agrawala + Lamport")
    parser.add_argument("--id", type=int, required=True, help="ID do cliente (inteiro)")
    parser.add_argument("--host", default="0.0.0.0", help="Host para escutar (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, required=True, help="Porta para escutar (ex: 50052)")
    parser.add_argument("--server", required=True, help="Endereço do servidor de impressão (ex: localhost:50051)")
    parser.add_argument("--clients", default="", help="Lista de peers separados por vírgula (ex: host1:50053,host2:50054)")
    parser.add_argument("--auto", action="store_true", help="Gera jobs automaticamente em intervalos aleatórios")
    args = parser.parse_args()

    peers = [p.strip() for p in args.clients.split(",") if p.strip()]

    node = ClientNode(client_id=args.id, host=args.host, port=args.port, printer_addr=args.server, peer_addrs=peers)
    node.start()

    if args.auto:
        print(f"[CLIENT {args.id}] Modo automático ON")
        try:
            node.auto_job_loop()
        except KeyboardInterrupt:
            print("Encerrando...")
    else:
        print("Digite mensagens para imprimir. Ctrl+C para sair.")
        try:
            while True:
                text = input().strip()
                if not text:
                    continue
                node.enter_critical_section(text)
        except KeyboardInterrupt:
            print("Encerrando...")


if __name__ == "__main__":
    main()

