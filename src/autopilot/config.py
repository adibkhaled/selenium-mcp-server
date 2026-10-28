from dotenv import find_dotenv, load_dotenv


def load_environment() -> None:
    load_dotenv(find_dotenv(usecwd=True))
