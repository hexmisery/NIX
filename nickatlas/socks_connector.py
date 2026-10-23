from aiohttp_socks import ProxyConnector
from aiohttp_socks.connector import _ResponseHandler
from python_socks.async_.asyncio.v2 import Proxy


class PinnedSocksConnector(ProxyConnector):
    async def _wrap_create_connection(self, *args, addr_infos, req, timeout, **kwargs):
        if not addr_infos:
            raise OSError("No validated proxy destination")
        host, port = addr_infos[0][4][:2]
        proxy = Proxy(
            proxy_type=self._proxy_type,
            host=self._proxy_host,
            port=self._proxy_port,
            username=self._proxy_username,
            password=self._proxy_password,
            rdns=False,
            proxy_ssl=self._proxy_ssl,
        )
        stream = None
        try:
            stream = await proxy.connect(
                dest_host=host, dest_port=port, timeout=timeout.sock_connect
            )
            context = kwargs.get("ssl")
            if context is not None:
                stream = await stream.start_tls(
                    hostname=req.server_hostname or req.url.host, ssl_context=context
                )
            transport = stream.writer.transport
            protocol = _ResponseHandler(loop=self._loop, writer=stream.writer)
            transport.set_protocol(protocol)
            protocol.connection_made(transport)
            return transport, protocol
        except BaseException:
            if stream is not None:
                await stream.close()
            raise
