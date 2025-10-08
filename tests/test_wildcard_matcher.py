import pytest
from mitmproxy.http import HTTPFlow
from mitmproxy.test import tflow

from app.schemas import ClashRule, RoutingRuleType
from app.utils.rule import HttpFlowMatcher


class TestHttpFlowMatcherWildcard:
    @pytest.mark.parametrize(
        "rule, url, expected",
        [
            # Wildcard *
            (
                ClashRule(
                    rule_type=RoutingRuleType.DOMAIN_WILDCARD,
                    payload="*.baidu.com",
                    action="DIRECT",
                    raw_rule="DOMAIN-WILDCARD,*.baidu.com,DIRECT",
                ),
                "http://tieba.baidu.com/",
                True,
            ),
            (
                ClashRule(
                    rule_type=RoutingRuleType.DOMAIN_WILDCARD,
                    payload="*.baidu.com",
                    action="DIRECT",
                    raw_rule="DOMAIN-WILDCARD,*.baidu.com,DIRECT",
                ),
                "http://123.tieba.baidu.com/",
                False,
            ),
            (
                ClashRule(
                    rule_type=RoutingRuleType.DOMAIN_WILDCARD,
                    payload="*.baidu.com",
                    action="DIRECT",
                    raw_rule="DOMAIN-WILDCARD,*.baidu.com,DIRECT",
                ),
                "http://baidu.com/",
                False,
            ),
            # Wildcard +
            (
                ClashRule(
                    rule_type=RoutingRuleType.DOMAIN_WILDCARD,
                    payload="+.baidu.com",
                    action="DIRECT",
                    raw_rule="DOMAIN-WILDCARD,+.baidu.com,DIRECT",
                ),
                "http://tieba.baidu.com/",
                True,
            ),
            (
                ClashRule(
                    rule_type=RoutingRuleType.DOMAIN_WILDCARD,
                    payload="+.baidu.com",
                    action="DIRECT",
                    raw_rule="DOMAIN-WILDCARD,+.baidu.com,DIRECT",
                ),
                "http://123.tieba.baidu.com/",
                True,
            ),
            (
                ClashRule(
                    rule_type=RoutingRuleType.DOMAIN_WILDCARD,
                    payload="+.baidu.com",
                    action="DIRECT",
                    raw_rule="DOMAIN-WILDCARD,+.baidu.com,DIRECT",
                ),
                "http://baidu.com/",
                True,
            ),
            # Wildcard .
            (
                ClashRule(
                    rule_type=RoutingRuleType.DOMAIN_WILDCARD,
                    payload=".baidu.com",
                    action="DIRECT",
                    raw_rule="DOMAIN-WILDCARD,.baidu.com,DIRECT",
                ),
                "http://tieba.baidu.com/",
                True,
            ),
            (
                ClashRule(
                    rule_type=RoutingRuleType.DOMAIN_WILDCARD,
                    payload=".baidu.com",
                    action="DIRECT",
                    raw_rule="DOMAIN-WILDCARD,.baidu.com,DIRECT",
                ),
                "http://123.tieba.baidu.com/",
                True,
            ),
            (
                ClashRule(
                    rule_type=RoutingRuleType.DOMAIN_WILDCARD,
                    payload=".baidu.com",
                    action="DIRECT",
                    raw_rule="DOMAIN-WILDCARD,.baidu.com,DIRECT",
                ),
                "http://baidu.com/",
                False,
            ),
        ],
    )
    def test_matches(self, rule: ClashRule, url: str, expected: bool):
        from urllib.parse import urlparse

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
        assert HttpFlowMatcher.matches(rule, flow) == expected
