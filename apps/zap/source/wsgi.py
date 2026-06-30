try:
    from zap.app import create_app
except ModuleNotFoundError:
    from app import create_app


app = create_app()
