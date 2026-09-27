from app.models import User


class UserService:
    def greet(self, where: str) -> str:
        return f"{User().name} @ {where}"
