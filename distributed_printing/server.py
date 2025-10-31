import time
import argparse
from concurrent import futures

import grpc

from distributed_printing import printing_pb2
from distributed_printing import printing_pb2_grpc


class PrintingService(printing_pb2_grpc.PrintingServiceServicer):
    def __init__(self, delay_seconds: float = 2.0):
        self.delay_seconds = delay_seconds

    def SendToPrinter(self, request, context):
        print(
            f"[PRINTER] [TS: {request.lamport_timestamp}] CLIENTE {request.client_id}: {request.message_content}"
        )
        time.sleep(self.delay_seconds)
        # Ecoa o timestamp recebido; servidor não mantém relógio próprio
        return printing_pb2.PrintResponse(
            success=True,
            confirmation_message="Printed",
            lamport_timestamp=request.lamport_timestamp,
        )


def serve(host: str, port: int, delay: float):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    printing_pb2_grpc.add_PrintingServiceServicer_to_server(PrintingService(delay_seconds=delay), server)
    addr = f"{host}:{port}"
    server.add_insecure_port(addr)
    server.start()
    print(f"[PRINTER] Servidor burro escutando em {addr} (delay={delay}s)")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("[PRINTER] Encerrando...")


def main():
    parser = argparse.ArgumentParser(description="Servidor de Impressão (burro)")
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP para escutar (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=50051, help="Porta do servidor de impressão (default: 50051)")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay de impressão em segundos (default: 2.0)")
    args = parser.parse_args()

    serve(args.host, args.port, args.delay)


if __name__ == "__main__":
    main()

