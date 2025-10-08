import secrets
from collections.abc import Callable
from typing import Literal

from app.chain import ChainBase
from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.db.models.user import User
from app.db.user_oper import UserOper
from app.log import logger
from app.schemas import AuthCredentials, AuthInterceptCredentials
from app.schemas.types import ChainEventType

PASSWORD_INVALID_CREDENTIALS_MESSAGE = (
    "Incorrect username or password or secondary verification code"
)


class UserChain(ChainBase):
    """User chain, handling multiple authentication protocols."""

    def user_authenticate(
        self,
        username: str | None = None,
        password: str | None = None,
        mfa_code: str | None = None,
        code: str | None = None,
        grant_type: str = "password",
    ) -> tuple[Literal[True], User] | tuple[Literal[False], str]:
        """Authenticate users and handle different authentication processes according to
        different grant_type.

        :param username: Username, applicable to "password" grant_type
        :param password: User password, applicable to "password" grant_type
        :param mfa_code: One-time password, applicable to "password" grant_type
        :param code: Authorization code, applicable to "authorization_code" grant_type
        :param grant_type: Authentication type, such as "password", "authorization_code",
                           "client_credentials"
        :return:
            - For successful authentication, return (True, User)
            - For failed authentication, return (False, "Error message")
        """
        credentials = AuthCredentials(
            username=username,
            password=password,
            mfa_code=mfa_code,
            code=code,
            grant_type=grant_type,
        )
        logger.debug(
            f"Authentication type: {grant_type}, "
            f"preparing to verify the identity of user {username}"
        )

        auth_handlers: dict[
            str,
            Callable[
                [AuthCredentials],
                tuple[Literal[True], User] | tuple[Literal[False], str],
            ],
        ] = {
            "password": self._authenticate_by_password,
            "authorization_code": self._authenticate_by_authorization_code,
        }

        handler = auth_handlers.get(grant_type)
        if not handler:
            logger.debug(f"Authentication type {grant_type} is not implemented")
            return False, "Unsupported authentication type"

        return handler(credentials)

    def _authenticate_by_password(
        self, credentials: AuthCredentials
    ) -> tuple[Literal[True], User] | tuple[Literal[False], str]:
        """Process password authentication flow."""
        success, user_or_message = self.password_authenticate(credentials=credentials)
        if success:
            logger.info(
                f"User {credentials.username} "
                f"passed password authentication successfully"
            )
            return True, user_or_message

        # User does not exist or password is wrong, consider auxiliary authentication
        if settings.AUXILIARY_AUTH_ENABLE:
            logger.warning(
                "Password authentication failed, trying to perform auxiliary "
                "authentication through an external service..."
            )
            aux_success, aux_user_or_message = self.auxiliary_authenticate(
                credentials=credentials
            )
            if aux_success:
                return True, aux_user_or_message
            else:
                return False, PASSWORD_INVALID_CREDENTIALS_MESSAGE
        else:
            logger.debug(
                f"Auxiliary authentication is not enabled, "
                f"user {credentials.username} authentication failed"
            )
            return False, PASSWORD_INVALID_CREDENTIALS_MESSAGE

    def _authenticate_by_authorization_code(
        self, credentials: AuthCredentials
    ) -> tuple[Literal[True], User] | tuple[Literal[False], str]:
        """Process authorization code authentication flow."""
        if settings.AUXILIARY_AUTH_ENABLE:
            aux_success, aux_user_or_message = self.auxiliary_authenticate(
                credentials=credentials
            )
            if aux_success:
                return True, aux_user_or_message
            else:
                return False, "Authentication failed"
        else:
            return False, "Authentication failed"

    @staticmethod
    def password_authenticate(
        credentials: AuthCredentials,
    ) -> tuple[Literal[True], User] | tuple[Literal[False], str]:
        """Password authentication.

        :param credentials: Authentication credentials, including username,
                            password, and optional MFA authentication code
        :return:
            - On success, return (True, User), where User is the user object that
              passed the authentication
            - On failure, return (False, "Error message")
        """
        if not credentials or credentials.grant_type != "password":
            logger.info(
                "Password authentication failed, authentication type does not match"
            )
            return False, PASSWORD_INVALID_CREDENTIALS_MESSAGE
        assert isinstance(credentials.username, str)
        assert isinstance(credentials.password, str)
        user = UserOper().get_by_name(name=credentials.username)
        if not user:
            logger.info(
                f"Password authentication failed, "
                f"user {credentials.username} does not exist"
            )
            return False, PASSWORD_INVALID_CREDENTIALS_MESSAGE

        if not user.is_active:
            logger.info(
                f"Password authentication failed, "
                f"user {credentials.username} has been disabled"
            )
            return False, PASSWORD_INVALID_CREDENTIALS_MESSAGE

        if not verify_password(credentials.password, str(user.hashed_password)):
            logger.info(
                f"Password authentication failed, "
                f"the password verification of user {credentials.username} failed"
            )
            return False, PASSWORD_INVALID_CREDENTIALS_MESSAGE

        return True, user

    def auxiliary_authenticate(
        self, credentials: AuthCredentials
    ) -> tuple[Literal[True], User] | tuple[Literal[False], str]:
        """Auxiliary user authentication.

        :param credentials: Authentication credentials, including necessary
                            authentication information
        :return:
            - On success, return (True, User), where User is the user object that
              passed the authentication
            - On failure, return (False, "Error message")
        """
        if not credentials:
            return False, "Invalid authentication credentials"

        # Check if the user is disabled
        useroper = UserOper()
        if credentials.username:
            user = useroper.get_by_name(name=credentials.username)
            if user and not user.is_active:
                logger.info(
                    f"User {user.name} has been disabled, skip subsequent identity "
                    f"verification"
                )
                return False, PASSWORD_INVALID_CREDENTIALS_MESSAGE

        logger.debug(
            f"Authentication type: {credentials.grant_type}, "
            f"trying to perform auxiliary authentication through the system module, "
            f"user: {credentials.username}"
        )
        result = self.run_module("user_authenticate", credentials=credentials)

        if not result:
            logger.debug(
                f"Auxiliary authentication through the system module failed, "
                f"trying to trigger the {ChainEventType.AuthVerification} event"
            )
            event = self.eventmanager.send_event(
                etype=ChainEventType.AuthVerification, data=credentials
            )
            if not event or not event.event_data:
                logger.error(
                    f"Authentication type: {credentials.grant_type}, "
                    f"auxiliary authentication failed, no valid data returned"
                )
                return (
                    False,
                    f"Authentication type: {credentials.grant_type}, "
                    f"auxiliary authentication event failed or invalid",
                )

            credentials = (
                event.event_data
            )  # Use the authentication data returned by the event
        else:
            logger.info(
                f"Auxiliary authentication through the system module was successful, "
                f"user: {credentials.username}"
            )
            # Use the authentication data returned by the module authentication
            credentials = result

        # Process the logic of successful authentication
        success = self._process_auth_success(
            username=credentials.username, credentials=credentials
        )
        if success:
            logger.info(f"User {credentials.username} passed auxiliary authentication")
            return True, useroper.get_by_name(credentials.username)
        else:
            logger.warning(
                f"User {credentials.username} failed auxiliary authentication"
            )
            return False, PASSWORD_INVALID_CREDENTIALS_MESSAGE

    def _process_auth_success(
        self, username: str, credentials: AuthCredentials
    ) -> bool:
        """Process the logic of successful auxiliary authentication, return a user
        object or create a new user.

        :param username: Username
        :param credentials: Authentication credentials,
            including token, channel, service and other information
        :return:
            - If the authentication is successful and the user exists or has been
              created, return the User object
            - If the authentication is intercepted or fails, return None
        """
        if not username:
            logger.info(
                f"Failed to obtain the corresponding user information, "
                f"{credentials.grant_type} authentication failed"
            )
            return False

        token, channel, service = (
            credentials.token,
            credentials.channel,
            credentials.service,
        )
        if not all([token, channel, service]):
            logger.info(
                f"User {username} failed the {credentials.grant_type} authentication, "
                f"necessary information is insufficient"
            )
            return False
        assert isinstance(channel, str)
        assert isinstance(service, str)
        assert isinstance(token, str)
        # Trigger the interception event of successful authentication
        intercept_event = self.eventmanager.send_event(
            etype=ChainEventType.AuthIntercept,
            data=AuthInterceptCredentials(
                username=username,
                channel=channel,
                service=service,
                token=token,
                status="completed",
            ),
        )
        if intercept_event and intercept_event.event_data:
            intercept_data: AuthInterceptCredentials = intercept_event.event_data
            if intercept_data.cancel:
                logger.warning(
                    f"Authentication was intercepted, "
                    f"user: {username}, channel: {channel}, "
                    f"service: {service}, interception source: {intercept_data.source}"
                )
                return False

        # Check if the user exists, if not, and the current authentication is password
        # authentication, create a new user
        useroper = UserOper()
        user = useroper.get_by_name(name=username)
        if user:
            # If the user exists, but has been disabled, respond directly
            if not user.is_active:
                logger.info(
                    f"Auxiliary authentication failed, "
                    f"user {username} has been disabled"
                )
                return False
            anonymized_token = f"{token[: len(token) // 2]}********"
            logger.info(
                f"Authentication type: {credentials.grant_type}, user: {username}, "
                f"channel: {channel}, "
                f"service: {service} authentication successful, "
                f"token: {anonymized_token}"
            )
            return True
        else:
            if credentials.grant_type == "password":
                useroper.add(
                    name=username,
                    is_active=True,
                    is_superuser=False,
                    hashed_password=get_password_hash(secrets.token_urlsafe(16)),
                )
                logger.info(
                    f"User {username} does not exist, "
                    f"has passed the {credentials.grant_type} "
                    f"authentication and has created a normal user"
                )
                return True
            else:
                logger.warning(
                    f"Authentication type: {credentials.grant_type}, "
                    f"user: {username}, channel: {channel}, "
                    f"service: {service} authentication failed, "
                    f"failed to find the corresponding user information locally"
                )
                return False
