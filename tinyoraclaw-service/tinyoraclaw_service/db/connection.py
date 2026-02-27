import logging

import oracledb

oracledb.defaults.thin_mode = True

logger = logging.getLogger(__name__)


class OracleConnectionManager:
    """Manages Oracle async connection pools for both FreePDB and ADB.

    FreePDB (local Docker):
        Simple host:port/service DSN, no TLS.

    ADB wallet-less (TLS):
        Full DSN descriptor with ``(protocol=tcps)`` -- the thin driver
        handles TLS natively, no wallet files needed.  Credentials match
        the oracle-ai-developer-hub ``config.yaml`` format.

    ADB wallet (mTLS):
        DSN descriptor + ``config_dir`` pointing to the wallet directory.
    """

    def __init__(self, settings):
        self.settings = settings
        self.pool: oracledb.AsyncConnectionPool | None = None

    async def create_pool(self) -> oracledb.AsyncConnectionPool:
        params = {
            "user": self.settings.oracle_user,
            "password": self.settings.oracle_password,
            "dsn": self.settings.get_dsn(),
            "min": self.settings.oracle_pool_min,
            "max": self.settings.oracle_pool_max,
        }

        if self.settings.is_adb:
            if self.settings.uses_wallet:
                # mTLS: wallet directory required
                params["config_dir"] = self.settings.oracle_wallet_path
                params["ssl_server_dn_match"] = True
                if self.settings.oracle_wallet_password:
                    params["wallet_password"] = self.settings.oracle_wallet_password
                logger.info("ADB connection mode: mTLS (wallet at %s)",
                            self.settings.oracle_wallet_path)
            else:
                # Wallet-less TLS: the DSN descriptor contains tcps + ssl_server_dn_match
                logger.info("ADB connection mode: wallet-less TLS")
        else:
            logger.info("FreePDB connection: %s", self.settings.get_dsn())

        self.pool = await oracledb.create_pool_async(**params)
        return self.pool

    async def close_pool(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def get_connection(self):
        return await self.pool.acquire()

    async def release_connection(self, conn):
        await self.pool.release(conn)
