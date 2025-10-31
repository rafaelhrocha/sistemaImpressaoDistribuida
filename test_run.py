import threading
import time

import grpc

from concurrent import futures

from distributed_printing import printing_pb2_grpc
from distributed_printing.server import PrintingService
from distributed_printing.client import ClientNode


def start_printer(host: str = "127.0.0.1", port: int = 50051, delay: float = 0.5):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    printing_pb2_grpc.add_PrintingServiceServicer_to_server(
        PrintingService(delay_seconds=delay), server
    )
    addr = f"{host}:{port}"
    server.add_insecure_port(addr)
    server.start()
    print(f"[TEST] Printer started at {addr} (delay={delay}s)")
    return server


def main():
    printer = start_printer()
    try:
        # peers
        p1 = "127.0.0.1:50052"
        p2 = "127.0.0.1:50053"
        p3 = "127.0.0.1:50054"

        # create clients
        c1 = ClientNode(1, "127.0.0.1", 50052, "127.0.0.1:50051", [p2, p3])
        c2 = ClientNode(2, "127.0.0.1", 50053, "127.0.0.1:50051", [p1, p3])
        c3 = ClientNode(3, "127.0.0.1", 50054, "127.0.0.1:50051", [p1, p2])

        # start client servers
        c1.start()
        c2.start()
        c3.start()

        # Allow servers to bind
        time.sleep(0.5)

        def send_jobs(client: ClientNode, msgs):
            for m in msgs:
                client.enter_critical_section(m)

        # prepare messages
        now = int(time.time())
        t1 = threading.Thread(target=send_jobs, args=(c1, [f"m1@{now}", f"m4@{now}"]))
        t2 = threading.Thread(target=send_jobs, args=(c2, [f"m2@{now}"]))
        t3 = threading.Thread(target=send_jobs, args=(c3, [f"m3@{now}"]))

        # Start near-simultaneously to induce contention
        t1.start(); t2.start(); t3.start()

        # Wait for completion
        t1.join(); t2.join(); t3.join()

        print("[TEST] All jobs completed.")

    finally:
        # stop clients
        try:
            c1.stop(); c2.stop(); c3.stop()
        except Exception:
            pass
        # stop printer
        printer.stop(0)
        print("[TEST] Stopped all services.")


if __name__ == "__main__":
    main()

