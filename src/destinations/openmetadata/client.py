import httpx
from typing import Any, Dict, Optional, Union, Literal, overload, Tuple
from urllib.parse import urljoin
import logging
from src.config import OMDConfig
from src.models import SampleData
from src.logger import LoggerFactory


class AsyncOMDClient:
    """
    Async OpenMetadata API Client
    """

    def __init__(
        self,
        config: Union[OMDConfig, Dict[str, Any]],
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        base_client: Optional[httpx.AsyncClient] = None,
        logger: Optional[logging.Logger] = None,
    ):
        if isinstance(config, dict):
            config = OMDConfig(**config)
        self.config = config
        self.logger = logger or LoggerFactory.getLogger("omd.client")

        # Reuse shared client (e.g., from FastAPI lifespan) or create new
        if base_client:
            self._client = base_client
            self._owns_client = False
        else:
            timeout = httpx.Timeout(self.config.timeout)
            limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
            transport = transport or httpx.AsyncHTTPTransport(
                retries=self.config.retries
            )
            self._client = httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                transport=transport,
                headers={
                    "Authorization": f"Bearer {self.config.token.get_secret_value()}"
                },
            )
            self._owns_client = True

        self._base_url = f"{self.config.api_url}/{self.config.api_version}"

    async def aclose(self) -> None:
        """Gracefully close the internal httpx client if owned."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "AsyncOMDClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()

    def _build_url(self, endpoint: str) -> str:
        """Safely join base URL and endpoint (handles leading/trailing slashes)."""
        return urljoin(f"{self._base_url}/", endpoint.lstrip("/"))

    @overload
    async def get(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = ...,
        nullable: Literal[True],
    ) -> Optional[Dict[str, Any]]: ...

    @overload
    async def get(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = ...,
        nullable: Literal[False] = ...,
    ) -> Dict[str, Any]: ...

    async def get(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        nullable: bool = False,
    ) -> Optional[Dict[str, Any]]:
        url = self._build_url(endpoint)
        try:
            response = await self._client.get(url, params=params)
            if nullable and response.status_code == 404:
                self.logger.debug("GET %s → 404 (nullable=True → returning None)", url)
                return None
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            self.logger.error("HTTP error on GET %s: %s", url, e)
            raise
        except Exception as e:
            self.logger.exception("Unexpected error on GET %s: %s", url, e)
            raise

    async def get_table_by_name(
        self, fqn: str, fields: str = "*", nullable: bool = False
    ) -> Optional[Dict[str, Any]]:
        params = {"fields": fields}
        return await self.get(
            endpoint=f"/tables/name/{fqn}", params=params, nullable=nullable
        )

    async def get_table_by_id(
        self, id: str, fields: str = "*", nullable: bool = False
    ) -> Optional[Dict[str, Any]]:
        params = {"fields": fields}
        return await self.get(
            endpoint=f"/tables/{id}", params=params, nullable=nullable
        )

    async def post(
        self,
        endpoint: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint)
        try:
            response = await self._client.post(url, json=json, data=data, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error("POST %s failed: %s", url, e)
            raise

    async def put(
        self,
        endpoint: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint)
        try:
            response = await self._client.put(url, json=json, data=data, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error("PUT %s failed: %s", url, e)
            raise

    async def add_sample_data(self, id: str, body: SampleData) -> Dict[str, Any]:
        return await self.put(
            endpoint=f"/tables/{id}/sampleData", json=body.model_dump(mode="json")
        )

    async def patch(
        self,
        endpoint: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """OpenMetadata often uses PATCH semantics for partial updates."""
        url = self._build_url(endpoint)
        try:
            response = await self._client.patch(
                url, json=json, data=data, params=params
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error("PATCH %s failed: %s", url, e)
            raise

    async def delete(
        self,
        endpoint: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> bool:
        url = self._build_url(endpoint)
        try:
            response: httpx.Response = await self._client.delete(
                url, json=json, params=params
            )
            if response.status_code == 204:  # No Content
                return True
            response.raise_for_status()
            return response.status_code in (200, 201, 202)
        except Exception as e:
            self.logger.error("DELETE %s failed: %s", url, e)
            raise

    async def is_healthy(self) -> Tuple[bool, Optional[Exception]]:
        """A check whether an OpenMetadata client connection is working
        Returns:
            Tuple[bool, Optional[Exception]]: Client is successfully \
                making requests, returns Exception object if an error has occured
        """
        try:
            await self.get(endpoint="/tables", params={"limit": 0}, nullable=False)
        except Exception as ex:
            return False, ex
        return True, None
