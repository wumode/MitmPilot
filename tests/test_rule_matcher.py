from urllib.parse import urlparse

import pytest
from mitmproxy.http import HTTPFlow
from mitmproxy.test import tflow

from app.helper.ruleparser import ClashRuleParser
from app.utils.rule import HttpFlowMatcher


class TestHttpFlowMatcher:
    @pytest.mark.parametrize(
        "rule, url, expected",
        [
            (
                "DOMAIN,example.com,DIRECT",
                "http://example.com/",
                True,
            ),
            (
                "DOMAIN,example.com,DIRECT",
                "http://test.com/",
                False,
            ),
            (
                "DOMAIN-SUFFIX,example.com,DIRECT",
                "http://test.example.com/",
                True,
            ),
            (
                "DOMAIN-SUFFIX,example.com,DIRECT",
                "http://example.com/",
                True,
            ),
            (
                "DOMAIN-SUFFIX,example.com,DIRECT",
                "http://example.org/",
                False,
            ),
            (
                "DOMAIN-KEYWORD,example,DIRECT",
                "http://test.example.com/",
                True,
            ),
            (
                "DOMAIN-KEYWORD,example,DIRECT",
                "http://test.com/",
                False,
            ),
            (
                "DOMAIN-REGEX,example\\.com,DIRECT",
                "http://example.com/",
                True,
            ),
            (
                "DOMAIN-REGEX,.*example\\.com,DIRECT",
                "http://test.example.com/",
                True,
            ),
            (
                "DOMAIN-REGEX,example\\.com,DIRECT",
                "http://test.com/",
                False,
            ),
            (
                "DOMAIN-WILDCARD,*.example.com,DIRECT",
                "http://test.example.com/",
                True,
            ),
            (
                "DOMAIN-WILDCARD,*.example.com,DIRECT",
                "http://example.com/",
                False,
            ),
            (
                "DOMAIN-WILDCARD,example.com,DIRECT",
                "http://example.com/",
                True,
            ),
            (
                "AND,((DOMAIN,baidu.com),(NOT,(DST-PORT,80))),DIRECT",
                "http://baidu.com/",
                True,
            ),
        ],
    )
    def test_matches(self, rule: str, url: str, expected: bool):
        parsed_url = urlparse(url)
        port = parsed_url.port
        if port is None:
            if parsed_url.scheme == "https":
                port = 443
            else:
                port = 80
        flow: HTTPFlow = tflow.tflow(
            req=tflow.treq(
                host=parsed_url.hostname, port=port, scheme=parsed_url.scheme.encode()
            )
        )
        clash_rule = ClashRuleParser.parse_rule_line(rule)
        assert clash_rule is not None
        assert HttpFlowMatcher.matches(clash_rule, flow) == expected

    @pytest.mark.parametrize(
        "rule, client_ip, server_ip, expected",
        [
            # IP-CIDR tests
            ("IP-CIDR,192.168.1.0/24,DIRECT", "127.0.0.1", "192.168.1.100", True),
            ("IP-CIDR,192.168.1.0/24,DIRECT", "127.0.0.1", "192.168.2.100", False),
            ("IP-CIDR,2001:db8::/32,DIRECT", "127.0.0.1", "2001:db8:1:1:1:1:1:1", True),
            ("IP-CIDR,2001:db8::/32,DIRECT", "127.0.0.1", "2001:db9::1", False),
            ("IP-CIDR,2001:db8::/32,DIRECT", "127.0.0.1", "8.8.8.8", False),
            # IP-SUFFIX tests
            ("IP-SUFFIX,10.20.30.201/8,DIRECT", "127.0.0.1", "192.168.1.201", True),
            ("IP-SUFFIX,10.20.30.201/8,DIRECT", "127.0.0.1", "192.168.1.200", False),
            ("IP-SUFFIX,10.20.30.201/16,DIRECT", "127.0.0.1", "192.168.30.201", True),
            ("IP-SUFFIX,10.20.30.201/16,DIRECT", "127.0.0.1", "192.168.31.201", False),
            # SRC-IP-CIDR tests
            ("SRC-IP-CIDR,10.0.0.0/8,DIRECT", "10.0.0.5", "192.168.1.1", True),
            ("SRC-IP-CIDR,10.0.0.0/8,DIRECT", "12.0.0.5", "192.168.1.1", False),
            # SRC-IP-SUFFIX tests
            (
                "SRC-IP-SUFFIX,192.168.1.201/16,DIRECT",
                "10.20.1.201",
                "192.168.1.1",
                True,
            ),
            (
                "SRC-IP-SUFFIX,192.168.1.201/16,DIRECT",
                "10.20.2.201",
                "192.168.1.1",
                False,
            ),
        ],
    )
    def test_ip_matches(
        self, rule: str, client_ip: str, server_ip: str, expected: bool
    ):
        flow: HTTPFlow = tflow.tflow()
        flow.client_conn.peername = (client_ip, 12345)
        # For server connection, mitmproxy uses .address for the destination address
        # but our matcher uses peername. In real scenarios, after connection, they would be related.
        # For testing, we set both to be safe.
        flow.server_conn.address = (server_ip, 80)
        flow.server_conn.peername = (server_ip, 80)

        clash_rule = ClashRuleParser.parse_rule_line(rule)
        assert clash_rule is not None
        assert HttpFlowMatcher.matches(clash_rule, flow) == expected
