from microbootstrap.granian_server import create_granian_server

from payment_processing.settings import settings


def run_main() -> None:
    create_granian_server("payment_processing.api.application:build_application", settings, factory=True).serve()


if __name__ == "__main__":
    run_main()
