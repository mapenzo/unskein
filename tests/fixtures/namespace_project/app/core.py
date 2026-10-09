import app.types
import app.types.llms


def build():
    return app.types.models.Model()


def client():
    return app.types.llms.openai.OpenAI()


def broken():
    from app.helpers.gone import helper

    return helper()
