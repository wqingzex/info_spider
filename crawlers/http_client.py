"""统一的 HTTP 客户端工厂 - 自动处理代理配置"""
import os
import httpx


def _get_proxy_url() -> str | None:
    """优先使用 HTTP 代理（httpx 0.28 不支持 SOCKS 方案字符串）"""
    for env in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        val = os.environ.get(env, "")
        if val and val.startswith("http"):
            return val
    # ALL_PROXY 可能是 socks://，跳过
    return None


def build_client(timeout: int = 20, headers: dict | None = None) -> httpx.Client:
    """创建配置好代理的 httpx 同步客户端"""
    proxy_url = _get_proxy_url()
    kwargs: dict = {
        "timeout": timeout,
        "headers": headers or {},
        "trust_env": False,  # 避免自动读取 SOCKS ALL_PROXY
        "follow_redirects": True,
    }
    if proxy_url:
        kwargs["mounts"] = {
            "https://": httpx.HTTPTransport(proxy=proxy_url),
            "http://": httpx.HTTPTransport(proxy=proxy_url),
        }
    return httpx.Client(**kwargs)
