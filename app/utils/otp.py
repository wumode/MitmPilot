import pyotp

from app.core.config import settings


class OtpUtils:
    @staticmethod
    def generate_secret_key(username: str) -> tuple[str, str]:
        try:
            secret = pyotp.random_base32()
            uri = pyotp.totp.TOTP(secret).provisioning_uri(
                name=settings.PROJECT_NAME,
                issuer_name=f"{settings.PROJECT_NAME}(" + username + ")",
            )
            return secret, uri
        except Exception as err:
            print(str(err))
            return "", ""

    @staticmethod
    def is_legal(otp_uri: str, password: str) -> bool:
        """
        校验二次验证是否正确
        """
        try:
            return pyotp.TOTP(pyotp.parse_uri(otp_uri).secret).verify(password)
        except Exception as err:
            print(str(err))
            return False

    @staticmethod
    def check(secret: str, password: str) -> bool:
        """
        校验二次验证是否正确
        """
        try:
            totp = pyotp.TOTP(secret)
            return totp.verify(password)
        except Exception as err:
            print(str(err))
            return False

    @staticmethod
    def get_secret(otp_uri: str) -> str:
        """
        获取uri中的secret
        """
        try:
            return pyotp.parse_uri(otp_uri).secret
        except Exception as err:
            print(str(err))
            return ""
