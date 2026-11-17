from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "evalra"
    port: int = 8100
    jwt_secret: str = "evalra-default-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
