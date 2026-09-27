import os

from app.services.user import UserService


def main() -> None:
    UserService().greet(os.getcwd())
