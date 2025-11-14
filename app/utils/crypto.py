import base64
import hashlib
from hashlib import md5

from Crypto import Random
from Crypto.Cipher import AES
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa


class RSAUtils:
    @staticmethod
    def generate_rsa_key_pair(key_size: int = 2048) -> tuple[str, str]:
        """Generates an RSA key pair.

        :return: Private key and public key (Base64 encoded, without identifiers)
        """
        # Generate RSA key pair
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
        )

        public_key = private_key.public_key()

        # Export private key in DER format
        private_key_der = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        # Export public key in DER format
        public_key_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        # Base64 encode the DER formatted keys
        private_key_b64 = base64.b64encode(private_key_der).decode("utf-8")
        public_key_b64 = base64.b64encode(public_key_der).decode("utf-8")

        return private_key_b64, public_key_b64

    @staticmethod
    def verify_rsa_keys(private_key: str | None, public_key: str | None) -> bool:
        """Verifies if the private and public keys match using RSA.

        :param private_key: Private key string (Base64 encoded, without identifiers)
        :param public_key: Public key string (Base64 encoded, without identifiers)
        :return: True if they match, False otherwise
        """
        if not private_key or not public_key:
            return False

        try:
            # Decode Base64 encoded public and private keys
            public_key_bytes = base64.b64decode(public_key)
            private_key_bytes = base64.b64decode(private_key)

            # Load public key
            public_key = serialization.load_der_public_key(
                public_key_bytes, backend=default_backend()
            )

            # Load private key
            private_key = serialization.load_der_private_key(
                private_key_bytes, password=None, backend=default_backend()
            )

            # Test encryption and decryption
            message = b"test"
            encrypted_message = public_key.encrypt(
                message,
                asym_padding.OAEP(
                    mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )

            decrypted_message = private_key.decrypt(
                encrypted_message,
                asym_padding.OAEP(
                    mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )

            return message == decrypted_message
        except Exception as e:
            print(f"RSA key verification failed: {e}")
            return False


class HashUtils:
    @staticmethod
    def md5(data: str | bytes, encoding: str = "utf-8") -> str:
        """Generates the MD5 hash of the data and returns it as a string.

        :param data: Input data
        :param encoding: String encoding type, UTF-8 by default
        :return: Generated MD5 hash string
        """
        if isinstance(data, str):
            data = data.encode(encoding)
        return hashlib.md5(data).hexdigest()

    @staticmethod
    def md5_bytes(data: str | bytes, encoding: str = "utf-8") -> bytes:
        """Generates the MD5 hash of the data and returns it as bytes.

        :param data: Input data
        :param encoding: String encoding type, UTF-8 by default
        :return: Generated MD5 hash binary data
        """
        if isinstance(data, str):
            data = data.encode(encoding)
        return hashlib.md5(data).digest()


class CryptoJsUtils:
    @staticmethod
    def bytes_to_key(data: bytes, salt: bytes, output=48) -> bytes:
        """Generates the key and initialization vector (IV) required for
        encryption/decryption."""
        # extended from https://gist.github.com/gsakkis/4546068
        assert len(salt) == 8, len(salt)
        data += salt
        key = md5(data).digest()
        final_key = key
        while len(final_key) < output:
            key = md5(key + data).digest()
            final_key += key
        return final_key[:output]

    @staticmethod
    def encrypt(message: bytes, passphrase: bytes) -> bytes:
        """Encrypts a message using a CryptoJS compatible encryption strategy."""
        # This is a modified copy of https://stackoverflow.com/questions/36762098/how-to-decrypt-password-from-javascript-cryptojs-aes-encryptpassword-passphras
        # Generate 8 bytes of random salt
        salt = Random.new().read(8)
        # Generate key and IV from passphrase and salt
        key_iv = CryptoJsUtils.bytes_to_key(passphrase, salt, 32 + 16)
        key = key_iv[:32]
        iv = key_iv[32:]
        # Create AES encryptor (CBC mode)
        aes = AES.new(key, AES.MODE_CBC, iv)
        # Apply PKCS#7 padding
        padding_length = 16 - (len(message) % 16)
        padding = bytes([padding_length] * padding_length)
        padded_message = message + padding
        # Encrypt message
        encrypted = aes.encrypt(padded_message)
        # Construct encrypted data format: b"Salted__" + salt + encrypted_message
        salted_encrypted = b"Salted__" + salt + encrypted
        # Return Base64 encoded encrypted data
        return base64.b64encode(salted_encrypted)

    @staticmethod
    def decrypt(encrypted: str | bytes, passphrase: bytes) -> bytes:
        """Decrypts an encrypted message using a CryptoJS compatible decryption
        strategy."""
        # Ensure input is bytes type
        if isinstance(encrypted, str):
            encrypted = encrypted.encode("utf-8")
        # Base64 decode
        encrypted = base64.b64decode(encrypted)
        # Check if the first 8 bytes are "Salted__"
        assert encrypted.startswith(b"Salted__"), "Invalid encrypted data format"
        # Extract salt value
        salt = encrypted[8:16]
        # Generate key and IV from passphrase and salt
        key_iv = CryptoJsUtils.bytes_to_key(passphrase, salt, 32 + 16)
        key = key_iv[:32]
        iv = key_iv[32:]
        # Create AES decryptor (CBC mode)
        aes = AES.new(key, AES.MODE_CBC, iv)
        # Decrypt the encrypted part
        decrypted_padded = aes.decrypt(encrypted[16:])
        # Remove PKCS#7 padding
        padding_length = decrypted_padded[-1]
        if isinstance(padding_length, str):
            padding_length = ord(padding_length)
        decrypted = decrypted_padded[:-padding_length]
        return decrypted
